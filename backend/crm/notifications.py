"""E-mails da plataforma aos gestores (Painel Admin, Notificações): envio manual e lembretes automáticos.

Automáticos (rodados uma vez por dia por `processar_automaticas`): lembrete de cobrança N dias antes do vencimento, avisos de fim de
teste (7/3/1/0 dias), cobrança em atraso por faixa (+ aviso de desligamento no atraso longo) e chave de API de agente perto de
expirar. Cada aviso tem uma `chave` e nunca é reenviado. Este módulo só AVISA: o desligamento de agentes por atraso não é automático.
"""
import re
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from . import billing
from .models import Cobranca, Company, ConfigNotificacao, Gestor, NotificacaoEnviada
from .services import _status_conta_agente

ASSUNTOS = {
    "cobranca": "Lembrete: mensalidade vence em {vencimento}",
    "teste": "O teste de {empresa} termina em {fim_do_teste}",
    "atraso": "Mensalidade em atraso desde {vencimento}",
    "desligamento": "Aviso: agentes serão desligados por atraso no pagamento",
    "chave": "A chave de API do agente {agente} expira em {chave_expira_em}",
}


def config():
    return ConfigNotificacao.objects.first() or ConfigNotificacao.objects.create(teste_dias_avisos=[7, 3, 1, 0], chave_dias_avisos=[30, 7])


def renderizar(texto, contexto):
    """Troca {variavel} pelos valores; variável desconhecida fica como está (a tela lista as disponíveis)."""
    return re.sub(r"\{(\w+)\}", lambda m: str(contexto.get(m.group(1), m.group(0))), texto or "")


