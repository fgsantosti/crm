from collections import Counter
import logging
import re
import secrets
from datetime import datetime, time, timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.authtoken.models import Token
from .emails import send_credentials_email, send_invite_email, send_email_change_code, send_password_reset_by_admin_email
from .models import Profile, Lead, Question, Event, Company, Blacklist, Area, AtendenteInvite, PasswordChangeRequired, EmailChangeRequest, AgentTokenExpiry, Variavel, VariavelRoteiro, VARIAVEL_DETALHAMENTO, PESO_PADRAO_DETALHAMENTO, CompanyInfo, MANDATORY_QUESTION_IDS, MANDATORY_OFFFLOW_QUESTION_IDS, TEXTO_PADRAO_LEMBRETE, DEFAULT_HUMAN_MESSAGE, SITUACOES_ESPECIAIS, ESPECIAL_QUESTION_IDS, ContagemDiaria

logger = logging.getLogger(__name__)

NO_REPLY = {"action": "NO_REPLY"}
RESERVED_QUESTION_IDS = {"validar", "encerramento", "necessidade_humana", "lembrete", *ESPECIAL_QUESTION_IDS}

# question_id -> (nome de exibição, slug/placeholder fixo) das 3 Variáveis de roteiro
# builtin: reaproveitam os placeholders já existentes (FIELD_MAP), sem precisar de
# armazenamento extra em Lead.variaveis_roteiro.
BUILTIN_VARIAVEL_ROTEIRO = {
    "nome": ("Nome", "nome"),
    "situacao": ("Área da Lead", "especialidade"),
    "demanda": ("Demanda", "tema"),
}

TEXTOS_PADRAO_ESPECIAIS = {v["question_id"]: v["texto_padrao"] for v in SITUACOES_ESPECIAIS.values()}

def variavel_detalhamento(company):
    """Variável do sistema "Detalhamento" (obrigatória em toda empresa): o CRM calcula a nota dela a partir
    do quanto o cliente contou (calcular_detalhamento) e ela entra na média da urgência com o peso
    que a conta Empresa definir."""
    variavel, _ = Variavel.objects.get_or_create(company=company, name=VARIAVEL_DETALHAMENTO, defaults={"peso": PESO_PADRAO_DETALHAMENTO, "builtin": True})
    if not variavel.builtin:
        variavel.builtin = True
        variavel.save(update_fields=["builtin"])
    return variavel

def seed_roteiro_padrao(company):
    """Garante o mínimo pra uma empresa nova conseguir operar o funil: a Variavel
    padrão, as 3 perguntas obrigatórias de triagem (nome/situacao/demanda) já
    atreladas às suas Variáveis de roteiro builtin, os textos fora do fluxo
    (apresentacao/empresa/validar/encerramento/necessidade_humana) e os 3 campos obrigatórios de Dados
    da empresa. Chamado na criação de empresa (AdminCompanyViewSet) e pela migração
    0012/0014 pras empresas que já existiam antes dessas features."""
    variavel, _ = Variavel.objects.get_or_create(company=company, name="Geral", defaults={"peso": 5})
    variavel_detalhamento(company)
    for ordem, question_id in enumerate(MANDATORY_QUESTION_IDS):
        label, slug = BUILTIN_VARIAVEL_ROTEIRO[question_id]
        vr, _ = VariavelRoteiro.objects.get_or_create(company=company, slug=slug, defaults={"name": label, "builtin": True})
        Question.objects.get_or_create(company=company, question_id=question_id, defaults={"obrigatoria": True, "variavel": variavel, "ordem": ordem, "variavel_roteiro": vr})
    for question_id in MANDATORY_OFFFLOW_QUESTION_IDS:
        Question.objects.get_or_create(company=company, question_id=question_id, defaults={
            "obrigatoria": True, "variavel": None,
            "text": DEFAULT_HUMAN_MESSAGE if question_id == "necessidade_humana" else TEXTO_PADRAO_LEMBRETE if question_id == "lembrete" else TEXTOS_PADRAO_ESPECIAIS.get(question_id, ""),
        })
    for title in CompanyInfo.MANDATORY_TITLES:
        CompanyInfo.objects.get_or_create(company=company, title=title, defaults={"obrigatorio": True})

def slugify_variavel_roteiro(company, name):
    """Deriva um slug/placeholder ({slug}) a partir do nome digitado: só letras
    minúsculas e '_', sem acento, único por empresa e nunca colidindo com um
    placeholder fixo já existente (empresa/nome/especialidade/tema/... -- ver
    FIELD_MAP) nem com outra Variável de roteiro já cadastrada."""
    import unicodedata
    base = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-zA-Z]+", "_", base).strip("_").lower() or "variavel"
    reservados = {"empresa", *FIELD_MAP.keys()}
    existentes = set(VariavelRoteiro.objects.filter(company=company).values_list("slug", flat=True))
    slug = base
    i = 2
    while slug in reservados or slug in existentes:
        slug = f"{base}_{i}"
        i += 1
    return slug

def proxima_cor_roteiro(company):
    paleta = VariavelRoteiro.PALETA_CORES
    usadas = VariavelRoteiro.objects.filter(company=company).count()
    return paleta[usadas % len(paleta)]

# Mapa dos campos que o agente Axioma envia em ATUALIZAR/VALIDAR/CLASSIFICADO
# para os campos reais do Lead. 'proxima' nunca é um campo do Lead: é o
# question_id da próxima pergunta, tratado separadamente.
FIELD_MAP = {
    "nome": "name",
    "especialidade": "especialidade",
    "tema": "demand",
    "impacto": "impacto",
    "interesse": "interesse",
    "temperatura": "temperature",
    "prioridade": "priority",
}

def normalizar_contato(valor):
    """Telefone como a pessoa digita -> E.164 (+55 quando falta DDI). None se inválido."""
    valor = (valor or "").strip()
    digitos = re.sub(r"\D", "", valor)
    if not digitos:
        return None
    if valor.startswith("+"):
        e164 = f"+{digitos}"
    elif digitos.startswith("55") and len(digitos) in (12, 13):
        e164 = f"+{digitos}"
    else:
        e164 = f"+55{digitos}"
    return e164 if re.fullmatch(r"\+[1-9]\d{7,14}", e164) else None

def escalate(lead, reason):
    lead.pedido_humano_pendente = False
    lead.mode = "HUMANO"
    lead.priority = "Alta"
    lead.next_action = reason
    if not lead.name.strip():
        lead.name = lead.contact_name
    if reason == "pedido humano":
        motivo = "Cliente pediu contato direto com atendente humano"
        if motivo not in lead.demand:
            demanda = lead.demand.strip()
            lead.demand = f"{demanda[:300 - len(motivo) - 3]} | {motivo}" if demanda else motivo
    lead.save()

LIMITE_OBSERVACOES = 1500
LIMITE_ITEM_OBSERVACAO = 200
# Observações guardam só dados não sensíveis: sequências longas de dígitos (CPF, telefone, conta,
# cartão) e senhas/códigos ditos no chat não entram, mesmo que o agente os envie.
_PADRAO_SENSIVEL = re.compile(r"(?:\d[\s.\-/]?){8,}|\b(?:senha|código|codigo|token)\b\s*(?:é|e|:|=)", re.I)

def mesclar_observacoes(atual, novas):
    """Observações do lead = itens curtos separados por ';'. O agente só acrescenta: itens já
    existentes (inclusive os editados pela atendente) são mantidos e repetições são ignoradas."""
    itens = [i.strip() for i in (atual or "").split(";") if i.strip()]
    vistos = {i.casefold() for i in itens}
    for bruto in re.split(r"[;\n]", str(novas or "")):
        item = re.sub(r"\s+", " ", bruto).strip()[:LIMITE_ITEM_OBSERVACAO].strip()
        if not item or item.casefold() in vistos or _PADRAO_SENSIVEL.search(item):
            continue
        if len("; ".join([*itens, item])) > LIMITE_OBSERVACOES:
            break
        itens.append(item)
        vistos.add(item.casefold())
    return "; ".join(itens)

_NUMERO_LONGO = re.compile(r"\d(?:[\s.\-/]?\d){7,}")
_SENHA_DITA = re.compile(r"\b((?:senha|código|codigo|token)\b\s*(?:é|e|:|=)\s*)\S+", re.I)

def redigir_dados_sensiveis(texto):
    """Histórico de conversa: o texto do cliente é guardado sem sequências longas de dígitos (CPF,
    telefone, conta, cartão) nem senha/código ditos no chat."""
    texto = _SENHA_DITA.sub(lambda m: m.group(1) + "[omitido]", str(texto or ""))
    return _NUMERO_LONGO.sub("[número omitido]", texto).strip()

def historico_da_conversa(lead):
    """Mensagens do cliente e respostas do agente, em ordem, da primeira até a que classificou o lead."""
    mensagens = []
    for evento in lead.events.order_by("created_at", "pk"):
        if evento.mensagem_cliente:
            mensagens.append({"quem": "cliente", "texto": evento.mensagem_cliente, "quando": evento.created_at})
        resultado = evento.result if isinstance(evento.result, dict) else {}
        if evento.marker == "LEMBRETE":
            for m in resultado.get("mensagens") or []:
                mensagens.append({"quem": "agente", "texto": m.get("content", ""), "quando": evento.created_at, "audio": False, "entregue": evento.delivery == "SENT"})
            continue
        if resultado.get("action") in ("TEXTO", "AUDIO") and (resultado.get("content") or "").strip():
            mensagens.append({
                "quem": "agente", "texto": resultado["content"], "quando": evento.created_at,
                "audio": resultado.get("action") == "AUDIO", "entregue": evento.delivery in ("SENT", "NOT_REQUIRED"),
            })
        if evento.marker == "CLASSIFICADO":
            break
    return mensagens

def apply_fields(lead, company, fields):
    """Grava os campos recebidos no lead; retorna uma mensagem de erro (str) se
    `especialidade` não for uma Area cadastrada para a empresa, ou None se ok.

    `especialidade` deixou de ser um choices fixo e global: agora é validada
    contra as áreas que a própria empresa cadastrou na tela "Equipe"
    (Area.objects.filter(company=...)). O agente nunca pode inventar uma área.

    `variaveis_roteiro` (opcional): dict slug->texto, só aceito pra slugs de
    Variáveis de roteiro CUSTOMIZADAS (não-builtin) já cadastradas pela empresa --
    nunca cria uma variável nova nem aceita um slug desconhecido/builtin (os
    builtin já são os campos fixos acima, nome/especialidade/tema).
    """
    especialidade = fields.get("especialidade")
    if especialidade and not _eh_fora_de_escopo(especialidade) and not company.areas.filter(name=especialidade).exists():
        return f"Área desconhecida: '{especialidade}' não está cadastrada em Equipe"
    for key, model_field in FIELD_MAP.items():
        if key in fields and fields[key]:
            setattr(lead, model_field, fields[key])
    if fields.get("observacoes"):
        lead.notes = mesclar_observacoes(lead.notes, fields["observacoes"])
    extra = fields.get("variaveis_roteiro")
    if extra:
        slugs_validos = set(company.variaveis_roteiro.filter(builtin=False).values_list("slug", flat=True))
        for slug, valor in extra.items():
            if slug in slugs_validos and isinstance(valor, str) and valor:
                lead.variaveis_roteiro[slug] = valor[:300]
    return None

def render_text(text, lead, company):
    """Substitui placeholders no texto aprovado pelos dados já coletados do lead e pela empresa.

    {empresa} vem de Company.name: o roteiro nunca precisa citar o nome da empresa
    na mão, e continua correto automaticamente se a empresa for renomeada ou se o
    mesmo texto for reaproveitado como modelo para uma empresa nova.
    {nome}, {especialidade}, {tema}... vêm dos dados já coletados do lead (usado
    sobretudo no texto aprovado de 'validar', que mostra um resumo para confirmação)
    -- são também as 3 Variáveis de roteiro builtin (Nome/Área da Lead/Demanda).
    Variáveis de roteiro customizadas usam o slug gerado na criação (ver
    slugify_variavel_roteiro) como placeholder, resolvido a partir de
    lead.variaveis_roteiro. Placeholder sem valor ainda vira string vazia, nunca
    quebra ou expõe '{campo}' literal.

    Todos os valores de substituição são resolvidos ANTES de rodar o regex, e a
    troca é feita em uma única passada sobre o texto original: um valor de campo
    (texto livre vindo do lead via o agente de IA) nunca é reprocessado como se
    fosse ele próprio um novo placeholder. Isso evita que um lead encadeie campos
    (ex.: nome="{tema}", tema="{impacto}", impacto="<texto arbitrário>") para fazer
    o backend reexpandir e enviar conteúdo que não é do roteiro aprovado da empresa.

    O regex de placeholders é montado por chamada (depende das Variáveis de roteiro
    customizadas desta empresa), não é um padrão fixo global.
    """
    values = {"empresa": company.name}
    for placeholder, model_field in FIELD_MAP.items():
        values[placeholder] = getattr(lead, model_field) or ""
    for slug in company.variaveis_roteiro.filter(builtin=False).values_list("slug", flat=True):
        values[slug] = (lead.variaveis_roteiro or {}).get(slug, "")

    def substitute(match):
        return values[match.group(1)]

    placeholder_re = re.compile(r"\{(" + "|".join(re.escape(k) for k in values.keys()) + r")\}")
    return placeholder_re.sub(substitute, text)

def _somar_contagem(company_id, dia, campo, quantidade=1):
    """Soma no contador diário da empresa (cria a linha do dia se preciso)."""
    contagem, _ = ContagemDiaria.objects.get_or_create(company_id=company_id, data=dia)
    ContagemDiaria.objects.filter(pk=contagem.pk).update(**{campo: F(campo) + quantidade})

def registrar_novo_lead(company):
    """Conta uma nova lead (criada pelo agente) no dia de hoje, que não se perde se o lead for apagado."""
    _somar_contagem(company.pk, timezone.localdate(), "novas")

