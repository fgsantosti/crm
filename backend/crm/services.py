import logging
import re
import secrets
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.authtoken.models import Token
from .emails import send_credentials_email, send_invite_email, send_email_change_code, send_password_reset_by_admin_email
from .models import Lead, Question, Event, Company, Blacklist, Area, AtendenteInvite, PasswordChangeRequired, EmailChangeRequest, AgentTokenExpiry, Variavel, VariavelRoteiro, CompanyInfo, MANDATORY_QUESTION_IDS, MANDATORY_OFFFLOW_QUESTION_IDS

logger = logging.getLogger(__name__)

NO_REPLY = {"action": "NO_REPLY"}
RESERVED_QUESTION_IDS = {"validar", "encerramento"}

# question_id -> (nome de exibição, slug/placeholder fixo) das 3 Variáveis de roteiro
# builtin: reaproveitam os placeholders já existentes (FIELD_MAP), sem precisar de
# armazenamento extra em Lead.variaveis_roteiro.
BUILTIN_VARIAVEL_ROTEIRO = {
    "nome": ("Nome", "nome"),
    "situacao": ("Área da Lead", "especialidade"),
    "demanda": ("Demanda", "tema"),
}

def seed_roteiro_padrao(company):
    """Garante o mínimo pra uma empresa nova conseguir operar o funil: a Variavel
    padrão, as 3 perguntas obrigatórias de triagem (nome/situacao/demanda) já
    atreladas às suas Variáveis de roteiro builtin, os 4 textos fora do fluxo
    (apresentacao/empresa/validar/encerramento) e os 3 campos obrigatórios de Dados
    da empresa. Chamado na criação de empresa (AdminCompanyViewSet) e pela migração
    0012/0014 pras empresas que já existiam antes dessas features."""
    variavel, _ = Variavel.objects.get_or_create(company=company, name="Geral", defaults={"peso": 5})
    for ordem, question_id in enumerate(MANDATORY_QUESTION_IDS):
        label, slug = BUILTIN_VARIAVEL_ROTEIRO[question_id]
        vr, _ = VariavelRoteiro.objects.get_or_create(company=company, slug=slug, defaults={"name": label, "builtin": True})
        Question.objects.get_or_create(company=company, question_id=question_id, defaults={"obrigatoria": True, "variavel": variavel, "ordem": ordem, "variavel_roteiro": vr})
    for question_id in MANDATORY_OFFFLOW_QUESTION_IDS:
        Question.objects.get_or_create(company=company, question_id=question_id, defaults={"obrigatoria": True, "variavel": None})
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
    lead.mode = "HUMANO"
    lead.priority = "Alta"
    lead.next_action = reason
    if reason == "pedido humano":
        motivo = "Cliente pediu contato direto com atendente humano"
        if motivo not in lead.demand:
            demanda = lead.demand.strip()
            lead.demand = f"{demanda[:300 - len(motivo) - 3]} | {motivo}" if demanda else motivo
    lead.save()

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