def _brl(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _data(d):
    return d.strftime("%d/%m/%Y") if d else "—"


def contexto_do_gestor(gestor, **extra):
    return {"gestor": gestor.nome, **extra}


def enviar(gestor, tipo, assunto, corpo, chave="", user=None, cc=False, anexos=None):
    """Envia e registra um e-mail ao gestor. Com `chave`, não repete um aviso já enviado. Devolve a NotificacaoEnviada (ou None se já enviado).
    `anexos`: lista de (nome, bytes, tipo_mime)."""
    if chave and NotificacaoEnviada.objects.filter(chave=chave, estado="enviado").exists():
        return None
    cfg = config()
    registro = NotificacaoEnviada(gestor=gestor, gestor_nome=gestor.nome, para=gestor.email, tipo=tipo, assunto=assunto[:250], corpo=corpo, chave=chave, criado_por=user, anexos=[a[0] for a in anexos or []])
    if not gestor.email:
        registro.estado, registro.erro = "falhou", "Gestor sem e-mail cadastrado."
        registro.save()
        return registro
    try:
        mensagem = EmailMessage(assunto, corpo, from_email=cfg.remetente or settings.DEFAULT_FROM_EMAIL, to=[gestor.email], cc=[cfg.cc] if (cc and cfg.cc) else None)
        for nome, conteudo, mime in anexos or []:
            mensagem.attach(nome, conteudo, mime)
        mensagem.send(fail_silently=False)
    except Exception as exc:  # SMTP fora do ar, endereço recusado etc.: registra e segue
        registro.estado, registro.erro = "falhou", str(exc)[:300]
    registro.save()
    return registro


VARIAVEIS = ("gestor", "empresa", "valor", "vencimento", "fim_do_teste", "agente", "chave_expira_em", "dias_desligamento")


def contexto_completo(gestor, hoje=None):
    """Valores reais de cada variável para este gestor (envio manual). Sem dado correspondente, a variável não entra no contexto."""
    hoje = hoje or timezone.localdate()
    ctx = {"gestor": gestor.nome, "dias_desligamento": billing.regra().aviso_desligamento_dias}
    empresas = list(gestor.empresas.order_by("id"))
    if empresas:
        ctx["empresa"] = empresas[0].name if len(empresas) == 1 else ", ".join(e.name for e in empresas)
    fins = [(e.teste_inicio + timedelta(days=e.teste_dias), e) for e in empresas if e.em_teste and e.teste_inicio]
    if fins:
        fim, empresa = min(fins, key=lambda x: x[0])
        ctx["fim_do_teste"] = _data(fim)
        if len(empresas) > 1:
            ctx["empresa"] = empresa.name
    abertas = [c for c in gestor.cobrancas.prefetch_related("pagamentos") if billing.estado_da_cobranca(c, hoje)["status"] in ("a_receber", "em_atraso")]
    if abertas:
        c = min(abertas, key=lambda c: c.vencimento)
        ctx.update(valor=_brl(billing.estado_da_cobranca(c, hoje)["saldo"]), vencimento=_data(c.vencimento))
    validades = []
    for empresa in empresas:
        for usuario in empresa.members.filter(groups__name="agente"):
            v = _status_conta_agente(usuario, True)["validade"]
            if v and not v["expirado"]:
                validades.append((v["expires_at"].date(), usuario.username, empresa.name))
    if validades:
        dia, agente, empresa = min(validades)
        ctx.update(agente=agente, chave_expira_em=_data(dia))
        if "empresa" not in ctx or len(empresas) > 1:
            ctx["empresa"] = empresa
    return ctx


def variaveis_sem_valor(texto, ctx):
    return sorted({m for m in re.findall(r"\{(\w+)\}", texto or "") if m not in ctx})


def enviar_manual(gestor, assunto, corpo, user, anexos=None):
    ctx = contexto_completo(gestor)
    faltam = variaveis_sem_valor(assunto + " " + corpo, ctx)
    if faltam:  # nunca manda "{variavel}" crua ao gestor: registra a falha e explica
        registro = NotificacaoEnviada.objects.create(
            gestor=gestor, gestor_nome=gestor.nome, para=gestor.email, tipo="manual", assunto=assunto[:250], corpo=corpo, criado_por=user,
            estado="falhou", erro="Sem dado para " + ", ".join("{" + v + "}" for v in faltam) + " neste gestor.", anexos=[a[0] for a in anexos or []])
        return registro
    return enviar(gestor, "manual", renderizar(assunto, ctx), renderizar(corpo, ctx), user=user, anexos=anexos)


def _ctx_cobranca(c):
    estado = billing.estado_da_cobranca(c)
    return contexto_do_gestor(c.gestor, valor=_brl(estado["saldo"] or c.valor), vencimento=_data(c.vencimento), empresa="", dias_desligamento=billing.regra().aviso_desligamento_dias)


def processar_automaticas(hoje=None):
    """Roda os avisos do dia. Idempotente. Devolve {tipo: quantos foram enviados/registrados}."""
    hoje = hoje or timezone.localdate()
    cfg = config()
    regra = billing.regra()
    contagem = {"cobranca": 0, "teste": 0, "atraso": 0, "desligamento": 0, "chave": 0}
    mes = billing.mes_de(hoje)
    billing.gerar_cobrancas(mes)
    if hoje.day >= 20:  # a mensalidade do mês que vem já existe para o lembrete de "N dias antes" funcionar na virada
        billing.gerar_cobrancas((mes + timedelta(days=32)).replace(day=1))
    abertas = [c for c in Cobranca.objects.select_related("gestor").prefetch_related("pagamentos") if billing.estado_da_cobranca(c, hoje)["status"] in ("a_receber", "em_atraso")]

    def conta(tipo, registro):
        if registro is not None:
            contagem[tipo] += 1

    for c in abertas:
        estado = billing.estado_da_cobranca(c, hoje)
        ctx = _ctx_cobranca(c)
        if cfg.lembrete_cobranca_ativo and estado["status"] == "a_receber" and (c.vencimento - hoje).days == cfg.lembrete_dias_antes:
            conta("cobranca", enviar(c.gestor, "cobranca", renderizar(ASSUNTOS["cobranca"], ctx), renderizar(cfg.texto_cobranca, ctx), chave=f"cobranca:{c.pk}", cc=True))
        if estado["status"] == "em_atraso":
            faixa = estado["faixa"]
            if getattr(cfg, f"atraso_f{faixa}"):
                conta("atraso", enviar(c.gestor, "atraso", renderizar(ASSUNTOS["atraso"], ctx), renderizar(cfg.texto_atraso, ctx), chave=f"atraso:{c.pk}:{faixa}", cc=faixa >= 2))
            if faixa == 3 and cfg.atraso_f3:
                conta("desligamento", enviar(c.gestor, "desligamento", renderizar(ASSUNTOS["desligamento"], ctx), renderizar(cfg.texto_desligamento, ctx), chave=f"desligamento:{c.pk}", cc=True))
    if cfg.teste_ativo:
        for empresa in Company.objects.filter(em_teste=True, gestor__isnull=False).select_related("gestor"):
            if not empresa.teste_inicio:
                continue
            fim = empresa.teste_inicio + timedelta(days=empresa.teste_dias)
            restam = (fim - hoje).days
            if restam in [int(d) for d in (cfg.teste_dias_avisos or [])]:
                ctx = contexto_do_gestor(empresa.gestor, empresa=empresa.name, fim_do_teste=_data(fim))
                conta("teste", enviar(empresa.gestor, "teste", renderizar(ASSUNTOS["teste"], ctx), renderizar(cfg.texto_teste, ctx), chave=f"teste:{empresa.pk}:{restam}:{fim}"))
    if cfg.chave_ativo:
        for empresa in Company.objects.filter(gestor__isnull=False).select_related("gestor"):
            for usuario in empresa.members.filter(groups__name="agente"):
                estado = _status_conta_agente(usuario, True)
                validade = estado["validade"]
                if not validade or validade["expirado"]:
                    continue
                restam = (validade["expires_at"].date() - hoje).days
                if restam in [int(d) for d in (cfg.chave_dias_avisos or [])]:
                    ctx = contexto_do_gestor(empresa.gestor, empresa=empresa.name, agente=usuario.username, chave_expira_em=_data(validade["expires_at"].date()))
                    conta("chave", enviar(empresa.gestor, "chave", renderizar(ASSUNTOS["chave"], ctx), renderizar(cfg.texto_chave, ctx), chave=f"chave:{usuario.pk}:{restam}:{validade['expires_at'].date()}"))
    return contagem


def painel_de_chaves(hoje=None):
    """Chaves de API por gestor → empresa → agente: validade da chave do CRM e a referência da chave da OpenAI do gestor."""
    hoje = hoje or timezone.localdate()
    saida = []
    for g in Gestor.objects.all():
        agentes = []
        for empresa in g.empresas.order_by("id"):
            for usuario in empresa.members.filter(groups__name="agente").order_by("pk"):
                estado = _status_conta_agente(usuario, True)
                v = estado["validade"]
                dias = (v["expires_at"].date() - hoje).days if v else None
                situacao = "sem_chave" if not estado["masked_key"] else "sem_validade" if not v else "expirada" if v["expirado"] else "expira" if dias <= 30 else "valida"
                agentes.append({"agente": usuario.username, "empresa": empresa.name, "chave": estado["masked_key"], "expira_em": v["expires_at"].date() if v else None, "dias": dias, "situacao": situacao})
        saida.append({
            "gestor_id": g.pk, "gestor": g.nome, "email": g.email, "agentes": agentes,
            "openai": {"modo": g.openai_modo, "projeto": g.openai_projeto, "chave_final": g.openai_chave_final, "limite_mensal": str(g.openai_limite_mensal) if g.openai_limite_mensal is not None else None},
        })
    return saida