def avaliar_contato(company, contact):
    """Única regra de "o agente pode atender este número agora?" -- usada por receive()
    (decide NO_REPLY) e por GET /agente/contato/ (a ponte consulta antes do modelo), pra
    as duas nunca divergirem. Sem efeitos colaterais.
    Devolve (lead_ou_None, aceita_agente, motivo)."""
    # O próprio número do agente (normalmente o mesmo em que a equipe atende) nunca é lead.
    if company.numero_agente and contact == company.numero_agente:
        return None, False, "proprio_numero"
    # BlackList: o número nunca entra no funil (sem lead, sem evento).
    if Blacklist.objects.filter(company=company, contact=contact).exists():
        return None, False, "blacklist"
    # Só um lead ATIVO (desfecho em aberto) prende o número; depois do despacho (ou de uma
    # desqualificação automática) ele fica livre e a próxima mensagem abre um lead novo do zero.
    lead = Lead.objects.filter(company=company, contact=contact, desfecho="").first()
    if not lead:
        return None, True, "sem_lead"
    if lead.mode == "HUMANO":
        return lead, False, "humano"
    # Classificado: o número fica com a equipe até o despacho registrar o desfecho.
    if lead.bot_closed or lead.state == "ENCERRADO_CLASSIFICADO":
        return lead, False, "classificado"
    return lead, True, "em_triagem"

def _spin_fora_da_area(company, lead, question_id):
    """Pergunta de uma lista {Área}-SPIN só vale para lead já classificado naquela área."""
    q = Question.objects.filter(company=company, question_id=question_id).select_related("area").first()
    if not q or not q.area_id:
        return False
    return (lead.especialidade or "") != q.area.name

def spins_iniciais_habilitadas(company):
    """Etapa Inicial: áreas cujas SPINs o cliente pode acessar (vazio sem Etapa Inicial)."""
    if not company.etapa_inicial:
        return []
    spins = list(company.spins_iniciais.order_by("name"))
    # Legado: empresa configurada só com spin_inicial (antes das várias SPINs) segue valendo.
    if not spins and company.spin_inicial_id:
        spins = [company.spin_inicial]
    return spins

def spin_efetiva(company, lead=None):
    """SPIN que vale para este lead na Etapa Inicial: a única habilitada ou, com várias, a que o
    agente escolheu pela mensagem inicial (lead.especialidade). None enquanto não foi escolhida."""
    spins = spins_iniciais_habilitadas(company)
    if len(spins) == 1:
        return spins[0]
    if lead is not None and lead.especialidade:
        return next((a for a in spins if a.name == lead.especialidade), None)
    return None

def perguntas_da_spin(company, area):
    if area is None:
        return []
    etapas = {"situacao": 0, "problema": 1, "implicacao": 2, "necessidade": 3, "": 4}
    perguntas = Question.objects.filter(company=company, area_id=area.pk).exclude(question_id__in=MANDATORY_OFFFLOW_QUESTION_IDS)
    return sorted((q for q in perguntas if q.text.strip()), key=lambda q: (etapas[q.etapa_spin], q.ordem, q.pk))

def perguntas_spin_inicial(company, lead=None):
    return perguntas_da_spin(company, spin_efetiva(company, lead))

def etapa_inicial_configurada(company):
    """Etapa Inicial com ao menos uma SPIN habilitada que tem perguntas com texto."""
    return any(perguntas_da_spin(company, a) for a in spins_iniciais_habilitadas(company))

def palavras_chave_da_area(area):
    """Palavras-chave da área (texto separado por vírgula, ponto e vírgula ou quebra de linha) como lista."""
    vistas, saida = set(), []
    for bruta in re.split(r"[,;\n]", area.palavras_chave or ""):
        palavra = re.sub(r"\s+", " ", bruta).strip()
        if palavra and palavra.casefold() not in vistas:
            vistas.add(palavra.casefold())
            saida.append(palavra[:60])
    return saida[:40]

def area_escolhida_na_etapa_inicial(company, fields):
    """Com várias SPINs: a área habilitada que o agente informou em fields.especialidade (ou None)."""
    nome = str((fields or {}).get("especialidade") or "").strip().casefold()
    return next((a for a in spins_iniciais_habilitadas(company) if a.name.casefold() == nome), None) if nome else None

def texto_fora_habilitado(company, question_id):
    if company.etapa_inicial:
        return False
    return not Question.objects.filter(company=company, question_id=question_id, habilitada=False).exists()

def pergunta_inicial(company, lead=None):
    if company.etapa_inicial:
        perguntas = perguntas_spin_inicial(company, lead)
        return perguntas[0].question_id if perguntas else None
    if company.initial_state in MANDATORY_OFFFLOW_QUESTION_IDS and not texto_fora_habilitado(company, company.initial_state):
        perguntas = Question.objects.filter(company=company, area__isnull=True).exclude(question_id__in=MANDATORY_OFFFLOW_QUESTION_IDS).order_by("ordem", "id")
        return next((q.question_id for q in perguntas if q.text.strip()), None)
    return company.initial_state

def pode_classificar_sem_validar(company, lead):
    if perguntas_obrigatorias_pendentes(company, lead):
        return False
    if dados_para_classificar(company, lead):
        return True
    if company.etapa_inicial:
        perguntas = perguntas_spin_inicial(company, lead)
    elif not texto_fora_habilitado(company, "validar"):
        perguntas = list(Question.objects.filter(company=company, area__name=lead.especialidade).exclude(question_id__in=MANDATORY_OFFFLOW_QUESTION_IDS).exclude(text="").order_by("ordem", "id"))
        if not perguntas:
            perguntas = list(Question.objects.filter(company=company, area__isnull=True).exclude(question_id__in=MANDATORY_OFFFLOW_QUESTION_IDS).exclude(text="").order_by("ordem", "id"))
    else:
        return False
    return bool(perguntas and lead.state == perguntas[-1].question_id)

def dados_para_classificar(company, lead, fields=None):
    fields = fields or {}
    nome = fields.get("nome") or lead.name or lead.contact_name
    demanda = fields.get("tema") or lead.demand
    area = fields.get("especialidade") or lead.especialidade
    return bool(str(nome).strip() and str(demanda).strip() and area and company.areas.filter(name=area).exists() and not _eh_fora_de_escopo(area))

def perguntas_obrigatorias_pendentes(company, lead=None, fields=None):
    fields = fields or {}
    if company.etapa_inicial:
        perguntas = perguntas_spin_inicial(company, lead)
    else:
        area = fields.get("especialidade") or (lead.especialidade if lead else "")
        perguntas = Question.objects.filter(company=company, area__name=area).order_by("ordem", "id") if area else []
    enviadas = {result.get("question_id") for result in lead.events.filter(delivery="SENT").values_list("result", flat=True)} if lead else set()
    return [q for q in perguntas if q.envio_obrigatorio and q.question_id not in enviadas]

def guardar_notas_coletadas(company, lead, fields):
    notas = fields.get("notas") or {}
    if not notas:
        return
    perguntas = Question.objects.filter(company=company, variavel__isnull=False).exclude(variavel_roteiro__slug="nome")
    if company.etapa_inicial:
        spin = spin_efetiva(company, lead)
        perguntas = perguntas.filter(area_id=spin.pk if spin else None)
    else:
        area = fields.get("especialidade") or lead.especialidade
        perguntas = perguntas.filter(Q(area__isnull=True) | Q(area__name=area))
    ids = set(perguntas.values_list("question_id", flat=True))
    anteriores = (lead.urgencia_detalhe or {}).get("notas", {})
    lead.urgencia_detalhe = {"notas": {qid: nota for qid, nota in {**anteriores, **notas}.items() if qid in ids}}

def estado_spin_para_retomar(company, lead):
    ids = [q.question_id for q in perguntas_spin_inicial(company, lead)]
    if lead.state in ids:
        return lead.state
    for result in lead.events.filter(delivery__in=["SENT", "EXPIRADO"]).order_by("-created_at", "-pk").values_list("result", flat=True):
        if result.get("question_id") in ids:
            return result["question_id"]
    return ids[0] if ids else ""

MAX_REPETICOES = 3
# Conversa livre (marcador RESPONDER): só antes do fluxo e com teto de respostas por lead.
ESTADOS_PRE_FLUXO = ("apresentacao", "empresa")
MAX_RESPOSTAS_LIVRES = 6
LIMITE_TEXTO_LIVRE = 1000

def conversa_livre_ativa(company):
    return bool(company.agente_conversacional and not company.etapa_inicial)

def respostas_livres_enviadas(lead):
    return Event.objects.filter(lead=lead, marker="RESPONDER", result__action__in=["TEXTO", "AUDIO"]).count()

def conversa_livre_restante(company, lead):
    """Quantas respostas livres o agente ainda pode dar a este lead (0 = indisponível)."""
    if not lead or lead.desfecho or lead.bot_closed or lead.pedido_humano_pendente or not conversa_livre_ativa(company):
        return 0
    if lead.state not in ESTADOS_PRE_FLUXO or not texto_fora_habilitado(company, "apresentacao"):
        return 0
    return max(0, MAX_RESPOSTAS_LIVRES - respostas_livres_enviadas(lead))
REPEAT_PREFIX = "Por favor, responda novamente. "
JANELA_ENTREGA_PENDENTE = timedelta(seconds=90)

def variaveis_humano_pendentes(company, lead):
    question = Question.objects.filter(company=company, question_id="necessidade_humana").first()
    if not question:
        return []
    missing = []
    for variable in question.variaveis_obrigatorias.all():
        if variable.builtin:
            model_field = FIELD_MAP.get(variable.slug)
            value = getattr(lead, model_field, "") if model_field else ""
        else:
            value = (lead.variaveis_roteiro or {}).get(variable.slug, "")
        if not str(value or "").strip():
            missing.append(variable)
    return missing

def mensagem_necessidade_humana(company, lead, event, question=None):
    if question is None:
        question = Question.objects.filter(company=company, question_id="necessidade_humana").first()
    if not question or not question.text.strip():
        return dict(NO_REPLY)
    if question.question_id in MANDATORY_OFFFLOW_QUESTION_IDS and not texto_fora_habilitado(company, question.question_id):
        return dict(NO_REPLY)
    if company.etapa_inicial and question.area_id != getattr(spin_efetiva(company, lead), "pk", None):
        return dict(NO_REPLY)
    content = render_text(question.text, lead, company)
    anterior = Event.objects.filter(lead=lead, delivery__in=["SENT", "PENDING", "EXPIRADO"]).exclude(pk=event.pk).order_by("-created_at", "-pk").first()
    if anterior and anterior.result.get("question_id") == question.question_id and anterior.result.get("content", "").removeprefix(REPEAT_PREFIX) == content:
        if not company.etapa_inicial:
            content = REPEAT_PREFIX + content
        event.marker = "REPETIR"
    event.delivery = "PENDING"
    return {"action": "TEXTO", "content": content, "question_id": question.question_id}

def processar_pedido_humano(company, lead, event, fields):
    was_pending = lead.pedido_humano_pendente
    collected = {key: value for key, value in fields.items() if key in {
        "nome", "especialidade", "tema", "impacto", "interesse", "variaveis_roteiro",
    }}
    field_error = apply_fields(lead, company, collected)
    missing = variaveis_humano_pendentes(company, lead)
    if not missing:
        lead.pedido_humano_pendente = False
        escalate(lead, "pedido humano")
        event.summary = "Encaminhado para atendimento humano: pedido humano"
        # A mensagem que solicita os dados já foi enviada antes da coleta.
        return dict(NO_REPLY) if was_pending else mensagem_necessidade_humana(company, lead, event)

    lead.pedido_humano_pendente = True
    lead.next_action = ("Coletar dados antes do atendimento humano: " + ", ".join(v.name for v in missing))[:250]
    event.summary = "Pedido humano aguardando dados: " + ", ".join(v.slug for v in missing)
    if field_error:
        event.summary += "; " + field_error
    question = None
    if was_pending or not texto_fora_habilitado(company, "necessidade_humana"):
        # Depois da mensagem fora do fluxo, pede apenas o próximo dado faltante.
        perguntas = Question.objects.filter(company=company, variavel_roteiro=missing[0]).filter(
            Q(area__isnull=True) | Q(area__name=lead.especialidade)
        ).exclude(question_id__in=MANDATORY_OFFFLOW_QUESTION_IDS).exclude(text="")
        if company.etapa_inicial:
            perguntas = perguntas.filter(area_id=getattr(spin_efetiva(company, lead), "pk", None))
        question = perguntas.order_by("ordem", "id").first()
    lead.state = question.question_id if question else "necessidade_humana"
    lead.save()
    return mensagem_necessidade_humana(company, lead, event, question)

def contar_repeticoes(lead, excluir_pk=None):
    """REPETIR consecutivos desde o último marcador que não foi REPETIR."""
    if lead is None:
        return 0
    qs = Event.objects.filter(lead=lead).exclude(marker="").order_by("-created_at", "-pk")
    if excluir_pk:
        qs = qs.exclude(pk=excluir_pk)
    total = 0
    for marker in qs.values_list("marker", flat=True):
        if marker != "REPETIR":
            break
        total += 1
    return total

def ultima_pergunta(lead):
    """question_id da etapa em que o lead está (ou da última pergunta enviada a ele)."""
    if lead.state and Question.objects.filter(company_id=lead.company_id, question_id=lead.state).exists():
        return lead.state
    for result in Event.objects.filter(lead=lead).order_by("-created_at", "-pk").values_list("result", flat=True):
        if isinstance(result, dict) and result.get("action") in ("TEXTO", "AUDIO") and result.get("question_id"):
            return result["question_id"]
    return None

def status_contato(company, contact):
    lead, aceita, motivo = avaliar_contato(company, contact)
    return {
        "contact": contact,
        "lead_id": str(lead.pk) if lead else None,
        "aceita_agente": aceita,
        "motivo": motivo,
        "ultima_pergunta": (estado_spin_para_retomar(company, lead) if company.etapa_inicial and lead.pedido_humano_pendente else ultima_pergunta(lead)) if lead and motivo == "em_triagem" else None,
        "repeticoes": contar_repeticoes(lead) if lead and motivo == "em_triagem" else 0,
        # Área já classificada no lead ativo: define qual lista SPIN o agente segue.
        "especialidade": (lead.especialidade or "") if lead and not lead.desfecho else "",
        "pergunta_inicial": pergunta_inicial(company, lead),
        "conversa_livre_restante": conversa_livre_restante(company, lead) if lead and aceita and motivo == "em_triagem" else 0,
        "campos": {key: (lead.name or lead.contact_name) if key == "nome" else getattr(lead, model_field) for key, model_field in FIELD_MAP.items()} if lead and aceita else {},
        "variaveis_roteiro": (lead.variaveis_roteiro or {}) if lead and aceita else {},
        "observacoes": (lead.notes or "") if lead and aceita else "",
        "pode_classificar": bool(lead and aceita and dados_para_classificar(company, lead) and not perguntas_obrigatorias_pendentes(company, lead)),
        "perguntas_obrigatorias_pendentes": [q.question_id for q in perguntas_obrigatorias_pendentes(company, lead)] if aceita else [],
        "notas_urgencia": (lead.urgencia_detalhe or {}).get("notas", {}) if lead and aceita else {},
        "atendimento_humano_habilitado": not company.etapa_inicial,
        "pedido_humano_pendente": bool(lead and aceita and lead.pedido_humano_pendente and not company.etapa_inicial),
        "variaveis_humano_pendentes": [v.slug for v in variaveis_humano_pendentes(company, lead)] if lead and aceita and lead.pedido_humano_pendente and not company.etapa_inicial else [],
    }

