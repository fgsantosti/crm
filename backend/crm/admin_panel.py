"""Agregados do Painel Admin (só superuser): Visão geral e Leads. Só números e nomes de empresas/gestores, nunca conversas."""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Max, Sum
from django.utils import timezone

from . import billing, notifications
from .models import Cobranca, Company, ContagemDiaria, Gestor, Lead, NotificacaoEnviada, Pagamento
from .services import NOMES_CLASSIFICACAO, _categoria_status, fora_do_kanban

PERIODOS = {"30": 30, "90": 90, "all": None}
# Ordem de exibição das fatias do gráfico "Tipos de atendimento" (a chave vem de services._categoria_status).
TIPOS = [("automatico", "Em triagem"), ("aguardando", "Triagem concluída"), ("equipe", "Com a equipe"), ("despachado", "Despachos"), ("especial", "Outras situações"), ("desqualificado", "Desqualificados"), ("nao_prosseguiram", "Não prosseguiram")]


def _meses_anteriores(n, hoje):
    """Primeiros dias dos últimos n meses, do mais antigo ao atual."""
    saida, ano, mes = [], hoje.year, hoje.month
    for _ in range(n):
        saida.append(hoje.replace(year=ano, month=mes, day=1))
        mes -= 1
        if mes == 0:
            ano, mes = ano - 1, 12
    return saida[::-1]


def leads_do_admin(periodo="30", gestor_id=None, hoje=None):
    """Leads de todas as empresas (ou do gestor): resumo, tipos de atendimento, série mensal (6 meses) e quadro por empresa."""
    hoje = hoje or timezone.localdate()
    dias = PERIODOS.get(periodo, 30)
    empresas = Company.objects.select_related("gestor").order_by("name")
    if gestor_id:
        empresas = empresas.filter(gestor_id=gestor_id)
    desde = timezone.now() - timedelta(days=dias) if dias else None
    desde_dia = timezone.localdate(desde) if desde else None
    meses = _meses_anteriores(6, hoje)
    serie = {m.strftime("%Y-%m"): 0 for m in meses}
    tipos = {k: 0 for k, _ in TIPOS}
    classif_total = {t: 0 for t in NOMES_CLASSIFICACAO}
    linhas = []
    for empresa in empresas:
        fora = fora_do_kanban(empresa)
        base = Lead.objects.filter(company=empresa)
        for l in base.filter(created_at__gte=timezone.make_aware(datetime.combine(meses[0], time.min))).values_list("created_at", flat=True):
            chave = timezone.localtime(l).strftime("%Y-%m")
            if chave in serie:
                serie[chave] += 1
        for dia, nao in ContagemDiaria.objects.filter(company=empresa, data__gte=meses[0]).values_list("data", "nao_prosseguiram"):
            chave = dia.strftime("%Y-%m")
            if chave in serie:
                serie[chave] += nao
        qs = base.filter(created_at__gte=desde) if desde else base
        temps = {t: 0 for t in NOMES_CLASSIFICACAO}
        tipos_empresa = {k: 0 for k, _ in TIPOS}
        total = 0
        for r in qs.values("desfecho", "bot_closed", "mode", "temperature", "origem_manual", "etapa_atendimento", "situacao_especial"):
            tipos_empresa[_categoria_status(r, fora)] += 1
            if r["temperature"] in temps:
                temps[r["temperature"]] += 1
            total += 1
        contagens = ContagemDiaria.objects.filter(company=empresa)
        if desde_dia:
            contagens = contagens.filter(data__gte=desde_dia)
        nao = contagens.aggregate(n=Sum("nao_prosseguiram"))["n"] or 0
        tipos_empresa["nao_prosseguiram"] = nao
        for k, v in tipos_empresa.items():
            tipos[k] += v
        for t, v in temps.items():
            classif_total[t] += v
        linhas.append({"empresa_id": empresa.pk, "empresa": empresa.name, "gestor": empresa.gestor.nome if empresa.gestor else "", "total": total + nao, "temperaturas": temps, "nao_prosseguiram": nao})
    total = sum(l["total"] for l in linhas)
    classificados = sum(classif_total.values())
    return {
        "periodo": periodo,
        "resumo": {"atendimentos": total, "classificados": classificados, "quentes": classif_total.get("Quente", 0), "nao_prosseguiram": tipos["nao_prosseguiram"]},
        "tipos": [{"chave": k, "rotulo": r, "valor": tipos[k]} for k, r in TIPOS],
        "mensal": [{"mes": m, "valor": v} for m, v in serie.items()],
        "temperaturas": NOMES_CLASSIFICACAO[::-1],
        "empresas": linhas,
        "gestores": [{"id": g.pk, "nome": g.nome} for g in Gestor.objects.order_by("nome")],
    }


def _agentes(empresa):
    return empresa.members.filter(groups__name="agente")