MAX_REPETICOES = 3
JANELA_ENTREGA_PENDENTE = timedelta(seconds=90)

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
        "ultima_pergunta": ultima_pergunta(lead) if lead and motivo == "em_triagem" else None,
        "repeticoes": contar_repeticoes(lead) if lead and motivo == "em_triagem" else 0,
        # Área já classificada no lead ativo: define qual lista SPIN o agente segue.
        "especialidade": (lead.especialidade or "") if lead and not lead.desfecho else "",
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
        lead = Lead.objects.create(company=company, contact=data["contact"], state=company.initial_state)
    previous = Event.objects.filter(lead=lead, message_id=data["message_id"]).first()
    if previous:
        return {**NO_REPLY, "duplicate": True, "lead_id": str(lead.pk), "lead_novo": False}
    lead.last_contact = timezone.now()
    lead.save()
    event = Event.objects.create(
        lead=lead, message_id=data["message_id"], marker=data["marker"],
        summary=f"Marcador recebido: {data['marker']}",
    )
    result = dict(NO_REPLY)
    # Triagem que não pode continuar (travada ou erro do agente) nunca vai pra equipe:
    # o lead é apagado e o número recomeça do zero na próxima mensagem.
    apagar_lead, motivo_apagar = False, ""
    pendentes = Event.objects.filter(lead=lead, delivery="PENDING").exclude(pk=event.pk)

    if not aceita:
        pass
    elif data["human_required"] and data["reason"] == "fora de escopo":
        desqualificar_fora_de_escopo(lead)
    elif data["human_required"] and data["reason"] == "falha de integração":
        apagar_lead, motivo_apagar = True, "Agente sinalizou falha de integração"
    elif data["human_required"]:
        escalate(lead, data["reason"])
        event.summary = f"Encaminhado para atendimento humano: {data['reason']}"
    elif pendentes.filter(created_at__gte=timezone.now() - JANELA_ENTREGA_PENDENTE).exists():
        # Contato mandou várias mensagens em sequência enquanto a resposta anterior ainda
        # está saindo: ignora esta sem escalar (escalar aqui travava o lead em HUMANO).
        event.summary = "Mensagem em sequência: entrega anterior ainda pendente"
    else:
        # Pendência antiga (90s+): a confirmação se perdeu; não deixa ela travar a triagem.
        pendentes.update(delivery="EXPIRADO")
        marker = data["marker"]
        fields = data.get("fields") or {}
        if lead_novo and not (marker == "Q" and data["question_id"] == company.initial_state):
            # Lead novo sempre começa pela apresentação, mesmo que o agente (ex.: sessão antiga
            # que "lembra" de uma triagem já apagada) mande outro marcador.
            event.summary = f"Lead novo: começando pela apresentação (marcador {marker} ignorado)"
            marker, fields = "Q", {}
            event.marker = "Q"
            data = {**data, "question_id": company.initial_state}
        if marker in {"ATUALIZAR", "VALIDAR", "CLASSIFICADO"} and _eh_fora_de_escopo(fields.get("especialidade") or lead.especialidade):
            # Fora de escopo não precisa concluir nem validar o roteiro e nunca recebe
            # a urgência comercial enviada pelo agente.
            apply_fields(lead, company, fields)
            desqualificar_fora_de_escopo(lead)
            question_id = None
        elif marker == "Q":
            question_id = data["question_id"]
            if not question_id:
                apagar_lead, motivo_apagar = True, "Marcador Q sem question_id: revisar integração do agente"
                question_id = None
            elif _spin_fora_da_area(company, lead, question_id):
                apagar_lead, motivo_apagar = True, "Pergunta SPIN de área diferente da classificada"
                question_id = None
            else:
                lead.state = question_id
        elif marker == "REPETIR":
            if contar_repeticoes(lead, excluir_pk=event.pk) >= MAX_REPETICOES:
                # Último recurso (a ponte avança antes disso): triagem travada não vai pra equipe,
                # o lead é apagado e o número recomeça do zero na próxima mensagem.
                apagar_lead, motivo_apagar = True, "Triagem travada: 3 repetições sem resposta"
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
                    apagar_lead, motivo_apagar = True, f"'{question_id}' é reservado (validar/encerramento não são 'proxima' válidos): revisar fluxo do agente"
                    question_id = None
                elif _spin_fora_da_area(company, lead, question_id):
                    # apply_fields já rodou: uma especialidade enviada neste mesmo ATUALIZAR vale.
                    apagar_lead, motivo_apagar = True, "Pergunta SPIN de área diferente da classificada"
                    question_id = None
                elif question_id == lead.state:
                    # Avançar para a mesma pergunta é uma repetição disfarçada: conta no mesmo limite.
                    event.marker = "REPETIR"
                    if contar_repeticoes(lead, excluir_pk=event.pk) >= MAX_REPETICOES:
                        apagar_lead, motivo_apagar = True, "Triagem travada: 3 repetições sem resposta"
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
                question_id = "validar"
                lead.state = "VALIDANDO"
        elif marker == "CLASSIFICADO":
            antecipado = bool(fields.get("encerramento_antecipado"))
            if antecipado:
                apagar_lead, motivo_apagar = True, "Triagem abandonada antes de concluir o roteiro"
                question_id = None
            elif lead.state != "VALIDANDO":
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
                    lead.bot_closed = True
                    lead.state = "ENCERRADO_CLASSIFICADO"
                    lead.funnel_stage = "Triagem concluída"
                    lead.next_action = "Revisar classificação e dar continuidade humana"
                    question_id = "encerramento"
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
            if not question:
                # Erro de configuração da empresa (não do agente): fica visível pra empresa corrigir.
                escalate(lead, f"Configurar roteiro aprovado para question_id={question_id}")
            else:
                # Áudio (gravação/TTS) é aplicado depois, fora da transação: ver aplicar_audio().
                asset = render_text(question.text, lead, company)
                if not asset:
                    escalate(lead, "Configurar texto aprovado (vazio) no Roteiro")
                else:
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
        if question and question.audio_gravado:
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