@transaction.atomic
def receive(company, data):
    # Serialize per company: protege a criação do primeiro contato e mensagens concorrentes.
    company = Company.objects.select_for_update().get(pk=company.pk)
    lead, aceita, motivo = avaliar_contato(company, data["contact"])
    if motivo == "proprio_numero":
        # Mensagem do número do agente pra ele mesmo não cria lead nem evento.
        return {**NO_REPLY, "proprio_numero": True}
    if motivo == "blacklist":
        return {**NO_REPLY, "blacklist": True}
    lead_novo = lead is None
    if lead_novo:
        # O lock da empresa acima garante que nunca nascem dois leads ativos pro mesmo contato.
        # Com várias SPINs habilitadas o lead nasce sem área: o agente a escolhe pela mensagem inicial.
        spin_unica = spin_efetiva(company)
        lead = Lead.objects.create(company=company, contact=data["contact"], state=pergunta_inicial(company) or "", especialidade=spin_unica.name if spin_unica else "")
        registrar_novo_lead(company)
    previous = Event.objects.filter(lead=lead, message_id=data["message_id"]).first()
    if previous:
        return {**NO_REPLY, "duplicate": True, "lead_id": str(lead.pk), "lead_novo": False}
    if aceita and data.get("contact_name"):
        lead.contact_name = data["contact_name"]
    if aceita and company.etapa_inicial:
        if lead.pedido_humano_pendente:
            lead.state = estado_spin_para_retomar(company, lead)
            lead.pedido_humano_pendente = False
            lead.next_action = ""
        if data["human_required"] and data["reason"] in {"pedido humano", "urgência ou risco", "decisão profissional"}:
            # O pedido não cria uma coleta paralela nem substitui a demanda.
            fields = data.get("fields") or {}
            data = {**data, "human_required": False, "marker": "ATUALIZAR", "fields": {**fields, "proxima": fields.get("proxima") or estado_spin_para_retomar(company, lead)}}
    lead.last_contact = timezone.now()
    lead.save()
    event = Event.objects.create(
        lead=lead, message_id=data["message_id"], marker=data["marker"],
        summary=f"Marcador recebido: {data['marker']}",
        mensagem_cliente=redigir_dados_sensiveis(data.get("mensagem"))[:4000] if company.coletar_historico_conversa else "",
    )
    result = dict(NO_REPLY)
    # Triagem que não pode continuar (travada ou erro do agente) nunca vai pra equipe:
    # o lead é apagado e o número recomeça do zero na próxima mensagem.
    apagar_lead, motivo_apagar = False, ""
    pendentes = Event.objects.filter(lead=lead, delivery="PENDING").exclude(pk=event.pk)
    # Etapa Inicial com várias SPINs: enquanto a área não foi escolhida, o agente a informa em
    # fields.especialidade (ou sinaliza fora de escopo, que desqualifica).
    area_indefinida = False
    if aceita and company.etapa_inicial and len(spins_iniciais_habilitadas(company)) > 1 and spin_efetiva(company, lead) is None:
        escolhida = area_escolhida_na_etapa_inicial(company, data.get("fields"))
        if escolhida:
            lead.especialidade = escolhida.name
        else:
            area_indefinida = True

    if not aceita:
        pass
    elif company.etapa_inicial and not etapa_inicial_configurada(company):
        escalate(lead, "Configurar SPIN inicial com perguntas no Roteiro")
        event.summary = "SPIN inicial sem perguntas disponíveis"
    elif data["human_required"] and data["reason"] == "fora de escopo":
        desqualificar_fora_de_escopo(lead)
    elif (data.get("fields") or {}).get("situacao_especial") in SITUACOES_ESPECIAIS and data["marker"] == "ATUALIZAR":
        # Só chega aqui lead em triagem (aceita): quem já foi classificado/atendido não muda de categoria.
        result = marcar_situacao_especial(company, lead, event, data["fields"]["situacao_especial"], data["fields"])
    elif data["human_required"] and data["reason"] == "falha de integração":
        apagar_lead, motivo_apagar = True, "Agente sinalizou falha de integração"
    elif data["human_required"] and data["reason"] != "pedido humano":
        escalate(lead, data["reason"])
        event.summary = f"Encaminhado para atendimento humano: {data['reason']}"
    elif lead.pedido_humano_pendente or data["human_required"]:
        result = processar_pedido_humano(company, lead, event, data.get("fields") or {})
    elif area_indefinida:
        # Sem área válida entre as SPINs habilitadas não há pergunta a enviar: o agente deve informar a
        # especialidade (ATUALIZAR) ou sinalizar fora de escopo. A mensagem seguinte tenta de novo.
        event.summary = "Etapa Inicial: área não definida pelo agente (informe a especialidade ou fora de escopo)"
    elif pendentes.filter(created_at__gte=timezone.now() - JANELA_ENTREGA_PENDENTE).exists():
        # Contato mandou várias mensagens em sequência enquanto a resposta anterior ainda
        # está saindo: ignora esta sem escalar (escalar aqui travava o lead em HUMANO).
        event.summary = "Mensagem em sequência: entrega anterior ainda pendente"
    else:
        # Pendência antiga (90s+): a confirmação se perdeu; não deixa ela travar a triagem.
        pendentes.update(delivery="EXPIRADO")
        marker = data["marker"]
        fields = data.get("fields") or {}
        estado_anterior = lead.state
        inicial = pergunta_inicial(company, lead)
        if company.etapa_inicial:
            spin_do_lead = spin_efetiva(company, lead)
            fields = {**fields, "especialidade": spin_do_lead.name if spin_do_lead else ""}
            field_error = apply_fields(lead, company, fields)
            if field_error:
                event.summary = field_error
        pronto = dados_para_classificar(company, lead, fields)
        obrigatorias_pendentes = perguntas_obrigatorias_pendentes(company, lead, fields)
        pula_obrigatoria = False
        if obrigatorias_pendentes and marker in {"Q", "ATUALIZAR"}:
            alvo = data.get("question_id") if marker == "Q" else fields.get("proxima")
            perguntas_area = perguntas_spin_inicial(company, lead) if company.etapa_inicial else Question.objects.filter(company=company, area_id=obrigatorias_pendentes[0].area_id).order_by("ordem", "id")
            ids_area = [q.question_id for q in perguntas_area]
            pula_obrigatoria = alvo in ids_area and ids_area.index(alvo) > ids_area.index(obrigatorias_pendentes[0].question_id)
        if obrigatorias_pendentes and not fields.get("encerramento_antecipado") and (marker in {"CLASSIFICADO", "VALIDAR"} or pula_obrigatoria or (pronto and marker == "ATUALIZAR")):
            apply_fields(lead, company, fields)
            guardar_notas_coletadas(company, lead, fields)
            marker = "Q"
            event.marker = marker
            data = {**data, "question_id": obrigatorias_pendentes[0].question_id}
            if pronto:
                inicial = obrigatorias_pendentes[0].question_id
            event.summary = "Enviando pergunta obrigatória antes de classificar"
        elif marker in {"ATUALIZAR", "VALIDAR"} and pronto and fields.get("notas"):
            marker = "CLASSIFICADO"
            event.marker = marker
            event.summary = "Classificação antecipada: nome, demanda e área preenchidos"
        if lead_novo and not (marker == "Q" and data["question_id"] == inicial) and not (marker == "CLASSIFICADO" and pronto and not obrigatorias_pendentes):
            # Lead novo sempre começa pela etapa inicial configurada, mesmo que o agente (ex.: sessão antiga
            # que "lembra" de uma triagem já apagada) mande outro marcador.
            event.summary = f"Lead novo: começando por {inicial} (marcador {marker} ignorado)"
            marker, fields = "Q", fields if company.etapa_inicial else {}
            event.marker = "Q"
            data = {**data, "question_id": inicial or ""}
        if marker in {"ATUALIZAR", "VALIDAR", "CLASSIFICADO"} and _eh_fora_de_escopo(fields.get("especialidade") or lead.especialidade):
            # Fora de escopo não precisa concluir nem validar o roteiro e nunca recebe
            # a urgência comercial enviada pelo agente.
            apply_fields(lead, company, fields)
            desqualificar_fora_de_escopo(lead)
            question_id = None
        elif company.etapa_inicial and marker in {"Q", "ATUALIZAR"} and (data.get("question_id") if marker == "Q" else fields.get("proxima")) not in {q.question_id for q in perguntas_spin_inicial(company, lead)}:
            event.summary = "Pergunta bloqueada: somente a SPIN inicial selecionada é permitida"
            question_id = None
        elif marker == "Q":
            question_id = data["question_id"]
            if question_id == "necessidade_humana":
                event.summary = "Necessidade humana só é enviada ao identificar pedido humano"
                question_id = None
            elif not question_id:
                apagar_lead, motivo_apagar = True, "Marcador Q sem question_id: revisar integração do agente"
                question_id = None
            elif _spin_fora_da_area(company, lead, question_id):
                apagar_lead, motivo_apagar = True, "Pergunta SPIN de área diferente da classificada"
                question_id = None
            else:
                lead.state = question_id
        elif marker == "RESPONDER":
            texto = re.sub(r"[ \t]+", " ", str(fields.get("texto") or "")).strip()
            question_id = None
            if lead.state not in ESTADOS_PRE_FLUXO or not conversa_livre_ativa(company) or lead.bot_closed:
                # Fora da janela anterior ao fluxo (ou empresa sem o modo): nunca envia.
                event.summary = "Resposta livre bloqueada: só vale antes do fluxo, com Agente conversacional ligado"
            elif not texto or len(texto) > LIMITE_TEXTO_LIVRE or "[[AXIOMA" in texto:
                event.summary = "Resposta livre inválida (vazia, longa demais ou com marcador)"
            elif conversa_livre_restante(company, lead) <= 0:
                # Teto atingido: reenvia o convite aprovado em vez de conversar sem fim.
                question_id = lead.state
                event.summary = "Limite de respostas livres atingido; reenviando o texto aprovado"
            else:
                result = {"action": "TEXTO", "content": texto, "question_id": "conversa"}
                event.delivery = "PENDING"
                event.summary = "Resposta livre antes do fluxo"
        elif marker == "REPETIR":
            if contar_repeticoes(lead, excluir_pk=event.pk) >= MAX_REPETICOES:
                # A mesma pergunta foi repetida 3 vezes sem resposta utilizável (o contador zera
                # a cada pergunta nova): desqualifica e libera o número, sem ir pra equipe.
                desqualificar_sem_resposta(lead)
                event.summary = "Desqualificado: 3 repetições da mesma pergunta sem resposta"
                question_id = None
            else:
                # Na validação o estado é "VALIDANDO", mas a pergunta reenviada é "validar".
                question_id = "validar" if lead.state == "VALIDANDO" else lead.state
                event.summary = "Entrada ambígua ou fora do roteiro; repetindo pergunta atual"
        elif marker == "ATUALIZAR":
            field_error = apply_fields(lead, company, fields)
            if field_error:
                apagar_lead, motivo_apagar = True, field_error
                question_id = None
            elif _eh_fora_de_escopo(lead.especialidade):
                desqualificar_fora_de_escopo(lead)
                question_id = None
            else:
                question_id = fields.get("proxima", "")
                if not question_id:
                    apagar_lead, motivo_apagar = True, "ATUALIZAR sem 'proxima': configurar roteiro aprovado"
                    question_id = None
                elif question_id in RESERVED_QUESTION_IDS:
                    apagar_lead, motivo_apagar = True, f"'{question_id}' é reservado e não é uma 'proxima' válida: revisar fluxo do agente"
                    question_id = None
                elif _spin_fora_da_area(company, lead, question_id):
                    # apply_fields já rodou: uma especialidade enviada neste mesmo ATUALIZAR vale.
                    apagar_lead, motivo_apagar = True, "Pergunta SPIN de área diferente da classificada"
                    question_id = None
                elif question_id == lead.state:
                    # Avançar para a mesma pergunta é uma repetição disfarçada: conta no mesmo limite.
                    event.marker = "REPETIR"
                    if contar_repeticoes(lead, excluir_pk=event.pk) >= MAX_REPETICOES:
                        desqualificar_sem_resposta(lead)
                        event.summary = "Desqualificado: 3 repetições da mesma pergunta sem resposta"
                        question_id = None
                    else:
                        event.summary = "Mesma pergunta pedida de novo; contada como repetição"
                else:
                    lead.state = question_id
                    lead.funnel_stage = "Triagem"
        elif marker == "VALIDAR":
            field_error = apply_fields(lead, company, fields)
            if field_error:
                apagar_lead, motivo_apagar = True, field_error
                question_id = None
            else:
                question_id = None if company.etapa_inicial else "validar"
                if not company.etapa_inicial:
                    lead.state = "VALIDANDO"
        elif marker == "CLASSIFICADO":
            antecipado = bool(fields.get("encerramento_antecipado"))
            if antecipado:
                apagar_lead, motivo_apagar = True, "Triagem abandonada antes de concluir o roteiro"
                question_id = None
            elif company.etapa_inicial and not pronto and not pode_classificar_sem_validar(company, lead):
                event.summary = "Classificação aguardando nome, demanda e área ou a última pergunta da SPIN"
                question_id = None
            elif lead.state != "VALIDANDO" and not pronto and not pode_classificar_sem_validar(company, lead):
                apagar_lead, motivo_apagar = True, "CLASSIFICADO recebido sem VALIDAR anterior: revisar fluxo do agente"
                question_id = None
            else:
                fields, field_error = _aplicar_notas_urgencia(lead, company, fields)
                if not field_error:
                    field_error = apply_fields(lead, company, fields)
                if field_error:
                    apagar_lead, motivo_apagar = True, field_error
                    question_id = None
                else:
                    if not lead.name.strip() and lead.temperature not in FORA_DO_KANBAN:
                        lead.name = lead.contact_name
                    lead.bot_closed = True
                    lead.state = "ENCERRADO_CLASSIFICADO"
                    lead.funnel_stage = "Triagem concluída"
                    lead.next_action = "Revisar classificação e dar continuidade humana"
                    question_id = "encerramento" if texto_fora_habilitado(company, "encerramento") else None
                    event.summary = "Lead classificada: " + lead.temperature
                    if lead.temperature in FORA_DO_KANBAN:
                        # Nunca entra no Kanban humano, então nunca seria despachado: fecha
                        # aqui, senão o número ficaria preso como "lead ativo" pra sempre.
                        lead.desfecho = "desqualificado"
                        lead.concluido_em = timezone.now()
                        lead.next_action = ""
        else:
            apagar_lead, motivo_apagar = True, f"Marcador desconhecido: {marker}"
            question_id = None

        if question_id:
            question = Question.objects.filter(company=company, question_id=question_id).first()
            spin_ids = [q.question_id for q in perguntas_spin_inicial(company, lead)] if company.etapa_inicial else []
            bloqueada = (question_id in MANDATORY_OFFFLOW_QUESTION_IDS and not texto_fora_habilitado(company, question_id)) or (company.etapa_inicial and question_id not in spin_ids)
            obrigatoria_antecipada = obrigatorias_pendentes and question_id == obrigatorias_pendentes[0].question_id
            fora_de_ordem = company.etapa_inicial and not obrigatoria_antecipada and question_id in spin_ids and estado_anterior in spin_ids and spin_ids.index(question_id) not in {spin_ids.index(estado_anterior), spin_ids.index(estado_anterior) + 1}
            if bloqueada or fora_de_ordem:
                if not lead.bot_closed:
                    lead.state = estado_anterior
                event.summary = "Envio bloqueado pelas opções do agente"
            elif not question:
                # Erro de configuração da empresa (não do agente): fica visível pra empresa corrigir.
                escalate(lead, f"Configurar roteiro aprovado para question_id={question_id}")
            else:
                # Áudio (gravação/TTS) é aplicado depois, fora da transação: ver aplicar_audio().
                asset = render_text(question.text, lead, company)
                if not asset:
                    escalate(lead, "Configurar texto aprovado (vazio) no Roteiro")
                else:
                    anterior = Event.objects.filter(lead=lead, delivery__in=["SENT", "PENDING", "EXPIRADO"]).exclude(pk=event.pk).order_by("-created_at", "-pk").first()
                    mesma_mensagem = anterior and anterior.result.get("question_id") == question_id and anterior.result.get("content", "").removeprefix(REPEAT_PREFIX) == asset
                    if not company.etapa_inicial and (event.marker == "REPETIR" or mesma_mensagem):
                        asset = REPEAT_PREFIX + asset
                    result = {"action": "TEXTO", "content": asset, "question_id": question_id}
                    event.delivery = "PENDING"
        lead.save()

    if apagar_lead:
        logger.warning("Lead %s (%s) apagado e triagem reiniciada: %s", lead.pk, company.name, motivo_apagar)
        lead_id = str(lead.pk)
        lead.delete()  # eventos vão junto (CASCADE)
        return {**NO_REPLY, "lead_id": lead_id, "lead_apagado": True, "lead_novo": False}

    result.update({"lead_id": str(lead.pk), "event_id": event.pk, "lead_novo": lead_novo})
    event.result = result
    event.save()
    return result