def visao_geral(hoje=None):
    """Indicadores, alertas, volume por empresa, faturamento por gestor e atividade recente."""
    hoje = hoje or timezone.localdate()
    User = get_user_model()
    empresas = list(Company.objects.select_related("gestor").order_by("name"))
    gestores = list(Gestor.objects.select_related("usuario").order_by("nome"))
    n_agentes = {e.pk: _agentes(e).count() for e in empresas}
    adicionais = sum(max(0, n - 1) for n in n_agentes.values())
    mes = billing.mes_de(hoje)
    billing.gerar_cobrancas(mes)
    mensalidades = {c.gestor_id: c for c in Cobranca.objects.filter(referencia=mes, tipo="mensalidade")}
    estimada = sum((c.valor for c in mensalidades.values()), Decimal("0"))
    # volume por empresa nos últimos 30 dias (leads + os que não prosseguiram)
    desde = timezone.now() - timedelta(days=30)
    ultimo = dict(Lead.objects.values_list("company_id").annotate(m=Max("created_at")))
    volume = []
    for e in empresas:
        n = Lead.objects.filter(company=e, created_at__gte=desde).count()
        n += ContagemDiaria.objects.filter(company=e, data__gte=timezone.localdate(desde)).aggregate(t=Sum("nao_prosseguiram"))["t"] or 0
        volume.append({"empresa_id": e.pk, "empresa": e.name, "leads": n})
    volume.sort(key=lambda v: -v["leads"])
    sem_acesso = [g for g in gestores if g.usuario and not g.usuario.last_login]
    alertas = []
    for g in notifications.painel_de_chaves(hoje):
        for a in g["agentes"]:
            if a["situacao"] == "expirada":
                alertas.append({"tipo": "chave", "titulo": "Chave do CRM expirada", "detalhe": f"{a['empresa']} · {a['agente']}", "gravidade": "alta"})
            elif a["situacao"] == "expira" and a["dias"] is not None:
                alertas.append({"tipo": "chave", "titulo": f"Chave do CRM expira em {a['dias']} dias", "detalhe": f"{a['empresa']} · {a['agente']}", "gravidade": "media"})
    for c in billing.resumo_faturamento(mes, hoje)["inadimplencia"]["atrasados"]:
        alertas.append({"tipo": "cobranca", "titulo": f"Cobrança em atraso há {c['dias_atraso']} dias", "detalhe": f"{c['gestor']} · R$ {c['saldo']}", "gravidade": "alta"})
    for e in empresas:
        if e.em_teste and e.teste_inicio:
            restam = (e.teste_inicio + timedelta(days=e.teste_dias) - hoje).days
            if restam <= 3:
                alertas.append({"tipo": "teste", "titulo": "Teste termina hoje" if restam == 0 else f"Teste termina em {restam} dias" if restam > 0 else f"Teste vencido há {-restam} dias", "detalhe": e.name, "gravidade": "media"})
        ult = ultimo.get(e.pk)
        if n_agentes[e.pk] and (not ult or (timezone.now() - ult).days >= 7):
            alertas.append({"tipo": "empresa", "titulo": "Empresa sem lead há 7 dias" if ult else "Empresa ainda sem nenhum lead", "detalhe": f"{e.name}" + (f" · último lead em {timezone.localtime(ult):%d/%m}" if ult else ""), "gravidade": "baixa"})
        if not e.gestor_id:
            alertas.append({"tipo": "empresa", "titulo": "Empresa sem gestor", "detalhe": e.name, "gravidade": "baixa"})
    for g in sem_acesso:
        alertas.append({"tipo": "gestor", "titulo": "Gestor ainda não fez o primeiro acesso", "detalhe": g.nome, "gravidade": "baixa"})
    ordem = {"alta": 0, "media": 1, "baixa": 2}
    alertas.sort(key=lambda a: ordem[a["gravidade"]])
    faturamento = []
    for g in gestores:
        contratadas = [e for e in g.empresas.all() if not e.em_teste]
        extras = sum(max(0, n_agentes.get(e.pk, 0) - 1) for e in g.empresas.all())
        c = mensalidades.get(g.pk)
        faturamento.append({"gestor_id": g.pk, "gestor": g.nome, "empresas": len(contratadas), "extras": extras, "total": str(c.valor) if c else None})
    atividade = []
    for n in NotificacaoEnviada.objects.order_by("-criado_em")[:6]:
        atividade.append({"quando": n.criado_em, "texto": f"E-mail \"{n.assunto}\" para {n.gestor_nome or '—'}" + ("" if n.estado == "enviado" else " (falhou)")})
    for p in Pagamento.objects.select_related("cobranca__gestor").order_by("-criado_em")[:6]:
        atividade.append({"quando": p.criado_em, "texto": f"Pagamento de R$ {p.valor} de {p.cobranca.gestor.nome}"})
    for g in gestores:
        if g.usuario and g.usuario.last_login:
            atividade.append({"quando": g.usuario.last_login, "texto": f"{g.nome} entrou no CRM"})
        atividade.append({"quando": g.criado_em, "texto": f"Gestor {g.nome} cadastrado"})
    atividade.sort(key=lambda a: a["quando"], reverse=True)
    return {
        "kpis": {
            "mensalidade_estimada": str(estimada), "gestores": len(gestores), "gestores_sem_acesso": len(sem_acesso),
            "empresas": len(empresas), "empresas_sem_gestor": sum(1 for e in empresas if not e.gestor_id),
            "agentes": sum(n_agentes.values()), "agentes_adicionais": adicionais, "leads_30_dias": sum(v["leads"] for v in volume),
        },
        "alertas": alertas, "volume": volume, "faturamento": faturamento, "atividade": atividade[:6],
    }