def agent_status(company):
    """Estado atual do token do agente desta empresa, pra tela Admin e pro
    serializer (nunca devolve a chave inteira, só uma prévia mascarada)."""
    User = get_user_model()
    username = _agent_username(company)
    user = User.objects.filter(username=username).first()
    if not user:
        return {"existe": False, "username": username, "masked_key": None, "validade": None}
    token = Token.objects.filter(user=user).first()
    if not token:
        return {"existe": True, "username": username, "masked_key": None, "validade": None}
    expiry = getattr(token, "expiry", None)
    validade = None
    if expiry:
        validade = {"expires_at": expiry.expires_at, "expirado": expiry.expires_at < timezone.now()}
    return {"existe": True, "username": username, "masked_key": f"{token.key[:8]}…{token.key[-4:]}", "validade": validade}

@transaction.atomic
def gerar_token_agente(company, dias_validade):
    """Cria a conta de serviço do agente se ainda não existir, e sempre
    GERA UM TOKEN NOVO (rotação: qualquer token antigo dessa empresa para de
    funcionar na hora). A chave completa só é devolvida aqui -- depois disso
    só a versão mascarada (agent_status) fica disponível, igual ao Django Admin."""
    User = get_user_model()
    agent_group, _ = Group.objects.get_or_create(name="agente")
    username = _agent_username(company)
    user, created = User.objects.get_or_create(username=username)
    if created:
        user.set_unusable_password()
        user.save()
    user.groups.add(agent_group)
    company.members.add(user)
    Token.objects.filter(user=user).delete()
    token = Token.objects.create(user=user)
    expires_at = timezone.now() + timedelta(days=dias_validade)
    AgentTokenExpiry.objects.create(token=token, expires_at=expires_at)
    return {"username": username, "token": token.key, "expires_at": expires_at}

def revogar_token_agente(company):
    User = get_user_model()
    user = User.objects.filter(username=_agent_username(company)).first()
    if user:
        Token.objects.filter(user=user).delete()

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
    (5, 7, "Remarketing"),
    (7, 9, "Qualificado"),
    (9, None, "Quente"),
]
URGENCIA_RANK = {temp: i for i, (_, _, temp) in enumerate(FAIXAS_URGENCIA)}
PRIORIDADE_POR_TEMPERATURA = {"Quente": "Alta", "Qualificado": "Média"}

# O agente manda TODOS os leads pro CRM, até os desqualificados/desconfiados
# -- mas esses dois nunca entram no fluxo operacional do Kanban nem podem ser
# assumidos por atendente, só contam nas estatísticas do dashboard.
FORA_DO_KANBAN = {"Desqualificado", "Desconfiado"}
PODE_ASSUMIR_A_PARTIR_DE = "Remarketing"
# "Concluído com sucesso" = desfecho Encerrado (o cliente conseguiu o que queria);
# Comprometido e Falha também são conclusões, mas não de sucesso.
DESFECHO_SUCESSO = "encerrado"

def calcular_urgencia(notas, pesos):
    """score = Σ(nota × peso) / Σ(peso), só sobre os question_id que têm peso.
    Retorna (score, temperatura) ou None se nenhuma nota tiver peso conhecido."""
    usados = [(float(notas[qid]), pesos[qid]) for qid in notas if qid in pesos and pesos[qid]]
    if not usados:
        return None
    score = sum(nota * peso for nota, peso in usados) / sum(peso for _, peso in usados)
    for minimo, maximo_exclusivo, temperatura in FAIXAS_URGENCIA:
        if score >= minimo and (maximo_exclusivo is None or score < maximo_exclusivo):
            return score, temperatura
    return score, FAIXAS_URGENCIA[0][2]

