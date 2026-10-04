import re
import secrets
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.authtoken.models import Token
from .emails import send_credentials_email, send_invite_email, send_email_change_code, send_password_reset_by_admin_email
from .models import Lead, Question, Event, Company, Area, AtendenteInvite, PasswordChangeRequired, EmailChangeRequest, AgentTokenExpiry

NO_REPLY = {"action": "NO_REPLY"}

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

def escalate(lead, reason):
    lead.mode = "HUMANO"
    lead.priority = "Alta"
    lead.next_action = reason
    lead.save()

def apply_fields(lead, company, fields):
    """Grava os campos recebidos no lead; retorna uma mensagem de erro (str) se
    `especialidade` não for uma Area cadastrada para a empresa, ou None se ok.

    `especialidade` deixou de ser um choices fixo e global: agora é validada
    contra as áreas que a própria empresa cadastrou na tela "Equipe"
    (Area.objects.filter(company=...)). O agente nunca pode inventar uma área.
    """
    especialidade = fields.get("especialidade")
    if especialidade and not company.areas.filter(name=especialidade).exists():
        return f"Área desconhecida: '{especialidade}' não está cadastrada em Equipe"
    for key, model_field in FIELD_MAP.items():
        if key in fields and fields[key]:
            setattr(lead, model_field, fields[key])
    return None

PLACEHOLDER_RE = re.compile(r"\{(" + "|".join(re.escape(p) for p in ["empresa", *FIELD_MAP.keys()]) + r")\}")

def render_text(text, lead, company):
    """Substitui placeholders no texto aprovado pelos dados já coletados do lead e pela empresa.

    {empresa} vem de Company.name: o roteiro nunca precisa citar o nome da empresa
    na mão, e continua correto automaticamente se a empresa for renomeada ou se o
    mesmo texto for reaproveitado como modelo para uma empresa nova.
    {nome}, {especialidade}, {tema}... vêm dos dados já coletados do lead (usado
    sobretudo no texto aprovado de 'validar', que mostra um resumo para confirmação).
    Placeholder sem valor ainda vira string vazia, nunca quebra ou expõe '{campo}' literal.

    Todos os valores de substituição são resolvidos ANTES de rodar o regex, e a
    troca é feita em uma única passada sobre o texto original: um valor de campo
    (texto livre vindo do lead via o agente de IA) nunca é reprocessado como se
    fosse ele próprio um novo placeholder. Isso evita que um lead encadeie campos
    (ex.: nome="{tema}", tema="{impacto}", impacto="<texto arbitrário>") para fazer
    o backend reexpandir e enviar conteúdo que não é do roteiro aprovado da empresa.
    """
    values = {"empresa": company.name}
    for placeholder, model_field in FIELD_MAP.items():
        values[placeholder] = getattr(lead, model_field) or ""

    def substitute(match):
        return values[match.group(1)]

    return PLACEHOLDER_RE.sub(substitute, text)

