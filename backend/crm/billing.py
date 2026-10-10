"""Faturamento da plataforma (Painel Admin): cobranças por gestor, pagamentos, inadimplência e contratos.

Convenções:
- A mensalidade de um mês é fotografada na emissão (`Cobranca.valor` e `Cobranca.linhas`): mudar a tabela de valores depois
  não altera cobranças já emitidas. Os preços vêm de PrecoCobranca na data de vencimento.
- Empresa em teste não cobra mensalidade: o piloto vira uma cobrança própria (tipo "piloto") no mês em que o teste começou.
- A 1ª empresa contratada do gestor (por id) é o plano base; as demais, "empresa adicional"; cada agente além do primeiro de
  uma empresa, "agente adicional".
- Pro-rata: no mês de início do contrato cobra só os dias de uso (do início ao fim do mês). Desconto por tempo: vale o maior
  percentual cujo prazo (em meses de contrato) já passou. Ambos entram como linhas negativas.
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import Cobranca, Company, Gestor, Pagamento, RegraCobranca
from .services import ITENS_COBRANCA, _nome_usuario, preco_vigente

CENTAVOS = Decimal("0.01")


def _q(valor):
    return Decimal(valor).quantize(CENTAVOS)


def regra():
    return RegraCobranca.objects.first() or RegraCobranca.objects.create(descontos=[[12, 5], [24, 10], [36, 12]])


def mes_de(d):
    return d.replace(day=1)


def parse_mes(texto):
    """'2026-10' -> date(2026, 10, 1); vazio = mês atual. ValueError com mensagem para a tela."""
    if not texto:
        return mes_de(timezone.localdate())
    try:
        ano, mes = str(texto)[:7].split("-")
        return date(int(ano), int(mes), 1)
    except (ValueError, TypeError):
        raise ValueError("Mês inválido (use AAAA-MM).")


def _vencimento(gestor, ref):
    return ref.replace(day=min(max(gestor.dia_vencimento, 1), 28))


def _agentes(company):
    return list(company.members.filter(groups__name="agente").order_by("pk").values_list("username", flat=True))


def _preco(item, quando):
    p = preco_vigente(item, quando)
    return p.valor if p else Decimal("0")


def meses_de_contrato(gestor, ref):
    if not gestor.contrato_inicio:
        return 0
    i = gestor.contrato_inicio
    return max(0, (ref.year - i.year) * 12 + (ref.month - i.month))


def montar_linhas_mensalidade(gestor, ref):
    """Linhas da mensalidade do mês (com pro-rata e desconto por tempo). Lista vazia = nada a cobrar."""
    quando = _vencimento(gestor, ref)
    r = regra()
    contratadas = [c for c in gestor.empresas.order_by("id") if not c.em_teste]
    linhas = []
    for idx, c in enumerate(contratadas):
        agentes = _agentes(c)
        item = "base" if idx == 0 else "empresa_adicional"
        linhas.append({"descricao": f"{ITENS_COBRANCA[item]['nome']} · {c.name}", "valor": _q(_preco(item, quando)), "empresa": c.name, "agente": agentes[0] if agentes else ""})
        for extra in agentes[1:]:
            linhas.append({"descricao": f"Agente adicional · {c.name}", "valor": _q(_preco("agente_adicional", quando)), "empresa": c.name, "agente": extra})
    if not linhas:
        return []
    bruto = sum((l["valor"] for l in linhas), Decimal("0"))
    corrente = bruto
    inicio = gestor.contrato_inicio
    if r.prorata_ativo and inicio and mes_de(inicio) == ref:
        dias_mes = calendar.monthrange(ref.year, ref.month)[1]
        usados = dias_mes - inicio.day + 1
        if usados < dias_mes:
            desconto = _q(bruto * Decimal(dias_mes - usados) / Decimal(dias_mes))
            linhas.append({"descricao": f"Pro-rata do 1º mês ({usados} de {dias_mes} dias)", "valor": -desconto, "empresa": "", "agente": ""})
            corrente = bruto - desconto
    meses = meses_de_contrato(gestor, ref)
    pct = max([int(p) for m, p in (r.descontos or []) if meses >= int(m)] or [0])
    if pct:
        desconto = _q(corrente * Decimal(pct) / Decimal(100))
        linhas.append({"descricao": f"Desconto por tempo de contrato ({pct}%)", "valor": -desconto, "empresa": "", "agente": ""})
    return linhas


def _linhas_json(linhas):
    return [{**l, "valor": str(l["valor"])} for l in linhas]


def _total(linhas):
    return max(Decimal("0"), sum((Decimal(str(l["valor"])) for l in linhas), Decimal("0")))


@transaction.atomic
def gerar_cobrancas(ref):
    """Emite (uma única vez por gestor/mês) a mensalidade e, quando um teste começou no mês, a cobrança do piloto. Idempotente."""
    criadas = 0
    for g in Gestor.objects.all():
        venc = _vencimento(g, ref)
        linhas = montar_linhas_mensalidade(g, ref)
        if linhas and not Cobranca.objects.filter(gestor=g, tipo="mensalidade", referencia=ref).exists():
            Cobranca.objects.create(gestor=g, tipo="mensalidade", referencia=ref, vencimento=venc, valor=_total(linhas), linhas=_linhas_json(linhas))
            criadas += 1
        pilotos = [c for c in g.empresas.order_by("id") if c.em_teste and c.teste_inicio and mes_de(c.teste_inicio) == ref]
        if pilotos and not Cobranca.objects.filter(gestor=g, tipo="piloto", referencia=ref).exists():
            valor = _q(_preco("piloto", venc))
            ls = [{"descricao": f"Piloto · {c.name}", "valor": valor, "empresa": c.name, "agente": (_agentes(c) or [""])[0]} for c in pilotos]
            Cobranca.objects.create(gestor=g, tipo="piloto", referencia=ref, vencimento=venc, valor=_total(ls), linhas=_linhas_json(ls))
            criadas += 1
    return criadas


@transaction.atomic
def gerar_implantacao(gestor, hoje=None):
    """Cobrança única de implantação, já descontado o piloto pago (se a regra de abatimento estiver ligada)."""
    hoje = hoje or timezone.localdate()
    ref = mes_de(hoje)
    if Cobranca.objects.filter(gestor=gestor, tipo="implantacao").exists():
        raise ValueError("Este gestor já tem a cobrança de implantação.")
    r = regra()
    ls = [{"descricao": "Implantação inicial", "valor": _q(_preco("implantacao", hoje)), "empresa": "", "agente": ""}]
    if r.abater_piloto:
        pago = Pagamento.objects.filter(cobranca__gestor=gestor, cobranca__tipo="piloto").aggregate(t=Sum("valor"))["t"] or Decimal("0")
        abatimento = _q(pago * Decimal(r.abatimento_pct) / Decimal(100))
        if abatimento > 0:
            ls.append({"descricao": f"Abatimento do piloto ({r.abatimento_pct}%)", "valor": -min(abatimento, ls[0]["valor"]), "empresa": "", "agente": ""})
    return Cobranca.objects.create(gestor=gestor, tipo="implantacao", referencia=ref, vencimento=_vencimento(gestor, ref) if _vencimento(gestor, ref) >= hoje else hoje + timedelta(days=7), valor=_total(ls), linhas=_linhas_json(ls))


def pago_de(cobranca):
    return cobranca.pagamentos.aggregate(t=Sum("valor"))["t"] or Decimal("0")


def estado_da_cobranca(cobranca, hoje=None):
    """{status, pago, saldo, dias_atraso, faixa}: status = recebido | a_receber | em_atraso | sem_cobranca; faixa 1/2/3 (só em atraso)."""
    hoje = hoje or timezone.localdate()
    pago = pago_de(cobranca)
    saldo = cobranca.valor - pago
    if cobranca.valor <= 0:
        return {"status": "sem_cobranca", "pago": pago, "saldo": Decimal("0"), "dias_atraso": 0, "faixa": 0}
    if saldo <= 0:
        return {"status": "recebido", "pago": pago, "saldo": Decimal("0"), "dias_atraso": 0, "faixa": 0}
    atraso = (hoje - cobranca.vencimento).days
    if atraso > 0:
        r = regra()
        faixa = 1 if atraso <= r.faixa_atraso_curta else 2 if atraso <= r.faixa_atraso_media else 3
        return {"status": "em_atraso", "pago": pago, "saldo": saldo, "dias_atraso": atraso, "faixa": faixa}
    return {"status": "a_receber", "pago": pago, "saldo": saldo, "dias_atraso": 0, "faixa": 0}


EXTENSOES_ANEXO = {".pdf": b"%PDF", ".png": b"\x89PNG", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff", ".webp": b"RIFF"}
TAMANHO_MAXIMO_ANEXO = 5 * 1024 * 1024


def validar_anexo(arquivo):
    """PDF ou imagem (PNG/JPEG/WEBP) de até 5 MB; confere também o início do arquivo, não só a extensão."""
    nome = (getattr(arquivo, "name", "") or "").lower()
    ext = nome[nome.rfind("."):] if "." in nome else ""
    if ext not in EXTENSOES_ANEXO:
        raise ValueError("Anexe um PDF ou uma imagem (PNG, JPG ou WEBP).")
    if arquivo.size > TAMANHO_MAXIMO_ANEXO:
        raise ValueError("O anexo passa de 5 MB.")
    inicio = arquivo.read(12)
    arquivo.seek(0)
    if not inicio.startswith(EXTENSOES_ANEXO[ext]):
        raise ValueError("O conteúdo do arquivo não corresponde ao tipo informado.")


@transaction.atomic
def registrar_pagamento(cobranca, data, valor, forma, comprovante, user, arquivo=None):
    """Registra um recebimento (valor em branco = o saldo). Aceita pagamento parcial, nunca acima do saldo."""
    saldo = cobranca.valor - pago_de(cobranca)
    if saldo <= 0:
        raise ValueError("Esta cobrança já está quitada.")
    if valor in (None, ""):
        valor = saldo
    try:
        valor = _q(Decimal(str(valor).replace(",", ".")))
    except (InvalidOperation, ValueError):
        raise ValueError("Informe um valor numérico.")
    if valor <= 0:
        raise ValueError("O valor do pagamento precisa ser maior que zero.")
    if valor > saldo:
        raise ValueError(f"O valor passa do saldo da cobrança (R$ {saldo}).")
    if isinstance(data, str):
        try:
            data = date.fromisoformat(data[:10])
        except ValueError:
            raise ValueError("Informe a data do pagamento (AAAA-MM-DD).")
    data = data or timezone.localdate()
    if forma not in dict(Gestor.FORMAS):
        forma = cobranca.gestor.forma_pagamento
    if arquivo:
        validar_anexo(arquivo)
    return Pagamento.objects.create(cobranca=cobranca, data=data, valor=valor, forma=forma, comprovante=(comprovante or "")[:300], comprovante_arquivo=arquivo or "", registrado_por=user)


def _str(d):
    return str(_q(d))


def _item_cobranca(c, hoje):
    e = estado_da_cobranca(c, hoje)
    ultimo = c.pagamentos.first()
    return {
        "id": c.pk, "gestor_id": c.gestor_id, "gestor": c.gestor.nome, "forma": c.gestor.forma_pagamento, "tipo": c.tipo, "tipo_rotulo": dict(Cobranca.TIPOS)[c.tipo],
        "referencia": c.referencia, "vencimento": c.vencimento, "valor": _str(c.valor), "pago": _str(e["pago"]), "saldo": _str(e["saldo"]),
        "status": e["status"], "dias_atraso": e["dias_atraso"], "faixa": e["faixa"], "linhas": c.linhas, "recebido_em": ultimo.data if ultimo and e["status"] == "recebido" else None,
    }


def contratos(hoje=None):
    hoje = hoje or timezone.localdate()
    r = regra()
    saida = []
    for g in Gestor.objects.all():
        ini = g.contrato_inicio
        prox = None
        if ini:
            prox = ini.replace(year=hoje.year)
            if prox <= hoje:
                prox = prox.replace(year=hoje.year + 1)
        meses = meses_de_contrato(g, hoje)
        pct = max([int(p) for m, p in (r.descontos or []) if meses >= int(m)] or [0])
        impl = g.cobrancas.filter(tipo="implantacao").first()
        dias = (prox - hoje).days if prox else None
        saida.append({
            "gestor_id": g.pk, "gestor": g.nome, "contrato_inicio": ini, "indice": g.indice_reajuste, "proximo_reajuste": prox, "dias_para_reajuste": dias,
            "alerta_reajuste": dias is not None and dias <= r.alerta_reajuste_dias, "desconto_por_tempo_pct": pct,
            "implantacao": (estado_da_cobranca(impl, hoje)["status"] if impl else "nao_cobrada"),
            "em_teste": g.empresas.filter(em_teste=True).exists(),
        })
    return saida


def resumo_faturamento(ref, hoje=None):
    hoje = hoje or timezone.localdate()
    gerar_cobrancas(ref)
    do_mes = list(Cobranca.objects.filter(referencia=ref).select_related("gestor").prefetch_related("pagamentos"))
    itens = [_item_cobranca(c, hoje) for c in do_mes]
    previsto = sum((Decimal(i["valor"]) for i in itens), Decimal("0"))
    recebido = sum((Decimal(i["pago"]) for i in itens), Decimal("0"))
    atraso = sum((Decimal(i["saldo"]) for i in itens if i["status"] == "em_atraso"), Decimal("0"))
    por_empresa, por_agente = {}, {}
    for c in do_mes:
        for l in c.linhas:
            v = Decimal(l["valor"])
            if l.get("empresa"):
                e = por_empresa.setdefault(l["empresa"], {"empresa": l["empresa"], "gestor": c.gestor.nome, "valor": Decimal("0"), "linhas": []})
                e["valor"] += v
                e["linhas"].append(l["descricao"])
            if l.get("agente"):
                a = por_agente.setdefault(l["agente"], {"agente": l["agente"], "empresa": l["empresa"], "gestor": c.gestor.nome, "valor": Decimal("0"), "linhas": []})
                a["valor"] += v
                a["linhas"].append(l["descricao"])
    abertas = [c for c in Cobranca.objects.select_related("gestor").prefetch_related("pagamentos") if estado_da_cobranca(c, hoje)["status"] == "em_atraso"]
    faixas = {1: {"n": 0, "valor": Decimal("0")}, 2: {"n": 0, "valor": Decimal("0")}, 3: {"n": 0, "valor": Decimal("0")}}
    atrasados = []
    for c in abertas:
        e = estado_da_cobranca(c, hoje)
        faixas[e["faixa"]]["n"] += 1
        faixas[e["faixa"]]["valor"] += e["saldo"]
        atrasados.append({"cobranca_id": c.pk, "gestor": c.gestor.nome, "tipo_rotulo": dict(Cobranca.TIPOS)[c.tipo], "saldo": _str(e["saldo"]), "vencimento": c.vencimento, "dias_atraso": e["dias_atraso"], "faixa": e["faixa"]})
    r = regra()
    pagamentos = [
        {"id": p.pk, "data": p.data, "gestor": p.cobranca.gestor.nome, "referencia": f"{dict(Cobranca.TIPOS)[p.cobranca.tipo]} · {p.cobranca.referencia:%m/%Y}", "valor": _str(p.valor),
         "forma": p.forma, "comprovante": p.comprovante, "comprovante_arquivo": p.comprovante_arquivo.name.rsplit("/", 1)[-1] if p.comprovante_arquivo else "", "por": _nome_usuario(p.registrado_por), "criado_em": p.criado_em}
        for p in Pagamento.objects.select_related("cobranca__gestor", "registrado_por")[:50]
    ]
    serie = []
    for k in range(5, -1, -1):
        m = ref.month - k
        a = ref.year + (m - 1) // 12
        mm = (m - 1) % 12 + 1
        d = date(a, mm, 1)
        serie.append({"mes": d, "valor": _str(Cobranca.objects.filter(referencia=d, tipo="mensalidade").aggregate(t=Sum("valor"))["t"] or Decimal("0")), "projecao": False})
    atual = Decimal(serie[-1]["valor"])
    for k in range(1, 4):
        m = ref.month + k
        d = date(ref.year + (m - 1) // 12, (m - 1) % 12 + 1, 1)
        serie.append({"mes": d, "valor": _str(atual), "projecao": True})
    return {
        "mes": ref, "kpis": {"previsto": _str(previsto), "recebido": _str(recebido), "a_receber": _str(max(Decimal("0"), previsto - recebido - atraso)), "em_atraso": _str(atraso)},
        "cobrancas": itens, "por_empresa": [{**e, "valor": _str(e["valor"])} for e in por_empresa.values()], "por_agente": [{**a, "valor": _str(a["valor"])} for a in por_agente.values()],
        "inadimplencia": {"faixas": [{"faixa": k, "n": v["n"], "valor": _str(v["valor"])} for k, v in faixas.items()], "atrasados": atrasados,
                          "limites": {"curta": r.faixa_atraso_curta, "media": r.faixa_atraso_media, "aviso_desligamento_dias": r.aviso_desligamento_dias}},
        "pagamentos": pagamentos, "contratos": contratos(hoje), "recorrente": serie,
    }