def _aplicar_notas_urgencia(lead, company, fields):
    """CLASSIFICADO com fields.notas: o CRM calcula temperatura (prevalece sobre a do
    agente) e, se não vier, a prioridade; grava o detalhe pra auditoria. Retorna
    (fields_atualizados, erro_ou_None)."""
    notas = fields.get("notas") or {}
    if not notas:
        return fields, None
    pesos = dict(
        Question.objects.filter(company=company, question_id__in=list(notas), variavel__isnull=False)
        .values_list("question_id", "variavel__peso")
    )
    calculo = calcular_urgencia(notas, pesos)
    if calculo is None:
        return fields, "Notas de urgência sem nenhuma pergunta com variável/peso cadastrado: revisar integração do agente"
    score, temperatura = calculo
    fields = {**fields, "temperatura": temperatura}
    if not fields.get("prioridade"):
        fields["prioridade"] = PRIORIDADE_POR_TEMPERATURA.get(temperatura, "Baixa")
    usados = {qid: notas[qid] for qid in notas if qid in pesos}
    lead.urgencia_detalhe = {
        "notas": usados,
        "pesos": {qid: pesos[qid] for qid in usados},
        "score": round(score, 2),
        "temperatura_calculada": temperatura,
    }
    return fields, None

TRIAGEM_ABANDONADA_APOS = timedelta(hours=24)

def apagar_triagens_abandonadas(agora=None):
    """Triagem automática parada há 24h+ sem resposta do contato: o lead (e os eventos) são
    apagados -- triagem que não terminou nunca vai pra equipe; o número recomeça do zero.
    Idempotente. Retorna quantos leads foram apagados."""
    agora = agora or timezone.now()
    limite = agora - TRIAGEM_ABANDONADA_APOS
    leads = Lead.objects.filter(
        Q(last_contact__lt=limite) | Q(last_contact__isnull=True, created_at__lt=limite),
        desfecho="", bot_closed=False, origem_manual=False,
    ).exclude(mode="HUMANO")
    total = 0
    company_ids = list(leads.order_by().values_list("company_id", flat=True).distinct())
    for company_id in company_ids:
        with transaction.atomic():
            # receive usa o mesmo lock: reavalia a inatividade após qualquer entrada concorrente.
            if not Company.objects.select_for_update().filter(pk=company_id).first():
                continue
            _, por_modelo = leads.filter(company_id=company_id).delete()
            total += por_modelo.get("crm.Lead", 0)
    return total

def _eh_fora_de_escopo(especialidade):
    return (especialidade or "").strip().lower() == "fora de escopo"

def desqualificar_fora_de_escopo(lead):
    """Fora de escopo nunca chega a Qualificados nem fica com prioridade Alta: desqualifica na
    hora (fora do Kanban, conta nas estatísticas) e libera o número."""
    lead.temperature = "Desqualificado"
    lead.priority = "Baixa"
    lead.mode = "AUTOMÁTICO"
    lead.bot_closed = True
    lead.state = "ENCERRADO_CLASSIFICADO"
    lead.funnel_stage = "Triagem concluída"
    lead.next_action = "Fora de escopo"
    lead.desfecho = "desqualificado"
    lead.concluido_em = timezone.now()
    lead.urgencia_detalhe = {**(lead.urgencia_detalhe or {}), "motivo": "fora_de_escopo"}
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
        if q.question_id in MANDATORY_OFFFLOW_QUESTION_IDS:
            fora_do_fluxo.append({"question_id": q.question_id, "texto": q.text})
            continue
        item = {
            "question_id": q.question_id,
            "ordem": q.ordem,
            "texto": q.text,
            "obrigatoria": q.obrigatoria,
            "variavel": {"nome": q.variavel.name, "peso": q.variavel.peso} if q.variavel else None,
            "variavel_roteiro": q.variavel_roteiro.slug if q.variavel_roteiro else None,
        }
        if q.area_id:
            spin[nomes_area[q.area_id]].append({**item, "etapa_spin": q.etapa_spin})
        else:
            perguntas.append(item)
    return {
        "empresa": company.name,
        "agente_conversacional": company.agente_conversacional,
        "mensagens_audio": company.audio_ativo,
        "numero_agente": company.numero_agente,
        "areas": [a.name for a in areas],
        "perguntas": perguntas,
        "spin": spin,
        "fora_do_fluxo": fora_do_fluxo,
        "faixas_urgencia": [
            {"min": minimo, "max_exclusivo": maximo, "temperatura": temperatura}
            for minimo, maximo, temperatura in FAIXAS_URGENCIA
        ],
    }