def aplicar_audio(company, result, url_absoluta):
    """'Mensagens via áudio': troca uma resposta TEXTO por AUDIO (gravação da pergunta ou TTS).

    Roda depois do receive(), fora da transação (o TTS pode levar segundos e não deve segurar
    o lock da empresa). Qualquer falha mantém o TEXTO -- nunca vira NO_REPLY por causa do
    áudio. url_absoluta(caminho_media) monta a URL na mesma origem da requisição.
    """
    from . import audio
    company.refresh_from_db(fields=["allow_transcription", "mensagens_audio", "voz_tts"])
    if result.get("action") != "TEXTO" or not company.audio_ativo:
        return result
    question = Question.objects.filter(company=company, question_id=result.get("question_id")).first()
    try:
        # A gravação fixa não contém o prefixo de repetição nem os valores dos placeholders.
        # Nesses casos o TTS deve falar o conteúdo efetivamente renderizado pelo CRM.
        repetida = result["content"].startswith(REPEAT_PREFIX)
        personalizada_humana = question and question.question_id == "necessidade_humana" and bool(re.search(r"\{[a-zA-Z_][a-zA-Z_0-9]*\}", question.text))
        if question and question.audio_gravado and not repetida and not personalizada_humana:
            caminho, origem = question.audio_gravado.name, "gravado"
        else:
            caminho, origem = audio.gerar_tts(result["content"], company.voz_tts), "tts"
    except Exception as exc:  # TTS/ffmpeg/rede: segue em texto
        logger.warning("audio: falha ao gerar áudio (event_id=%s): %s", result.get("event_id"), exc)
        novo = {**result, "audio_erro": str(exc)[:200] or exc.__class__.__name__}
    else:
        novo = {**result, "action": "AUDIO", "audio_url": url_absoluta(settings.MEDIA_URL + caminho), "audio_origem": origem}
    if result.get("event_id"):
        Event.objects.filter(pk=result["event_id"]).update(result=novo)
    return novo

INVITE_TTL = timedelta(minutes=15)
MAX_INVITE_ATTEMPTS = 5

def create_invite(company, name, email):
    """Cria o convite, gera o código de 6 dígitos e dispara o e-mail com código + link.

    O código em si nunca é persistido em texto puro (code_hash via make_password,
    o mesmo hasher usado para senha) nem retornado pela API -- só vai no e-mail.
    """
    User = get_user_model()
    if User.objects.filter(Q(username__iexact=email) | Q(email__iexact=email)).exists():
        raise ValueError("Já existe uma conta com este e-mail.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    invite = AtendenteInvite.objects.create(
        company=company, name=name, email=email,
        code_hash=make_password(code), expires_at=timezone.now() + INVITE_TTL,
    )
    send_invite_email(invite, code)
    return invite

@transaction.atomic
def validar_convite(invite_id, code):
    """Confere o código do convite e, se válido, cria a conta do atendente.

    Tudo protegido por select_for_update: duas tentativas concorrentes para o
    mesmo convite nunca criam duas contas nem passam ambas com o mesmo código.

    O link/código é de uso único: ao validar com sucesso, o convite é excluído
    na hora (não só marcado como verificado) -- ele nunca mais existe pra ser
    reaproveitado, nem guarda o code_hash depois de cumprir sua função.
    """
    invite = AtendenteInvite.objects.select_for_update().filter(pk=invite_id).first()
    if not invite:
        return {"ok": False, "detail": "Link inválido, expirado ou já utilizado."}
    if invite.expires_at < timezone.now():
        return {"ok": False, "detail": "Código expirado. Peça um novo convite à empresa."}
    if invite.attempts >= MAX_INVITE_ATTEMPTS:
        return {"ok": False, "detail": "Número de tentativas excedido. Peça um novo convite à empresa."}
    invite.attempts += 1
    if not check_password(code, invite.code_hash):
        invite.save(update_fields=["attempts"])
        return {"ok": False, "detail": "Código incorreto."}
    User = get_user_model()
    if User.objects.filter(username=invite.email).exists():
        invite.save(update_fields=["attempts"])
        return {"ok": False, "detail": "Já existe uma conta com este e-mail."}
    provisional_password = secrets.token_urlsafe(9)
    user = User.objects.create_user(username=invite.email, email=invite.email, password=provisional_password, first_name=invite.name[:150])
    invite.company.members.add(user)
    PasswordChangeRequired.objects.create(user=user)
    send_credentials_email(invite.email, invite.name, provisional_password)
    invite.delete()
    return {"ok": True, "detail": "Conta criada. As credenciais de acesso foram enviadas para o seu e-mail."}

def trocar_senha(user, current_password, new_password):
    """Exige a senha atual mesmo quando a troca é obrigatória (senha provisória
    recém-recebida por e-mail): uma sessão aberta sem saber a senha atual nunca
    deveria conseguir travar a conta sozinha trocando a senha por outra."""
    if not user.check_password(current_password):
        return "Senha atual incorreta."
    user.set_password(new_password)
    user.save()
    PasswordChangeRequired.objects.filter(user=user).delete()
    return None

EMAIL_CHANGE_TTL = timedelta(minutes=15)
MAX_EMAIL_CHANGE_ATTEMPTS = 5

def solicitar_troca_email(user, new_email):
    User = get_user_model()
    if User.objects.filter(Q(email__iexact=new_email) | Q(username__iexact=new_email)).exclude(pk=user.pk).exists():
        raise ValueError("Já existe uma conta usando este e-mail.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    request = EmailChangeRequest.objects.create(
        user=user, new_email=new_email,
        code_hash=make_password(code), expires_at=timezone.now() + EMAIL_CHANGE_TTL,
    )
    send_email_change_code(new_email, code)
    return request

