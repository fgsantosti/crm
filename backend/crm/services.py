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
from .models import Lead, Question, Event, Company, Area, AtendenteInvite, PasswordChangeRequired, EmailChangeRequest, AgentTokenExpiry, Variavel, VariavelRoteiro, CompanyInfo, MANDATORY_QUESTION_IDS, MANDATORY_OFFFLOW_QUESTION_IDS

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

    `variaveis_roteiro` (opcional): dict slug->texto, só aceito pra slugs de
    Variáveis de roteiro CUSTOMIZADAS (não-builtin) já cadastradas pela empresa --
    nunca cria uma variável nova nem aceita um slug desconhecido/builtin (os
    builtin já são os campos fixos acima, nome/especialidade/tema).
    """
    especialidade = fields.get("especialidade")
    if especialidade and not company.areas.filter(name=especialidade).exists():
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

@transaction.atomic
def receive(company, data):
    # Serialize per company: protege a criação do primeiro contato e mensagens concorrentes.
    company = Company.objects.select_for_update().get(pk=company.pk)
    # Só busca/reaproveita um lead ATIVO (desfecho em aberto) pra esse contato -- se o único
    # lead existente já foi despachado, o número está livre: cria um lead novo do zero em vez
    # de reabrir o histórico antigo. O lock da empresa acima garante que nunca nascem dois.
    lead = Lead.objects.filter(company=company, contact=data["contact"], desfecho="").first()
    if not lead:
        # Desqualificado recém-encerrado: um "ok, obrigado" logo depois da mensagem de
        # encerramento não pode reabrir a triagem do zero -- fica mudo durante o cooldown.
        lead = Lead.objects.filter(
            company=company, contact=data["contact"], desfecho="desqualificado",
            concluido_em__gte=timezone.now() - COOLDOWN_DESQUALIFICADO,
        ).order_by("-concluido_em").first()
    if not lead:
        lead = Lead.objects.create(
            company=company, contact=data["contact"], state=company.initial_state,
            owner=resolver_usuario(company, company.default_owner),
        )
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
                elif question_id in RESERVED_QUESTION_IDS:
                    escalate(lead, f"'{question_id}' é reservado (validar/encerramento não são 'proxima' válidos): revisar fluxo do agente")
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
                    if lead.temperature in FORA_DO_KANBAN:
                        # Nunca entra no Kanban humano, então nunca seria despachado: fecha
                        # aqui, senão o número ficaria preso como "lead ativo" pra sempre.
                        lead.desfecho = "desqualificado"
                        lead.concluido_em = timezone.now()
                        lead.next_action = ""
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

def _nome_usuario(user):
    """Só pra EXIBIÇÃO -- nunca usar pra comparar dono de lead (isso é Lead.owner, FK)."""
    if user is None:
        return ""
    profile = getattr(user, "profile", None)
    return (profile.display_name if profile else "") or user.get_full_name() or user.username

def resolver_usuario(company, texto):
    """Texto livre (ex.: Company.default_owner) -> membro da empresa, por nome de
    exibição, nome completo, primeiro nome ou username. Só aceita match único."""
    texto = (texto or "").strip().lower()
    if not texto:
        return None
    candidatos = []
    for u in company.members.filter(is_active=True).exclude(groups__name="agente").select_related("profile"):
        profile = getattr(u, "profile", None)
        chaves = {(profile.display_name if profile else ""), u.get_full_name(), u.first_name, u.username}
        if texto in {c.strip().lower() for c in chaves if c}:
            candidatos.append(u)
    return candidatos[0] if len(candidatos) == 1 else None

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
    """Qualificados -> Atendimentos em espera: atendente reserva um lead
    classificado e ainda sem responsável (ainda não é negociação -- só
    'pendências'). select_for_update garante atomicidade na disputa entre
    atendentes clicando ao mesmo tempo."""
    lead = Lead.objects.select_for_update().filter(pk=lead_id).first()
    if not lead:
        return "Lead não encontrado."
    if lead.owner_id:
        return "Este atendimento já foi assumido por outro atendente."
    erro = _validar_lead_classificavel(lead)
    if erro:
        return erro
    lead.owner = user
    lead.etapa_atendimento = "espera"
    lead.save(update_fields=["owner", "etapa_atendimento"])
    return None

@transaction.atomic
def mover_para_negociacao(lead_id, user):
    """Qualificados OU Atendimentos em espera -> Em negociação. Se o lead ainda
    não tem owner (vindo direto de Qualificados), quem está movendo se torna
    owner agora -- é o botão 'Acompanhar' na tela de cadastro. Se já tem owner
    (vindo de Em espera), só esse mesmo owner pode mover."""
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
def preparar_despacho(lead_id, desfecho, user, auto_falha=False):
    """Qualificados, Em espera OU Em negociação -> Despacho: só RESERVA o
    desfecho (desfecho_pendente), não finaliza ainda -- isso só acontece em
    enviar_despachos (botão 'Enviar Despachos'). `auto_falha=True` é a
    transição direta Qualificados -> Despacho (sem nunca ter negociado):
    força 'falha', ignora o `desfecho` pedido."""
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
    lead.owner = user
    lead.etapa_atendimento = "despacho"
    lead.desfecho_pendente = desfecho_final
    lead.save(update_fields=["owner", "etapa_atendimento", "desfecho_pendente"])
    return None

@transaction.atomic
def liberar_lead(lead_id, user):
    """Qualquer coluna já assumida -> de volta pra Qualificados: solta o owner
    (que fica livre pra qualquer atendente reivindicar de novo). Só o próprio
    owner pode se soltar -- mesma regra simétrica de mover."""
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

# --- Variáveis do Agente: peso (1-10) de cada pergunta sugere urgência ---
# 10 níveis de peso / 5 classificações de Lead.TEMPERATURA_CHOICES = faixas
# de 2 pontos cada. Ordem aqui é da menos pra mais urgente (ajuste se a ordem
# de negócio real for outra -- não há essa ordenação registrada em nenhum
# outro lugar do sistema hoje, TEMPERATURA_CHOICES é só uma lista solta).
URGENCIA_POR_FAIXA = [
    (1, 2, "Desqualificado"),
    (3, 4, "Desconfiado"),
    (5, 6, "Remarketing"),
    (7, 8, "Qualificado"),
    (9, 10, "Quente"),
]
URGENCIA_RANK = {temp: i for i, (_, _, temp) in enumerate(URGENCIA_POR_FAIXA)}

# O agente manda TODOS os leads pro CRM, até os desqualificados/desconfiados
# -- mas esses dois nunca entram no fluxo operacional do Kanban nem podem ser
# assumidos por atendente, só contam nas estatísticas do dashboard.
FORA_DO_KANBAN = {"Desqualificado", "Desconfiado"}
PODE_ASSUMIR_A_PARTIR_DE = "Remarketing"
COOLDOWN_DESQUALIFICADO = timedelta(hours=24)

def calcular_urgencia_sugerida(pesos):
    """Sugestão auxiliar a partir da média dos pesos (1-10) das Variaveis das
    perguntas já respondidas pelo lead. NÃO substitui o agente: CLASSIFICADO
    continua sendo decidido por ele -- isso é só uma referência que pode
    alimentar a legenda do Roteiro ou uma futura tela de apoio à decisão."""
    if not pesos:
        return None
    media = sum(pesos) / len(pesos)
    for minimo, maximo, temperatura in URGENCIA_POR_FAIXA:
        if minimo <= media <= maximo:
            return temperatura
    return URGENCIA_POR_FAIXA[0][2] if media < 1 else URGENCIA_POR_FAIXA[-1][2]

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
    rows = list(qs.values("created_at", "desfecho", "bot_closed", "mode", "temperature", "especialidade", "owner"))
    User = get_user_model()
    nomes = {u.pk: _nome_usuario(u) for u in User.objects.filter(pk__in={r["owner"] for r in rows if r["owner"]}).select_related("profile")}

    status = {"despachado": 0, "automatico": 0, "equipe": 0, "desqualificado": 0}
    desfechos = {"encerrado": 0, "comprometido": 0, "falha": 0}
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
            o = por_owner.setdefault(r["owner"], {"owner_id": r["owner"], "owner": nomes.get(r["owner"], ""), "atendimentos": 0, "concluidos": 0})
            o["atendimentos"] += 1
            if r["desfecho"]:
                o["concluidos"] += 1

    return {
        "total": len(rows),
        "triagem_concluida": sum(1 for r in rows if r["bot_closed"]),
        "desqualificados": sum(1 for r in rows if r["temperature"] in FORA_DO_KANBAN),
        "status": status,
        "desfechos": desfechos,
        "por_area": sorted(por_area.items(), key=lambda kv: -kv[1]),
        "por_mes": sorted(por_mes.items()),
        "por_owner": sorted(por_owner.values(), key=lambda o: -o["atendimentos"]),
    }