def _categoria_status(lead):
    """Categoria exclusiva (cada lead cai em exatamente uma) usada no donut/tiles
    do Dashboard -- antes "Concluído" (bot_closed) e "Atendimento humano"
    (mode=HUMANO) se sobrepunham e a soma passava do total."""
    if lead["desfecho"] == "desqualificado":
        return "desqualificado"
    if lead["desfecho"]:
        return "despachado"
    if not lead["bot_closed"] and lead["mode"] != "HUMANO":
        return "automatico"
    if lead["bot_closed"] and lead["mode"] != "HUMANO" and lead["temperature"] in FORA_DO_KANBAN:
        return "desqualificado"
    return "equipe"

def resumo_dashboard(company, dias=None, area="", busca=""):
    """Agregados do Dashboard calculados no servidor sobre TODOS os leads da
    empresa (o frontend antes contava só a 1ª página paginada de /leads/, então
    leads antigos -- justamente os já despachados -- sumiam das contas)."""
    from django.db.models import Q
    qs = Lead.objects.filter(company=company)
    if dias:
        qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=dias))
    if area:
        qs = qs.filter(especialidade=area)
    if busca:
        qs = qs.filter(
            Q(name__icontains=busca) | Q(contact__icontains=busca) | Q(owner__username__icontains=busca)
            | Q(owner__first_name__icontains=busca) | Q(owner__profile__display_name__icontains=busca)
        )
    rows = list(qs.values(
        "id", "name", "contact", "created_at", "concluido_em", "desfecho", "bot_closed", "mode",
        "temperature", "priority", "especialidade", "owner", "origem_manual",
    ))
    User = get_user_model()
    nomes = {u.pk: _nome_usuario(u) for u in User.objects.filter(pk__in={r["owner"] for r in rows if r["owner"]}).select_related("profile")}

    status = {"despachado": 0, "automatico": 0, "equipe": 0, "desqualificado": 0}
    desfechos = {"encerrado": 0, "comprometido": 0, "falha": 0, "bloqueado": 0}
    por_area, por_mes, por_owner = {}, {}, {}
    tz = timezone.get_current_timezone()
    for r in rows:
        status[_categoria_status(r)] += 1
        if r["desfecho"] in desfechos:
            desfechos[r["desfecho"]] += 1
        chave_area = r["especialidade"] or "Sem especialidade"
        por_area[chave_area] = por_area.get(chave_area, 0) + 1
        mes = timezone.localtime(r["created_at"], tz).strftime("%Y-%m")
        por_mes[mes] = por_mes.get(mes, 0) + 1
        if r["owner"]:
            o = por_owner.setdefault(r["owner"], {"owner_id": r["owner"], "owner": nomes.get(r["owner"], ""), "atendimentos": 0, "concluidos": 0, "sucesso": 0})
            o["atendimentos"] += 1
            if r["desfecho"] in Lead.DESFECHO_CONCLUIDO:
                o["concluidos"] += 1
            if r["desfecho"] == DESFECHO_SUCESSO:
                o["sucesso"] += 1

    # Despachados pela equipe (encerrado/comprometido/falha), mais recentes primeiro --
    # mesmos filtros de período/área/busca de todo o resto do resumo.
    concluidos = sorted(
        (r for r in rows if r["desfecho"] in Lead.DESFECHO_CONCLUIDO),
        key=lambda r: r["concluido_em"] or r["created_at"], reverse=True,
    )
    return {
        "total": len(rows),
        # Cadastro manual nunca passou por triagem (bot_closed=True só pra silenciar o agente).
        "triagem_concluida": sum(1 for r in rows if r["bot_closed"] and not r["origem_manual"]),
        # Mesmo critério da fatia "desqualificado" do status -- o tile e o donut sempre batem.
        "desqualificados": status["desqualificado"],
        "status": status,
        "desfechos": desfechos,
        "sucesso": desfechos[DESFECHO_SUCESSO],
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
        "por_owner": sorted(por_owner.values(), key=lambda o: -o["atendimentos"]),
    }