@transaction.atomic
def confirmar_troca_email(user, code):
    request = (
        EmailChangeRequest.objects.select_for_update()
        .filter(user=user, confirmed_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if not request:
        return {"ok": False, "detail": "Nenhuma troca de e-mail pendente. Peça o código novamente."}
    if request.expires_at < timezone.now():
        return {"ok": False, "detail": "Código expirado. Peça um novo código."}
    if request.attempts >= MAX_EMAIL_CHANGE_ATTEMPTS:
        return {"ok": False, "detail": "Número de tentativas excedido. Peça um novo código."}
    request.attempts += 1
    if not check_password(code, request.code_hash):
        request.save(update_fields=["attempts"])
        return {"ok": False, "detail": "Código incorreto."}
    User = get_user_model()
    if User.objects.filter(Q(email__iexact=request.new_email) | Q(username__iexact=request.new_email)).exclude(pk=user.pk).exists():
        request.save(update_fields=["attempts"])
        return {"ok": False, "detail": "Já existe uma conta usando este e-mail."}
    # O login é pelo username, que nas contas criadas por convite é o próprio e-mail:
    # sem atualizar os dois juntos, a pessoa trocava o e-mail e não conseguia entrar com ele.
    campos = ["email"]
    if "@" in (user.username or ""):
        user.username = request.new_email
        campos.append("username")
    user.email = request.new_email
    user.save(update_fields=campos)
    request.confirmed_at = timezone.now()
    request.save(update_fields=["attempts", "confirmed_at"])
    return {"ok": True, "detail": "E-mail atualizado."}

def redefinir_senha_atendente(atendente):
    """A empresa força uma senha nova para um atendente da própria equipe,
    enviada por e-mail. Mesma regra de segurança do convite: o atendente é
    obrigado a trocar essa senha no próximo login (PasswordChangeRequired)."""
    nova_senha = secrets.token_urlsafe(9)
    atendente.set_password(nova_senha)
    atendente.save()
    PasswordChangeRequired.objects.get_or_create(user=atendente)
    profile = getattr(atendente, "profile", None)
    nome = (profile.display_name if profile else "") or atendente.first_name or atendente.username
    send_password_reset_by_admin_email(atendente.email or atendente.username, nome, nova_senha)

# --- Painel Admin interno (Axioma): conta de serviço do agente por empresa ---
# Convenção de username já documentada em docs/integracao-agente.md
# (agente.<slug-da-empresa>) -- mantida aqui pra não divergir do que já está
# em produção (ex.: agente.rufus-advocacia, criado antes desta tela existir).

def _agent_username(company):
    return f"agente.{slugify(company.name)}"

def conta_agente_principal(company):
    """Conta de serviço do agente desta empresa -> (usuário ou None, vinculada?).

    Procura primeiro entre os MEMBROS da empresa que estão no grupo "agente" (assim renomear a
    empresa não "perde" a conta nem cria uma segunda). Sem membro, cai no username padrão
    agente.<slug> -- só se essa conta não pertencer a nenhuma outra empresa (uma conta de agente
    nunca pode ser compartilhada entre empresas); nesse caso ela existe mas está DESVINCULADA, e
    o agente dela recebe 404 do CRM até ser religada."""
    User = get_user_model()
    username = _agent_username(company)
    membros = list(company.members.filter(groups__name="agente").order_by("pk"))
    for u in membros:
        if u.username == username:
            return u, True
    if membros:
        return membros[0], True
    u = User.objects.filter(username=username).first()
    if u and u.groups.filter(name="agente").exists() and not u.companies.exists():
        return u, False
    return None, False

def _status_conta_agente(user, vinculada):
    token = Token.objects.filter(user=user).first()
    masked, validade = None, None
    if token:
        masked = f"{token.key[:8]}…{token.key[-4:]}"
        expiry = getattr(token, "expiry", None)
        if expiry:
            validade = {"expires_at": expiry.expires_at, "expirado": expiry.expires_at < timezone.now()}
    return {"existe": True, "id": user.pk, "username": user.username, "vinculada": vinculada,
            "ativa": user.is_active, "masked_key": masked, "validade": validade}

def agent_status(company):
    """Estado atual da conta e do token do agente desta empresa, pra tela Admin e pro
    serializer (nunca devolve a chave inteira, só uma prévia mascarada)."""
    user, vinculada = conta_agente_principal(company)
    if not user:
        return {"existe": False, "id": None, "username": _agent_username(company), "vinculada": False,
                "ativa": False, "masked_key": None, "validade": None}
    return _status_conta_agente(user, vinculada)

def _garantir_conta_agente(company):
    """Cria (se faltar), reativa e liga à empresa a conta de serviço do agente, SEM mexer na chave."""
    User = get_user_model()
    agent_group, _ = Group.objects.get_or_create(name="agente")
    user, _ = conta_agente_principal(company)
    if user is None:
        username = _agent_username(company)
        if User.objects.filter(username=username).exists():
            raise ValueError(f"A conta {username} já existe e pertence a outra empresa. Renomeie esta empresa.")
        user = User.objects.create(username=username)
        user.set_unusable_password()
        user.save()
    if not user.is_active:
        user.is_active = True
        user.save(update_fields=["is_active"])
    user.groups.add(agent_group)
    company.members.add(user)
    return user

@transaction.atomic
def vincular_conta_agente(company):
    """Religa (ou cria) a conta do agente à empresa sem trocar a chave -- o agente volta a
    funcionar com a mesma chave que já tem. Idempotente."""
    _garantir_conta_agente(company)
    return agent_status(company)

@transaction.atomic
def gerar_token_agente(company, dias_validade):
    """Cria a conta de serviço do agente se ainda não existir, e sempre
    GERA UM TOKEN NOVO (rotação: qualquer token antigo dessa empresa para de
    funcionar na hora). A chave completa só é devolvida aqui -- depois disso
    só a versão mascarada (agent_status) fica disponível, igual ao Django Admin."""
    user = _garantir_conta_agente(company)
    Token.objects.filter(user=user).delete()
    token = Token.objects.create(user=user)
    expires_at = timezone.now() + timedelta(days=dias_validade)
    AgentTokenExpiry.objects.create(token=token, expires_at=expires_at)
    return {"username": user.username, "token": token.key, "expires_at": expires_at}

def revogar_token_agente(company, user_id=None):
    """Apaga a chave da conta principal do agente, ou a de uma conta de agente específica desta
    empresa (user_id). Devolve False se user_id não for uma conta de agente desta empresa."""
    principal, _ = conta_agente_principal(company)
    if user_id is None:
        alvo = principal
    else:
        alvo = company.members.filter(groups__name="agente", pk=user_id).first()
        if alvo is None and principal is not None and principal.pk == user_id:
            alvo = principal  # a principal, mesmo desvinculada, ainda é "desta empresa"
        if alvo is None:
            return False
    if alvo is not None:
        Token.objects.filter(user=alvo).delete()
    return True

def dados_conta_empresa(u):
    profile = getattr(u, "profile", None)
    return {
        "id": u.pk, "username": u.username, "email": u.email,
        "display_name": (profile.display_name if profile else "") or u.first_name,
        "is_active": u.is_active, "date_joined": u.date_joined, "last_login": u.last_login,
        "must_change_password": PasswordChangeRequired.objects.filter(user=u).exists(),
    }

def contas_empresa_queryset(company):
    return company.members.filter(is_staff=True, is_superuser=False).exclude(groups__name="agente").order_by("username")

def contas_da_empresa(company):
    """Tudo que o Painel Admin mostra de contas no seletor da empresa: a conta do agente
    (+ outras contas de agente legadas) e as contas "Empresa" (login humano do cliente)."""
    principal, _ = conta_agente_principal(company)
    extras = [
        _status_conta_agente(u, True)
        for u in company.members.filter(groups__name="agente").order_by("pk")
        if not principal or u.pk != principal.pk
    ]
    return {
        "agente": agent_status(company),
        "agentes_extras": extras,
        "empresa": [dados_conta_empresa(u) for u in contas_empresa_queryset(company)],
    }

@transaction.atomic
def criar_conta_empresa(company, email, nome=""):
    """Conta Empresa (login humano do cliente no painel): is_staff, membro desta empresa, senha
    provisória com troca obrigatória no 1º acesso -- mesmo padrão dos convites de atendente.
    Devolve (usuário, senha provisória); o envio do e-mail é feito pela view (pode falhar sem
    desfazer a conta, e a senha aparece para o admin uma única vez)."""
    User = get_user_model()
    email = (email or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) or len(email) > 150:
        raise ValueError("Informe um e-mail válido.")
    if User.objects.filter(Q(username__iexact=email) | Q(email__iexact=email)).exists():
        raise ValueError("Já existe uma conta com este e-mail.")
    nome = (nome or "").strip()[:150]
    senha = secrets.token_urlsafe(9)
    user = User.objects.create_user(username=email, email=email, password=senha, first_name=nome, is_staff=True)
    Profile.objects.get_or_create(user=user, defaults={"display_name": nome})
    PasswordChangeRequired.objects.create(user=user)
    company.members.add(user)
    return user, senha

def enviar_credenciais_conta_empresa(user, senha, company_name):
    """True se o e-mail saiu; False (sem levantar) se o SMTP falhou -- a conta já existe e a
    senha provisória é mostrada ao admin de qualquer jeito."""
    try:
        send_credentials_email(user.email, user.first_name or company_name, senha)
        return True
    except Exception:
        logger.exception("Falha ao enviar credenciais da conta Empresa %s", user.pk)
        return False

def redefinir_senha_conta_empresa(user):
    """Nova senha provisória (troca obrigatória no próximo login). Devolve a senha."""
    senha = secrets.token_urlsafe(9)
    user.set_password(senha)
    user.save()
    PasswordChangeRequired.objects.get_or_create(user=user)
    return senha

def enviar_redefinicao_conta_empresa(user, senha):
    try:
        profile = getattr(user, "profile", None)
        nome = (profile.display_name if profile else "") or user.first_name or user.username
        send_password_reset_by_admin_email(user.email or user.username, nome, senha)
        return True
    except Exception:
        logger.exception("Falha ao enviar a nova senha da conta Empresa %s", user.pk)
        return False

@transaction.atomic
def excluir_empresa(company):
    """Exclui a empresa e tudo que é dela. Contas que pertencem SÓ a ela (conta de
    serviço do agente, atendentes, conta Empresa) são excluídas junto; contas
    vinculadas a outra empresa e superusers nunca são tocados."""
    User = get_user_model()
    company = Company.objects.select_for_update().get(pk=company.pk)
    candidatos = set(company.members.values_list("pk", flat=True))
    candidatos.update(User.objects.filter(username=_agent_username(company)).values_list("pk", flat=True))
    exclusivos = [
        u.pk for u in User.objects.filter(pk__in=candidatos, is_superuser=False)
        if not u.companies.exclude(pk=company.pk).exists()
    ]
    resumo = {
        "empresa": company.name,
        "leads": Lead.objects.filter(company=company).count(),
        "usuarios_excluidos": len(exclusivos),
    }
    # Question.variavel / Question.variavel_roteiro são PROTECT: sem apagar as
    # perguntas antes, o cascade de Company trava em ProtectedError.
    Question.objects.filter(company=company).delete()
    company.delete()
    User.objects.filter(pk__in=exclusivos).delete()
    return resumo

# --- Ciclo de vida pós-triagem: assumir e despachar (kanban "Atendimentos em
# Espera" -> "Atendimento humano" -> encerrado/comprometido/falha) ---

def _nome_usuario(user):
    """Só pra EXIBIÇÃO -- nunca usar pra comparar dono de lead (isso é Lead.owner, FK)."""
    if user is None:
        return ""
    profile = getattr(user, "profile", None)
    return (profile.display_name if profile else "") or user.get_full_name() or user.username

def _validar_lead_classificavel(lead):
    """Checagem comum a toda transição pós-triagem do Kanban (Qualificados em
    diante): precisa ter terminado o funil -- ou ter sido escalado pra humano no
    meio dele (falha de entrega, pedido humano, área desconhecida...), senão esse
    lead ficaria preso sem ninguém poder assumir -- e não pode ser Desqualificado/
    Desconfiado (esses nunca entram na fila de atendimento humano)."""
    if not lead.bot_closed and lead.mode != "HUMANO":
        return "Este lead ainda não concluiu a triagem."
    if lead.temperature in FORA_DO_KANBAN:
        return "Leads classificados como Desqualificado ou Desconfiado não entram na fila de atendimento humano."
    if lead.desfecho:
        return "Este atendimento já foi concluído."
    return None

@transaction.atomic
def reivindicar_lead(lead_id, user):
    """Qualificados -> Atendimentos em espera: sinaliza a pendência para toda
    a equipe, sem atribuir responsável. Só a negociação assume o atendimento.
    select_for_update impede disputar com uma negociação simultânea."""
    lead = Lead.objects.select_for_update().filter(pk=lead_id).first()
    if not lead:
        return "Lead não encontrado."
    erro = _validar_lead_classificavel(lead)
    if erro:
        return erro
    if lead.owner_id or lead.etapa_atendimento:
        return "Só é possível colocar em espera um lead em Qualificados."
    lead.owner = None
    lead.etapa_atendimento = "espera"
    lead.save(update_fields=["owner", "etapa_atendimento"])
    return None

@transaction.atomic
def acompanhar_lead(lead_id, user):
    """Atendente assume um Novo lead durante a triagem e interrompe o agente.
    Usa o mesmo lock da empresa que receive para não competir com a próxima mensagem."""
    company_id = Lead.objects.filter(pk=lead_id).values_list("company_id", flat=True).first()
    if company_id is None:
        return "Lead não encontrado."
    company = Company.objects.select_for_update().get(pk=company_id)
    lead = Lead.objects.select_for_update().filter(pk=lead_id).first()
    if not lead or not company.members.filter(pk=user.pk).exists():
        return "Lead não encontrado."
    if lead.desfecho or lead.temperature in FORA_DO_KANBAN:
        return "Este lead não está disponível para atendimento."
    if lead.owner_id:
        return "Este atendimento já foi assumido por um atendente."
    if lead.bot_closed or lead.mode != "AUTOMÁTICO" or lead.etapa_atendimento or lead.origem_manual:
        return "Só é possível acompanhar por esta ação um Novo lead ainda em triagem."
    lead.owner = user
    lead.mode = "HUMANO"
    lead.etapa_atendimento = "negociacao"
    lead.next_action = "Atendimento assumido durante a triagem"
    lead.save(update_fields=["owner", "mode", "etapa_atendimento", "next_action"])
    Event.objects.create(
        lead=lead, message_id=f"acompanhar:{secrets.token_hex(16)}",
        summary="Atendente assumiu atendimento durante a triagem",
    )
    return None

@transaction.atomic
def mover_para_negociacao(lead_id, user):
    """Qualificados OU Atendimentos em espera -> Em negociação: quem inicia
    se torna responsável. Um atendimento já assumido só pode ser movido por
    seu responsável."""
    lead = Lead.objects.select_for_update().filter(pk=lead_id).first()
    if not lead:
        return "Lead não encontrado."
    if lead.owner_id and lead.owner_id != user.pk:
        return "Só quem assumiu este atendimento pode movê-lo."
    erro = _validar_lead_classificavel(lead)
    if erro:
        return erro
    lead.owner = user
    lead.mode = "HUMANO"
    lead.etapa_atendimento = "negociacao"
    lead.save(update_fields=["owner", "mode", "etapa_atendimento"])
    return None

@transaction.atomic
def preparar_despacho(lead_id, desfecho, user, auto_falha=False, especialidade=None):
    """Qualificados, Em espera OU Em negociação -> Despacho: só RESERVA o
    desfecho (desfecho_pendente), não finaliza ainda -- isso só acontece em
    enviar_despachos (botão 'Enviar Despachos'). `auto_falha=True` é a
    transição direta Qualificados -> Despacho (sem nunca ter negociado):
    força 'falha', ignora o `desfecho` pedido. `especialidade` (opcional) é a
    área que o atendente escolhe ao despachar -- só uma Area desta empresa."""
    lead = Lead.objects.select_for_update().filter(pk=lead_id).first()
    if not lead:
        return "Lead não encontrado."
    if lead.owner_id and lead.owner_id != user.pk:
        return "Só quem assumiu este atendimento pode despachá-lo."
    erro = _validar_lead_classificavel(lead)
    if erro:
        return erro
    desfecho_final = "falha" if auto_falha else desfecho
    if desfecho_final not in Lead.DESFECHO_DESPACHO:
        return "Classificação de despacho inválida."
    campos = ["owner", "etapa_atendimento", "desfecho_pendente"]
    if especialidade:
        if not isinstance(especialidade, str) or not Area.objects.filter(company_id=lead.company_id, name=especialidade).exists():
            return "Área inválida: escolha uma das áreas cadastradas pela empresa."
        lead.especialidade = especialidade
        campos.append("especialidade")
    lead.owner = user
    lead.etapa_atendimento = "despacho"
    lead.desfecho_pendente = desfecho_final
    lead.save(update_fields=campos)
    return None

@transaction.atomic
def liberar_lead(lead_id, user):
    """Em espera ou atendimento assumido -> Qualificados. Em espera é uma fila
    compartilhada; depois de assumir, só o responsável pode devolver."""
    lead = Lead.objects.select_for_update().filter(pk=lead_id).first()
    if not lead:
        return "Lead não encontrado."
    if not lead.owner_id and not lead.etapa_atendimento:
        return "Este atendimento não está assumido por ninguém."
    if lead.owner_id and lead.owner_id != user.pk:
        return "Só quem assumiu este atendimento pode devolvê-lo pra Qualificados."
    if lead.desfecho:
        return "Este atendimento já foi concluído."
    lead.owner = None
    # Só volta pra AUTOMÁTICO quem já terminou a triagem (aí bot_closed mantém o bot
    # mudo de qualquer jeito). Lead escalado no meio do funil continua HUMANO --
    # senão "devolver" religaria o agente num caso que pediu humano.
    if lead.bot_closed:
        lead.mode = "AUTOMÁTICO"
    lead.etapa_atendimento = ""
    lead.desfecho_pendente = ""
    lead.save(update_fields=["owner", "mode", "etapa_atendimento", "desfecho_pendente"])
    return None

def criar_lead_manual(company, user, dados):
    """Atendimento Humano: o atendente cadastra um atendimento próprio que não
    veio do WhatsApp/agente (ex.: contato por outro canal). Entra direto como
    responsabilidade do próprio atendente que criou -- nunca passa pelo funil
    de triagem nem aparece no Kanban de Leads (ver Lead.origem_manual), só
    conta nas estatísticas do Dashboard. Retorna (lead, erro); erro é None se
    criado com sucesso."""
    from django.db import IntegrityError
    from .serializers import LeadManualSerializer
    entrada = LeadManualSerializer(data=dados)
    if not entrada.is_valid():
        campo, erros = next(iter(entrada.errors.items()))
        return None, str(erros[0]) if campo == "non_field_errors" else f"{LeadManualSerializer.ROTULOS.get(campo, campo)}: {erros[0]}"
    v = entrada.validated_data
    try:
        with transaction.atomic():
            # Lock da empresa: mesma serialização de services.receive, então a checagem
            # de duplicado e a criação nunca correm em paralelo com outro cadastro/agente.
            Company.objects.select_for_update().get(pk=company.pk)
            # Só bloqueia se já existir um lead ATIVO pra esse contato -- um lead antigo já
            # despachado não impede um novo cadastro (mesma regra de "ativo" de receive).
            if Lead.objects.filter(company=company, contact=v["contact"], desfecho="").exists():
                return None, "Já existe um lead ativo com esse contato nesta empresa."
            lead = Lead.objects.create(
                company=company,
                name=v["name"],
                contact=v["contact"],
                state="ATENDIMENTO_MANUAL",
                funnel_stage="Atendimento manual",
                demand=v["demand"],
                bot_closed=True,
                mode="HUMANO",
                owner=user,
                origem_manual=True,
            )
    except IntegrityError:
        return None, "Já existe um lead ativo com esse contato nesta empresa."
    return lead, None

@transaction.atomic
def enviar_despachos(user, company):
    """Botão 'Enviar Despachos': finaliza de uma vez TODOS os leads que este
    atendente já reservou na coluna Despacho DESTA empresa (desfecho_pendente
    -> desfecho definitivo). Devolve a quantidade enviada."""
    leads = list(Lead.objects.select_for_update().filter(company=company, owner=user, etapa_atendimento="despacho", desfecho="").exclude(desfecho_pendente=""))
    agora = timezone.now()
    for lead in leads:
        lead.desfecho = lead.desfecho_pendente
        lead.concluido_em = agora
        lead.desfecho_pendente = ""
        lead.etapa_atendimento = ""
        lead.next_action = ""
        lead.save(update_fields=["desfecho", "concluido_em", "desfecho_pendente", "etapa_atendimento", "next_action"])
    return len(leads)

# --- Urgência: média das notas (0-10) do agente ponderada pelos pesos das Variáveis ---
# Faixas contínuas sobre o score 0-10, da menos pra mais urgente. Mesma tabela é
# exposta ao agente em GET /companies/{id}/agente/contexto/ (faixas_urgencia).
FAIXAS_URGENCIA = [
    (0, 3, "Desqualificado"),
    (3, 5, "Desconfiado"),
    (5, 7, "Frio"),
    (7, 9, "Qualificado"),
    (9, None, "Quente"),
]
URGENCIA_RANK = {temp: i for i, (_, _, temp) in enumerate(FAIXAS_URGENCIA)}
NOMES_CLASSIFICACAO = [temp for _, _, temp in FAIXAS_URGENCIA]
CORTES_PADRAO = [3, 5, 7, 9]
MAX_REGRA_CLASSIFICACAO = 1500

def validar_cortes(cortes):
    """4 notas de 0 a 10, estritamente crescentes (mín. 0,1 entre elas), em passos de 0,1. Devolve a lista limpa
    ou levanta ValueError com a mensagem para a tela."""
    if not isinstance(cortes, (list, tuple)) or len(cortes) != 4:
        raise ValueError("Informe os 4 cortes das faixas de classificação.")
    try:
        valores = [round(float(c), 1) for c in cortes]
    except (TypeError, ValueError):
        raise ValueError("Os cortes precisam ser números.")
    if any(v < 0 or v > 10 for v in valores):
        raise ValueError("Os cortes ficam entre 0 e 10.")
    if any(b - a < 0.099 for a, b in zip(valores, valores[1:])) or valores[0] < 0.1 or valores[-1] > 9.9:
        raise ValueError("Cada faixa precisa ter ao menos 0,1 de largura: os cortes devem ser crescentes.")
    return valores

def faixas_da_empresa(company=None):
    """Mesma estrutura de FAIXAS_URGENCIA, mas com os cortes da empresa (padrão 3/5/7/9)."""
    try:
        cortes = validar_cortes(getattr(company, "classificacao_cortes", None) or CORTES_PADRAO)
    except ValueError:
        cortes = CORTES_PADRAO
    limites = [0, *cortes, None]
    return [(limites[i], limites[i + 1], NOMES_CLASSIFICACAO[i]) for i in range(5)]
PRIORIDADE_POR_TEMPERATURA = {"Quente": "Alta", "Qualificado": "Média"}

# O agente manda TODOS os leads pro CRM, até os desqualificados/desconfiados
# -- mas esses dois nunca entram no fluxo operacional do Kanban nem podem ser
# assumidos por atendente, só contam nas estatísticas do dashboard.
FORA_DO_KANBAN = {"Desqualificado", "Desconfiado"}
PODE_ASSUMIR_A_PARTIR_DE = "Frio"
# "Concluído com sucesso" = desfecho Encerrado (o cliente conseguiu o que queria);
# Comprometido e Falha também são conclusões, mas não de sucesso.
DESFECHO_SUCESSO = "encerrado"

def calcular_urgencia(notas, pesos, faixas=None):
    """score = Σ(nota × peso) / Σ(peso), só sobre os question_id que têm peso.
    Retorna (score, temperatura) ou None se nenhuma nota tiver peso conhecido."""
    usados = [(float(notas[qid]), pesos[qid]) for qid in notas if qid in pesos and pesos[qid]]
    if not usados:
        return None
    score = sum(nota * peso for nota, peso in usados) / sum(peso for _, peso in usados)
    faixas = faixas or FAIXAS_URGENCIA
    for minimo, maximo_exclusivo, temperatura in faixas:
        if score >= minimo and (maximo_exclusivo is None or score < maximo_exclusivo):
            return score, temperatura
    return score, faixas[0][2]

# Chave do Detalhamento em Lead.urgencia_detalhe["notas"/"pesos"] (não é um question_id).
CHAVE_DETALHAMENTO = "_detalhamento"

def calcular_detalhamento(lead, fields=None):
    """Nota 0-10 de quanto o cliente detalhou o caso, calculada pelo CRM com o que o agente coletou
    (sem depender de o agente "achar" nada): demanda (até 4), observações (até 3), impacto (1),
    variáveis de roteiro extras preenchidas (até 1) e nome informado (1). `fields` são os dados do
    CLASSIFICADO ainda não aplicados ao lead."""
    fields = fields or {}
    demanda = str(fields.get("tema") or lead.demand or "").strip()
    impacto = str(fields.get("impacto") or lead.impacto or "").strip()
    nome = str(fields.get("nome") or lead.name or "").strip()
    observacoes = mesclar_observacoes(lead.notes, fields.get("observacoes"))
    n_obs = len([i for i in observacoes.split(";") if i.strip()])
    extras = len([v for v in (lead.variaveis_roteiro or {}).values() if str(v).strip()])
    nota = (
        min(len(demanda) / 120, 1) * 4
        + min(n_obs / 3, 1) * 3
        + (1 if impacto else 0)
        + min(extras / 2, 1)
        + (1 if nome else 0)
    )
    return round(nota, 1)

def _aplicar_notas_urgencia(lead, company, fields):
    """CLASSIFICADO com fields.notas: o CRM calcula temperatura (prevalece sobre a do
    agente) e, se não vier, a prioridade; grava o detalhe pra auditoria. Retorna
    (fields_atualizados, erro_ou_None)."""
    notas = {**(lead.urgencia_detalhe or {}).get("notas", {}), **(fields.get("notas") or {})}
    if company.etapa_inicial:
        perguntas = perguntas_spin_inicial(company, lead)
        ids = {q.question_id for q in perguntas if not q.variavel_roteiro_id or q.variavel_roteiro.slug != "nome"}
        notas = {qid: nota for qid, nota in notas.items() if qid in ids}
        if not notas:
            return fields, "Classificação SPIN exige notas das perguntas da SPIN selecionada"
        # Na classificação antecipada, perguntas ainda não feitas não são notas zero.
        if perguntas and lead.state == perguntas[-1].question_id:
            enviadas = {result.get("question_id") for result in lead.events.filter(delivery="SENT").values_list("result", flat=True)}
            notas = {qid: notas.get(qid, 0) for qid in ids if qid in enviadas or qid in notas}
    else:
        # Fluxo clássico: nota de pergunta SPIN de OUTRA área não entra no cálculo (o agente só deveria usar
        # as fixas e a SPIN da área do lead; o CRM não confia só na instrução). Área vem de fields ou do lead.
        area = str(fields.get("especialidade") or lead.especialidade or "")
        de_outra_area = set(
            Question.objects.filter(company=company, question_id__in=list(notas), area__isnull=False)
            .exclude(area__name=area).values_list("question_id", flat=True)
        )
        notas = {qid: nota for qid, nota in notas.items() if qid not in de_outra_area}
    if not notas:
        return fields, None
    pesos = dict(
        Question.objects.filter(company=company, question_id__in=list(notas), variavel__isnull=False)
        .values_list("question_id", "variavel__peso")
    )
    if calcular_urgencia(notas, pesos) is None:
        return fields, "Notas de urgência sem nenhuma pergunta com variável/peso cadastrado: revisar integração do agente"
    usados = {qid: notas[qid] for qid in notas if qid in pesos}
    nomes = dict(
        Question.objects.filter(company=company, question_id__in=list(usados), variavel__isnull=False)
        .values_list("question_id", "variavel__name")
    )
    # Detalhamento: variável do sistema, nota calculada pelo CRM, entra na média com o peso da empresa.
    detalhamento = variavel_detalhamento(company)
    pesos = {qid: pesos[qid] for qid in usados if qid in pesos}
    if detalhamento.peso:  # a API só aceita 1-10; peso 0 só existe se alguém zerar direto no banco
        usados[CHAVE_DETALHAMENTO] = calcular_detalhamento(lead, fields)
        pesos[CHAVE_DETALHAMENTO] = detalhamento.peso
        nomes[CHAVE_DETALHAMENTO] = detalhamento.name
    score, temperatura = calcular_urgencia(usados, pesos, faixas_da_empresa(company))
    fields = {**fields, "temperatura": temperatura}
    if not fields.get("prioridade"):
        fields["prioridade"] = PRIORIDADE_POR_TEMPERATURA.get(temperatura, "Baixa")
    lead.urgencia_detalhe = {
        "notas": usados,
        "pesos": pesos,
        "nomes": nomes,
        "score": round(score, 2),
        "temperatura_calculada": temperatura,
    }
    return fields, None

TRIAGEM_ABANDONADA_APOS = timedelta(hours=24)
# Lembrete de continuidade: 24h sem resposta -> o CRM reserva o envio (reservar_lembretes); sem retorno
# em mais 24h depois de o lembrete ser confirmado (SENT), a triagem é apagada. Se o lembrete nunca
# saiu (gateway parado), a triagem é apagada mesmo assim: 48h após o envio tentado, 72h sem tentativa.
LEMBRETE_APOS = timedelta(hours=24)
APAGAR_APOS_LEMBRETE = timedelta(hours=24)
APAGAR_LEMBRETE_FALHO_APOS = timedelta(hours=48)
APAGAR_SEM_LEMBRETE_APOS = timedelta(hours=72)

def triagens_paradas(agora=None):
    """Leads em triagem automática sem nenhuma mensagem do cliente há 24h+ (base do lembrete e da limpeza)."""
    agora = agora or timezone.now()
    limite = agora - TRIAGEM_ABANDONADA_APOS
    return Lead.objects.filter(
        Q(last_contact__lt=limite) | Q(last_contact__isnull=True, created_at__lt=limite),
        desfecho="", bot_closed=False, origem_manual=False,
    ).exclude(mode="HUMANO")

def lembrete_da_empresa(company):
    """Texto 'lembrete' ligado (habilitado e com conteúdo); None = a empresa não envia lembrete.
    Independe da Etapa Inicial: ela desliga os outros textos fora do fluxo, não este."""
    q = Question.objects.filter(company=company, question_id="lembrete", habilitada=True).first()
    return q if q and q.text.strip() else None

def horario_do_lembrete(ultimo_contato, horario=None):
    """Quando o lembrete pode sair: 24h depois do último contato ou, com horário definido pela empresa,
    a primeira ocorrência desse horário (fuso do CRM) a partir daí."""
    base = ultimo_contato + LEMBRETE_APOS
    if not horario:
        return base
    local = timezone.localtime(base)
    alvo = local.replace(hour=horario.hour, minute=horario.minute, second=0, microsecond=0)
    return alvo if alvo >= local else alvo + timedelta(days=1)

def _pergunta_pendente_do_lembrete(company, lead):
    """Pergunta em que o lead parou (lead.state), pronta para reenviar; None se não houver uma de fluxo."""
    pergunta = Question.objects.filter(company=company, question_id=lead.state).first() if lead.state else None
    if not pergunta or pergunta.question_id in MANDATORY_OFFFLOW_QUESTION_IDS or not pergunta.text.strip():
        return None
    if company.etapa_inicial and (pergunta.area_id is None or pergunta.area_id != getattr(spin_efetiva(company, lead), "pk", None)):
        return None
    return pergunta

@transaction.atomic
def reservar_lembretes(company, agora=None):
    """Reserva (uma única vez por lead) os lembretes que já podem sair e devolve o que a ponte precisa enviar:
    duas mensagens, o texto do lembrete e a pergunta em que o cliente parou. Cada reserva é um Event
    marker=LEMBRETE em PENDING; a ponte confirma em /delivery/ (SENT grava lembrete_enviado_em; FAILED não
    apaga o lead)."""
    agora = agora or timezone.now()
    config = lembrete_da_empresa(company)
    if not config:
        return []
    Company.objects.select_for_update().get(pk=company.pk)  # mesmo lock do receive(): não corre com uma resposta do cliente
    reservados = []
    candidatos = triagens_paradas(agora).filter(company=company).exclude(events__marker="LEMBRETE").order_by("last_contact", "created_at")
    for lead in candidatos:
        referencia = lead.last_contact or lead.created_at
        if agora < horario_do_lembrete(referencia, config.horario_envio) or agora - referencia >= APAGAR_SEM_LEMBRETE_APOS:
            continue
        mensagens = [{"question_id": "lembrete", "content": render_text(config.text, lead, company)}]
        pergunta = _pergunta_pendente_do_lembrete(company, lead)
        if pergunta:
            mensagens.append({"question_id": pergunta.question_id, "content": render_text(pergunta.text, lead, company)})
        evento = Event.objects.create(
            lead=lead, message_id=f"lembrete-{lead.pk}", marker="LEMBRETE", summary="Lembrete de continuidade (24h sem resposta)",
            result={"action": "LEMBRETE", "mensagens": mensagens}, delivery="PENDING",
        )
        reservados.append({"event_id": evento.pk, "lead_id": str(lead.pk), "contact": lead.contact, "mensagens": mensagens})
    return reservados

def _deve_apagar_triagem(lead, lembrete_ativo, agora):
    referencia = lead.last_contact or lead.created_at
    if not lembrete_ativo:
        return referencia < agora - TRIAGEM_ABANDONADA_APOS
    if lead.lembrete_enviado_em:
        return max(referencia, lead.lembrete_enviado_em) < agora - APAGAR_APOS_LEMBRETE
    tentado = lead.events.filter(marker="LEMBRETE").exists()
    return referencia < agora - (APAGAR_LEMBRETE_FALHO_APOS if tentado else APAGAR_SEM_LEMBRETE_APOS)

def apagar_triagens_abandonadas(agora=None):
    """Triagem automática sem resposta do contato é apagada (o lead e os eventos): triagem que não terminou
    nunca vai pra equipe; o número recomeça do zero. Com o lembrete ligado na empresa, só depois de ele ser
    enviado e de mais 24h sem retorno (veja reservar_lembretes); sem lembrete, 24h como antes.
    Idempotente. Retorna quantos leads foram apagados."""
    agora = agora or timezone.now()
    leads = triagens_paradas(agora)
    total = 0
    company_ids = list(leads.order_by().values_list("company_id", flat=True).distinct())
    for company_id in company_ids:
        with transaction.atomic():
            # receive usa o mesmo lock: reavalia a inatividade após qualquer entrada concorrente.
            company = Company.objects.select_for_update().filter(pk=company_id).first()
            if not company:
                continue
            ativo = lembrete_da_empresa(company) is not None
            ids = [l.pk for l in leads.filter(company_id=company_id) if _deve_apagar_triagem(l, ativo, agora)]
            if not ids:
                continue
            da_empresa = Lead.objects.filter(pk__in=ids)
            # "Não prosseguiram": guarda quantos leads vão embora, no dia em que nasceram.
            por_dia = Counter(timezone.localtime(c).date() for c in da_empresa.values_list("created_at", flat=True))
            _, por_modelo = da_empresa.delete()
            for dia, quantidade in por_dia.items():
                _somar_contagem(company_id, dia, "nao_prosseguiram", quantidade)
            total += por_modelo.get("crm.Lead", 0)
    return total

def marcar_situacao_especial(company, lead, event, valor, fields):
    """Lead em triagem que não é lead novo (ex.: cliente que quer acompanhar um processo): sai da
    triagem, fica sem temperatura e fora do Kanban (aparece em "Outras situações") e o número segue
    preso até a equipe concluir. Devolve a resposta ao contato: o texto obrigatório fora do fluxo da
    situação, ou silêncio (NO_REPLY) quando ele está desligado ou a Etapa Inicial está ligada."""
    info = SITUACOES_ESPECIAIS[valor]
    extras = {k: fields[k] for k in ("nome", "observacoes") if fields.get(k)}
    if extras:
        apply_fields(lead, company, extras)
    if not lead.name.strip():
        lead.name = lead.contact_name
    lead.situacao_especial = valor
    lead.bot_closed = True
    lead.mode = "AUTOMÁTICO"
    lead.pedido_humano_pendente = False
    lead.state = "ENCERRADO_ESPECIAL"
    lead.funnel_stage = info["rotulo"]
    lead.next_action = info["next_action"]
    lead.save()
    event.summary = f"Situação especial: {info['rotulo']}"
    result = dict(NO_REPLY)
    question = Question.objects.filter(company=company, question_id=info["question_id"]).first()
    if question and texto_fora_habilitado(company, info["question_id"]) and (question.text or "").strip():
        asset = render_text(question.text, lead, company)
        if asset:
            result = {"action": "TEXTO", "content": asset, "question_id": info["question_id"]}
            event.delivery = "PENDING"
    return result

def criar_situacao_especial_manual(company, user, dados, valor="acompanhamento"):
    """Outras situações: cadastro manual de um acompanhamento (cliente que contatou por outro canal).
    Atendente que cadastra vira o responsável; a conta Empresa deixa sem responsável. Não passa pela
    triagem nem conta como nova lead. Retorna (lead, erro)."""
    from django.db import IntegrityError
    from .serializers import LeadManualSerializer
    info = SITUACOES_ESPECIAIS[valor]
    entrada = LeadManualSerializer(data=dados)
    if not entrada.is_valid():
        campo, erros = next(iter(entrada.errors.items()))
        return None, str(erros[0]) if campo == "non_field_errors" else f"{LeadManualSerializer.ROTULOS.get(campo, campo)}: {erros[0]}"
    v = entrada.validated_data
    try:
        with transaction.atomic():
            Company.objects.select_for_update().get(pk=company.pk)
            if Lead.objects.filter(company=company, contact=v["contact"], desfecho="").exists():
                return None, "Já existe um lead ativo com esse contato nesta empresa."
            lead = Lead.objects.create(
                company=company, name=v["name"], contact=v["contact"], demand=v["demand"],
                notes=mesclar_observacoes("", (dados.get("observacoes") if hasattr(dados, "get") else "") or ""),
                state="ENCERRADO_ESPECIAL", funnel_stage=info["rotulo"], next_action=info["next_action"],
                situacao_especial=valor, bot_closed=True, origem_manual=True,
                owner=None if user.is_staff else user,
            )
            Event.objects.create(lead=lead, message_id=f"especial-manual:{secrets.token_hex(16)}", summary=f"Cadastro manual: {info['rotulo']}")
    except IntegrityError:
        return None, "Já existe um lead ativo com esse contato nesta empresa."
    return lead, None

def _lead_especial_com_acesso(lead_id, user):
    lead = Lead.objects.select_for_update().filter(pk=lead_id).first()
    if not lead or not Company.objects.filter(pk=lead.company_id, members=user).exists():
        return None, "Lead não encontrado."
    if not lead.situacao_especial or lead.desfecho:
        return None, "Este lead não está em Outras situações."
    return lead, None

@transaction.atomic
def assumir_situacao_especial(lead_id, user):
    """Atendente assume o acompanhamento (fica como responsável); o lead continua em Outras situações."""
    lead, erro = _lead_especial_com_acesso(lead_id, user)
    if erro:
        return erro
    if lead.owner_id and lead.owner_id != user.pk:
        return "Este lead já foi assumido por outro atendente."
    lead.owner = user
    lead.save(update_fields=["owner"])
    Event.objects.create(lead=lead, message_id=f"especial-assumir:{secrets.token_hex(16)}", summary="Atendente assumiu o acompanhamento")
    return None

@transaction.atomic
def despachar_situacao_especial(lead_id, user, desfecho="encerrado", especialidade=None, motivo=""):
    """Outras situações segue a regra de despacho: o responsável (ou a conta Empresa) classifica o
    desfecho (encerrado/comprometido/falha, ou bloqueado -- que também põe o número na BlackList) e
    opcionalmente a área. O lead entra nas contagens de concluídos e despachos e o número é liberado.
    Quem despacha sem responsável vira o responsável. Retorna erro (str) ou None."""
    company_id = Lead.objects.filter(pk=lead_id).values_list("company_id", flat=True).first()
    if company_id is None:
        return "Lead não encontrado."
    # Mesma ordem de locks do incoming: nenhuma mensagem cria lead novo entre o despacho e a BlackList.
    Company.objects.select_for_update().get(pk=company_id)
    lead, erro = _lead_especial_com_acesso(lead_id, user)
    if erro:
        return erro
    if desfecho not in Lead.DESFECHO_CONCLUIDO:
        return "Classificação de despacho inválida."
    if lead.owner_id and lead.owner_id != user.pk and not user.is_staff:
        return "Só quem assumiu este acompanhamento (ou a conta Empresa) pode despachá-lo."
    campos = ["desfecho", "concluido_em", "desfecho_pendente", "etapa_atendimento", "next_action"]
    if especialidade:
        if not isinstance(especialidade, str) or not Area.objects.filter(company_id=lead.company_id, name=especialidade).exists():
            return "Área inválida: escolha uma das áreas cadastradas pela empresa."
        lead.especialidade = especialidade
        campos.append("especialidade")
    if not lead.owner_id and not user.is_staff:
        lead.owner = user
        campos.append("owner")
    if desfecho == "bloqueado":
        Blacklist.objects.get_or_create(
            company=lead.company, contact=lead.contact,
            defaults={"motivo": motivo or "Despachado e bloqueado pelo atendente", "adicionado_por": user},
        )
    lead.desfecho = desfecho
    lead.concluido_em = timezone.now()
    lead.desfecho_pendente = ""
    lead.etapa_atendimento = ""
    lead.next_action = ""
    lead.save(update_fields=campos)
    Event.objects.create(lead=lead, message_id=f"especial-despachar:{secrets.token_hex(16)}", summary=f"Acompanhamento despachado: {desfecho}")
    return None

def concluir_situacao_especial(lead_id, user):
    """Compatibilidade: despacho com o desfecho padrão (encerrado)."""
    return despachar_situacao_especial(lead_id, user, "encerrado")

def desqualificar_sem_resposta(lead):
    """A mesma pergunta foi repetida MAX_REPETICOES vezes sem resposta utilizável: desqualifica
    (o lead fica registrado, fora do Kanban) e libera o número em vez de apagar a triagem."""
    desqualificar_fora_de_escopo(lead, motivo="sem_resposta", proxima_acao="Sem resposta após repetições")

def _eh_fora_de_escopo(especialidade):
    return (especialidade or "").strip().lower() == "fora de escopo"

def desqualificar_fora_de_escopo(lead, motivo="fora_de_escopo", proxima_acao="Fora de escopo"):
    """Fora de escopo nunca chega a Qualificados nem fica com prioridade Alta: desqualifica na
    hora (fora do Kanban, conta nas estatísticas) e libera o número. Também encerra o contato
    que não deu resposta utilizável depois de MAX_REPETICOES repetições (motivo "sem_resposta")."""
    lead.temperature = "Desqualificado"
    lead.priority = "Baixa"
    lead.mode = "AUTOMÁTICO"
    lead.bot_closed = True
    lead.state = "ENCERRADO_CLASSIFICADO"
    lead.funnel_stage = "Triagem concluída"
    lead.next_action = proxima_acao
    lead.desfecho = "desqualificado"
    lead.concluido_em = timezone.now()
    lead.urgencia_detalhe = {**(lead.urgencia_detalhe or {}), "motivo": motivo}
    lead.save()

@transaction.atomic
def despachar_e_bloquear(lead_id, user, motivo=""):
    """Atendente dono conclui o lead com desfecho "bloqueado" e põe o número na BlackList,
    numa transação só (sem passar pela fila de Enviar Despachos). Retorna erro (str) ou None."""
    company_id = Lead.objects.filter(pk=lead_id).values_list("company_id", flat=True).first()
    if company_id is None:
        return "Lead não encontrado."
    # Mesma ordem de locks do incoming: nenhuma mensagem cria um novo lead
    # entre a conclusão do atendimento e a inclusão na BlackList.
    Company.objects.select_for_update().get(pk=company_id)
    lead = Lead.objects.select_for_update().filter(pk=lead_id).first()
    if not lead or not lead.company.members.filter(pk=user.pk).exists():
        return "Lead não encontrado."
    if lead.owner_id != user.pk:
        return "Só quem assumiu este atendimento pode despachá-lo."
    if lead.desfecho:
        return "Este lead já foi concluído."
    if not lead.origem_manual and lead.etapa_atendimento not in {"negociacao", "despacho"}:
        return "Este lead ainda não está em Meus Atendimentos."
    Blacklist.objects.get_or_create(
        company=lead.company, contact=lead.contact,
        defaults={"motivo": motivo or "Despachado e bloqueado pelo atendente", "adicionado_por": user},
    )
    lead.desfecho = "bloqueado"
    lead.desfecho_pendente = ""
    lead.etapa_atendimento = ""
    lead.concluido_em = timezone.now()
    lead.next_action = ""
    lead.bot_closed = True
    lead.save(update_fields=["desfecho", "desfecho_pendente", "etapa_atendimento", "concluido_em", "next_action", "bot_closed"])
    return None

def contexto_agente(company):
    """Tudo que o agente precisa pra conduzir o roteiro da empresa, sem efeitos colaterais."""
    perguntas = []
    fora_do_fluxo = []
    areas = list(company.areas.order_by("name"))
    # Uma chave por área cadastrada, mesmo sem perguntas: o agente sabe que a área existe mas não tem SPIN.
    spin = {a.name: [] for a in areas}
    nomes_area = {a.id: a.name for a in areas}
    for q in Question.objects.filter(company=company).select_related("variavel", "variavel_roteiro").order_by("ordem", "id"):
        if not (q.text or "").strip():
            continue
        if q.question_id == "lembrete":
            continue  # mensagem proativa do CRM (reservar_lembretes): o agente não a envia nem a conhece
        if q.question_id in MANDATORY_OFFFLOW_QUESTION_IDS:
            if not texto_fora_habilitado(company, q.question_id):
                continue
            item = {"question_id": q.question_id, "texto": q.text}
            if q.question_id == "necessidade_humana":
                item["variaveis_obrigatorias"] = list(q.variaveis_obrigatorias.values_list("slug", flat=True))
            fora_do_fluxo.append(item)
            continue
        item = {
            "question_id": q.question_id,
            "ordem": q.ordem,
            "texto": q.text,
            "obrigatoria": q.obrigatoria,
            "envio_obrigatorio": q.envio_obrigatorio,
            "variavel": {"nome": q.variavel.name, "peso": q.variavel.peso} if q.variavel else None,
            "variavel_roteiro": q.variavel_roteiro.slug if q.variavel_roteiro else None,
        }
        if q.area_id:
            spin[nomes_area[q.area_id]].append({**item, "etapa_spin": q.etapa_spin})
        else:
            perguntas.append(item)
    spins_iniciais = []
    if company.etapa_inicial:
        habilitadas = spins_iniciais_habilitadas(company)
        perguntas = []
        spin_filtrada = {}
        for area in habilitadas:
            ordenadas = [q.question_id for q in perguntas_da_spin(company, area)]
            spin_filtrada[area.name] = sorted((q for q in spin.get(area.name, []) if q["question_id"] in ordenadas), key=lambda q: ordenadas.index(q["question_id"]))
            spins_iniciais.append({"area": area.name, "palavras_chave": palavras_chave_da_area(area), "pergunta_inicial": ordenadas[0] if ordenadas else None})
        spin = spin_filtrada
    return {
        "empresa": company.name,
        "agente_conversacional": company.agente_conversacional,
        # Com a coleta de histórico ligada, a ponte envia o texto/transcrição do cliente em cada /incoming/.
        "coletar_historico": company.coletar_historico_conversa,
        "etapa_inicial": company.etapa_inicial,
        "atendimento_humano_habilitado": not company.etapa_inicial,
        "classificacao_antecipada": {"campos": ["nome", "tema", "especialidade"], "nome_perfil_permitido": True},
        # SPIN única (comportamento clássico) ou None com várias: aí vale spins_iniciais (o agente escolhe).
        "spin_inicial": getattr(spin_efetiva(company), "name", None),
        "spins_iniciais": spins_iniciais if len(spins_iniciais) > 1 else [],
        "pergunta_inicial": pergunta_inicial(company),
        "validar_habilitado": texto_fora_habilitado(company, "validar"),
        "variaveis_roteiro": list(company.variaveis_roteiro.values("slug", "name", "builtin")),
        "mensagens_audio": company.audio_ativo,
        "numero_agente": company.numero_agente,
        "areas": [a.name for a in areas],
        "conversa_livre": {
            "ativa": conversa_livre_ativa(company),
            "maximo_respostas": MAX_RESPOSTAS_LIVRES,
            "dados_empresa": [{"titulo": e.title, "conteudo": e.content} for e in company.info_entries.all() if e.content.strip()] if conversa_livre_ativa(company) else [],
        },
        "perguntas": perguntas,
        "spin": spin,
        "fora_do_fluxo": fora_do_fluxo,
        "situacoes_especiais": [
            {"valor": k, "descricao": v["descricao"]} for k, v in SITUACOES_ESPECIAIS.items()
        ],
        "faixas_urgencia": [
            {"min": minimo, "max_exclusivo": maximo, "temperatura": temperatura}
            for minimo, maximo, temperatura in faixas_da_empresa(company)
        ],
        # Critério em texto da empresa para o agente dar as notas ("" = sem regra); o CRM calcula a classificação.
        "regra_classificacao": (company.classificacao_regra or "").strip(),
    }

def _categoria_status(lead):
    """Categoria exclusiva (cada lead cai em exatamente uma) usada no donut/tiles do Dashboard:
    especial (Outras situações), desqualificado, despachado, automatico (em triagem), aguardando
    (Qualificados + Atendimentos em espera = a fila de Pendências, "Triagem concluída") e equipe
    (Em negociação, Despacho e cadastros manuais dos atendentes)."""
    if lead.get("situacao_especial") and not lead["desfecho"]:
        return "especial"  # Outras situações em aberto; depois do despacho conta como despachado
    if lead["desfecho"] == "desqualificado":
        return "desqualificado"
    if lead["desfecho"]:
        return "despachado"
    if not lead["bot_closed"] and lead["mode"] != "HUMANO":
        return "automatico"
    if lead["bot_closed"] and lead["mode"] != "HUMANO" and lead["temperature"] in FORA_DO_KANBAN:
        return "desqualificado"
    if not lead["origem_manual"] and lead["etapa_atendimento"] in ("", "espera"):
        return "aguardando"
    return "equipe"

MOTIVOS_DESQUALIFICACAO = {
    "fora_de_escopo": "Fora de escopo",
    "sem_resposta": "Sem resposta após 3 repetições da mesma pergunta",
}

def motivo_da_desqualificacao(lead):
    """Texto do motivo de um lead desqualificado (vazio para os demais), para o popup do Dashboard."""
    if _categoria_status(lead) != "desqualificado":
        return ""
    detalhe = lead.get("urgencia_detalhe") or {}
    if detalhe.get("motivo") in MOTIVOS_DESQUALIFICACAO:
        return MOTIVOS_DESQUALIFICACAO[detalhe["motivo"]]
    if lead.get("temperature") in FORA_DO_KANBAN:
        media = f" (média {detalhe['score']})" if detalhe.get("score") is not None else ""
        return f"Classificado como {lead['temperature']}{media}"
    return "Desqualificado pelo agente"

def _triagem_concluida_dashboard(lead):
    """Triagem concluída = leads que aguardam a equipe (colunas Qualificados e Em espera)."""
    return _categoria_status(lead) == "aguardando"

def resumo_dashboard(company, dias=None, area="", busca="", data_inicio=None, data_fim=None):
    """Agregados do Dashboard calculados no servidor sobre TODOS os leads da
    empresa (o frontend antes contava só a 1ª página paginada de /leads/, então
    leads antigos -- justamente os já despachados -- sumiam das contas)."""
    from django.db.models import Q
    qs = Lead.objects.filter(company=company)
    if data_inicio and data_fim:
        tz = timezone.get_current_timezone()
        qs = qs.filter(
            created_at__gte=timezone.make_aware(datetime.combine(data_inicio, time.min), tz),
            created_at__lte=timezone.make_aware(datetime.combine(data_fim, time.max), tz),
        )
    elif dias:
        qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=dias))
    if area:
        qs = qs.filter(especialidade=area)
    if busca:
        qs = qs.filter(
            Q(name__icontains=busca) | Q(contact__icontains=busca) | Q(owner__username__icontains=busca)
            | Q(owner__first_name__icontains=busca) | Q(owner__profile__display_name__icontains=busca)
        )
    # Contadores que sobrevivem à exclusão dos leads (novas leads e "não prosseguiram", do Celery).
    # Não dá para filtrar por área/busca (o lead apagado não existe mais): nesses casos ficam nulos.
    contagens = ContagemDiaria.objects.filter(company=company)
    hoje = timezone.localdate()
    if data_inicio and data_fim:
        contagens = contagens.filter(data__gte=data_inicio, data__lte=data_fim)
    elif dias:
        contagens = contagens.filter(data__gte=timezone.localdate(timezone.now() - timedelta(days=dias)))
    totais = contagens.aggregate(novas=Sum("novas"), nao=Sum("nao_prosseguiram"))
    novas_hoje = ContagemDiaria.objects.filter(company=company, data=hoje).aggregate(n=Sum("novas"))["n"] or 0
    sem_contagem = bool(area or busca)
    rows = list(qs.values(
        "id", "name", "contact", "created_at", "concluido_em", "desfecho", "bot_closed", "mode",
        "temperature", "priority", "especialidade", "owner", "origem_manual", "demand", "etapa_atendimento", "situacao_especial",
        "urgencia_detalhe",
    ))
    User = get_user_model()
    nomes = {u.pk: _nome_usuario(u) for u in User.objects.filter(pk__in={r["owner"] for r in rows if r["owner"]}).select_related("profile")}

    status = {"despachado": 0, "automatico": 0, "aguardando": 0, "equipe": 0, "desqualificado": 0, "especial": 0, "nao_prosseguiram": 0}
    desfechos = {"encerrado": 0, "comprometido": 0, "falha": 0, "bloqueado": 0}
    por_area, por_mes, por_owner = {}, {}, {}
    por_temperatura = {t: 0 for t in URGENCIA_RANK}
    tz = timezone.get_current_timezone()
    for r in rows:
        status[_categoria_status(r)] += 1
        if r["desfecho"] in desfechos:
            desfechos[r["desfecho"]] += 1
        chave_area = r["especialidade"] or "Sem especialidade"
        por_area[chave_area] = por_area.get(chave_area, 0) + 1
        mes = timezone.localtime(r["created_at"], tz).strftime("%Y-%m")
        por_mes[mes] = por_mes.get(mes, 0) + 1
        if r["temperature"] in por_temperatura:
            por_temperatura[r["temperature"]] += 1
        if r["owner"]:
            o = por_owner.setdefault(r["owner"], {"owner_id": r["owner"], "owner": nomes.get(r["owner"], ""), "atendimentos": 0, "concluidos": 0, "sucesso": 0})
            o["atendimentos"] += 1
            if r["desfecho"] in Lead.DESFECHO_CONCLUIDO:
                o["concluidos"] += 1
            if r["desfecho"] == DESFECHO_SUCESSO:
                o["sucesso"] += 1
    # Tendência por mês também conta as triagens que não prosseguiram (apagadas, no mês em que nasceram).
    if not sem_contagem:
        for dia, qtd in contagens.values_list("data", "nao_prosseguiram"):
            if qtd:
                chave = dia.strftime("%Y-%m")
                por_mes[chave] = por_mes.get(chave, 0) + qtd

    # Triagens abandonadas que o Celery apagou: não existem mais como lead, mas fazem parte do total.
    nao_prosseguiram = 0 if sem_contagem else (totais["nao"] or 0)
    status["nao_prosseguiram"] = nao_prosseguiram
    # Despachados pela equipe (encerrado/comprometido/falha), mais recentes primeiro --
    # mesmos filtros de período/área/busca de todo o resto do resumo.
    concluidos = sorted(
        (r for r in rows if r["desfecho"] in Lead.DESFECHO_CONCLUIDO),
        key=lambda r: r["concluido_em"] or r["created_at"], reverse=True,
    )
    return {
        # Total = leads existentes (em triagem, com a equipe, despachados, desqualificados e
        # outras situações) + os que não prosseguiram. "Triagem concluída" é um recorte dos existentes.
        "total": len(rows) + nao_prosseguiram,
        "novas_leads": None if sem_contagem else (totais["novas"] or 0),
        "nao_prosseguiram": None if sem_contagem else (totais["nao"] or 0),
        "novas_hoje": novas_hoje,
        # Cadastro manual nunca passou por triagem (bot_closed=True só pra silenciar o agente).
        "triagem_concluida": sum(1 for r in rows if _triagem_concluida_dashboard(r)),
        # Mesmo critério da fatia "desqualificado" do status -- o tile e o donut sempre batem.
        "desqualificados": status["desqualificado"],
        "status": status,
        "desfechos": desfechos,
        "sucesso": desfechos[DESFECHO_SUCESSO],
        "atendimentos": [
            {
                "id": str(r["id"]), "name": r["name"], "contact": r["contact"],
                "demand": r["demand"], "especialidade": r["especialidade"],
                "temperature": r["temperature"], "priority": r["priority"],
                "owner": nomes.get(r["owner"], ""), "created_at": r["created_at"],
                "desfecho": r["desfecho"], "origem_manual": r["origem_manual"],
                "categoria_status": _categoria_status(r),
                "triagem_concluida": _triagem_concluida_dashboard(r),
                "motivo_desqualificacao": motivo_da_desqualificacao(r),
            }
            for r in sorted(rows, key=lambda r: (r["created_at"], str(r["id"])), reverse=True)
        ],
        "concluidos": [
            {
                "id": str(r["id"]), "name": r["name"], "contact": r["contact"],
                "temperature": r["temperature"], "priority": r["priority"], "especialidade": r["especialidade"],
                "desfecho": r["desfecho"], "owner_id": r["owner"], "owner": nomes.get(r["owner"], ""),
                "concluido_em": r["concluido_em"], "created_at": r["created_at"], "origem_manual": r["origem_manual"],
            }
            for r in concluidos
        ],
        "por_area": sorted(por_area.items(), key=lambda kv: -kv[1]),
        "por_mes": sorted(por_mes.items()),
        # Leads classificadas por temperatura (Desqualificado ... Quente) no recorte do Dashboard.
        "por_temperatura": por_temperatura,
        "por_owner": sorted(por_owner.values(), key=lambda o: -o["atendimentos"]),
    }