@transaction.atomic
def receive(company, data):
    # Serialize per company: protege a criação do primeiro contato e mensagens concorrentes.
    company = Company.objects.select_for_update().get(pk=company.pk)
    lead, created = Lead.objects.get_or_create(company=company, contact=data["contact"], defaults={"state": company.initial_state, "owner": company.default_owner})
    previous = Event.objects.filter(lead=lead, message_id=data["message_id"]).first()
    if previous:
        return {**NO_REPLY, "duplicate": True, "lead_id": str(lead.pk)}
    lead.last_contact = timezone.now()
    lead.save()
    event = Event.objects.create(lead=lead, message_id=data["message_id"], summary=f"Marcador recebido: {data['marker']}")
    result = dict(NO_REPLY)

    if lead.mode == "HUMANO" or lead.bot_closed or lead.state == "ENCERRADO_CLASSIFICADO":
        pass
    elif data["human_required"]:
        escalate(lead, data["reason"])
    elif Event.objects.filter(lead=lead, delivery="PENDING").exclude(pk=event.pk).exists():
        escalate(lead, "Entrega anterior pendente: verificar integração")
    else:
        marker = data["marker"]
        fields = data.get("fields") or {}
        if marker == "Q":
            question_id = data["question_id"]
            if not question_id:
                escalate(lead, "Marcador Q sem question_id: revisar integração do agente")
                question_id = None
            else:
                lead.state = question_id
        elif marker == "REPETIR":
            question_id = lead.state
            event.summary = "Entrada ambígua ou fora do roteiro; repetindo pergunta atual"
        elif marker == "ATUALIZAR":
            field_error = apply_fields(lead, company, fields)
            if field_error:
                escalate(lead, field_error)
                question_id = None
            else:
                question_id = fields.get("proxima", "")
                if not question_id:
                    escalate(lead, "ATUALIZAR sem 'proxima': configurar roteiro aprovado")
                    question_id = None
                else:
                    lead.state = question_id
                    lead.funnel_stage = "Triagem"
        elif marker == "VALIDAR":
            field_error = apply_fields(lead, company, fields)
            if field_error:
                escalate(lead, field_error)
                question_id = None
            else:
                question_id = "validar"
                lead.state = "VALIDANDO"
        elif marker == "CLASSIFICADO":
            if lead.state != "VALIDANDO":
                escalate(lead, "CLASSIFICADO recebido sem VALIDAR anterior: revisar fluxo do agente")
                question_id = None
            else:
                field_error = apply_fields(lead, company, fields)
                if field_error:
                    escalate(lead, field_error)
                    question_id = None
                else:
                    lead.bot_closed = True
                    lead.state = "ENCERRADO_CLASSIFICADO"
                    lead.funnel_stage = "Triagem concluída"
                    lead.next_action = "Revisar classificação e dar continuidade humana"
                    question_id = "encerramento"
        else:
            escalate(lead, f"Marcador desconhecido: {marker}")
            question_id = None

        if question_id:
            question = Question.objects.filter(company=company, question_id=question_id).first()
            if not question:
                escalate(lead, f"Configurar roteiro aprovado para question_id={question_id}")
            else:
                use_audio = data["kind"] == "audio" and question.audio_asset
                asset = question.audio_asset if use_audio else render_text(question.text, lead, company)
                if not asset:
                    escalate(lead, "Ativo aprovado ausente")
                else:
                    if use_audio:
                        lead.last_audio_id = question.audio_asset
                    result = {"action": "AUDIO_GRAVADO" if use_audio else "TEXTO", "content": asset, "question_id": question_id}
                    event.delivery = "PENDING"
        lead.save()

    result.update({"lead_id": str(lead.pk), "event_id": event.pk})
    event.result = result
    event.save()
    return result

INVITE_TTL = timedelta(minutes=15)
MAX_INVITE_ATTEMPTS = 5

def create_invite(company, name, email):
    """Cria o convite, gera o código de 6 dígitos e dispara o e-mail com código + link.

    O código em si nunca é persistido em texto puro (code_hash via make_password,
    o mesmo hasher usado para senha) nem retornado pela API -- só vai no e-mail.
    """
    User = get_user_model()
    if User.objects.filter(username=email).exists():
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
    if User.objects.filter(email=new_email).exclude(pk=user.pk).exists():
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
    if User.objects.filter(email=request.new_email).exclude(pk=user.pk).exists():
        request.save(update_fields=["attempts"])
        return {"ok": False, "detail": "Já existe uma conta usando este e-mail."}
    user.email = request.new_email
    user.save(update_fields=["email"])
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

# --- Ciclo de vida pós-triagem: assumir e despachar (kanban "Atendimentos em
# Espera" -> "Atendimento humano" -> encerrado/comprometido/falha) ---

@transaction.atomic
def assumir_lead(lead_id, user):
    """Um atendente 'pega' um lead classificado e ainda sem responsável.
    select_for_update garante que, se dois atendentes clicarem ao mesmo tempo,
    só um consegue -- corrige o gap de atomicidade identificado antes (owner
    deixou de ser um PATCH livre, só muda por aqui ou por despachar_lead)."""
    lead = Lead.objects.select_for_update().filter(pk=lead_id).first()
    if not lead:
        return "Lead não encontrado."
    if lead.owner:
        return "Este atendimento já foi assumido por outro atendente."
    profile = getattr(user, "profile", None)
    nome = (profile.display_name if profile else "") or user.get_full_name() or user.username
    lead.owner = nome
    lead.mode = "HUMANO"
    lead.save(update_fields=["owner", "mode"])
    return None

def despachar_lead(lead_id, desfecho, user):
    if desfecho not in dict(Lead.DESFECHO_CHOICES):
        return "Classificação de despacho inválida."
    lead = Lead.objects.filter(pk=lead_id).first()
    if not lead:
        return "Lead não encontrado."
    profile = getattr(user, "profile", None)
    nome = (profile.display_name if profile else "") or user.get_full_name() or user.username
    if lead.owner and lead.owner != nome:
        return "Só quem assumiu este atendimento pode despachá-lo."
    lead.desfecho = desfecho
    lead.next_action = ""
    lead.save(update_fields=["desfecho", "next_action"])
    return None