# --- Identidade visual da empresa (nome, logo e gradiente da barra lateral) ---
MARCA_LOGO_MAX_BYTES = 2 * 1024 * 1024
MARCA_LOGO_LADO = 256
_COR_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

def _logo_da_marca(arquivo):
    """Valida e normaliza o logo (PNG/JPEG/WEBP até 2 MB, no máximo 256 px). Devolve (ContentFile, erro)."""
    from io import BytesIO
    from django.core.files.base import ContentFile
    from PIL import Image, UnidentifiedImageError
    if arquivo.size > MARCA_LOGO_MAX_BYTES:
        return None, "Logo muito grande (máximo 2MB)."
    try:
        imagem = Image.open(arquivo)
        formato = imagem.format
        imagem.load()
    except (UnidentifiedImageError, OSError, ValueError):
        return None, "Imagem inválida. Use PNG, JPEG ou WEBP."
    if formato not in {"PNG", "JPEG", "WEBP"}:
        return None, "Formato não suportado. Use PNG, JPEG ou WEBP."
    imagem = imagem.convert("RGBA")
    imagem.thumbnail((MARCA_LOGO_LADO, MARCA_LOGO_LADO))
    saida = BytesIO()
    imagem.save(saida, "PNG")
    return ContentFile(saida.getvalue()), None

@transaction.atomic
def atualizar_identidade_visual(company, dados, logo=None):
    """Grava a identidade visual da empresa. As duas cores (#RRGGBB) vêm juntas ou ficam vazias (padrão
    Conecta); nome vazio = "Conecta". Retorna uma mensagem de erro (str) ou None."""
    company = Company.objects.select_for_update().get(pk=company.pk)
    if str(dados.get("restaurar") or "") in ("1", "true", "True"):
        if company.marca_logo:
            company.marca_logo.delete(save=False)
        company.marca_nome, company.marca_cor_principal, company.marca_cor_contraste = "", "", ""
        company.save(update_fields=["marca_nome", "marca_logo", "marca_cor_principal", "marca_cor_contraste"])
        return None
    nome = re.sub(r"\s+", " ", str(dados.get("nome") or "")).strip()
    if len(nome) > 30:
        return "O nome pode ter no máximo 30 caracteres."
    principal = str(dados.get("cor_principal") or "").strip().lower()
    contraste = str(dados.get("cor_contraste") or "").strip().lower()
    if bool(principal) != bool(contraste):
        return "Selecione as duas cores (principal e de contraste) para formar o gradiente."
    for cor in (principal, contraste):
        if cor and not _COR_HEX.match(cor):
            return "Cor inválida. Use o formato #RRGGBB."
    novo_logo = None
    if logo is not None:
        novo_logo, erro = _logo_da_marca(logo)
        if erro:
            return erro
    if novo_logo is not None or str(dados.get("remover_logo") or "") in ("1", "true", "True"):
        if company.marca_logo:
            company.marca_logo.delete(save=False)
        if novo_logo is not None:
            company.marca_logo.save(f"{company.pk}.png", novo_logo, save=False)
    company.marca_nome, company.marca_cor_principal, company.marca_cor_contraste = nome, principal, contraste
    company.save(update_fields=["marca_nome", "marca_logo", "marca_cor_principal", "marca_cor_contraste"])
    return None
