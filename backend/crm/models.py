import uuid
from django.conf import settings
from django.db import models

class Company(models.Model):
    name = models.CharField(max_length=160)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="companies")
    initial_state = models.CharField(max_length=80, default="apresentacao", help_text="question_id inicial enviado no primeiro contato.")
    allow_transcription = models.BooleanField(default=False)
    default_owner = models.CharField(max_length=120, blank=True)
    def __str__(self): return self.name

class Question(models.Model):
    """Conteúdo fixo aprovado para um question_id do agente Axioma.

    O agente decide sozinho qual é a próxima pergunta (via os marcadores
    Q/ATUALIZAR/VALIDAR/CLASSIFICADO); este modelo só resolve um question_id
    para o texto ou áudio aprovado que de fato é enviado ao contato.
    """
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    question_id = models.CharField(max_length=80, help_text="Ex.: apresentacao, empresa, nome, situacao, ainda_na_empresa, tipo_de_situacao, afetou_renda, equipe_avaliar_situacao, validar, encerramento, repetir.")
    text = models.TextField(blank=True)
    audio_asset = models.CharField(max_length=250, blank=True, help_text="Identificador do OGG/Opus pré-gravado, usado quando a entrada do contato for áudio.")
    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "question_id"], name="unique_company_question")]

class CompanyInfo(models.Model):
    """Entrada de 'Dados da empresa': título + texto que o agente pode consultar
    para responder perguntas livres sobre a empresa (horário, endereço, serviços,
    formas de pagamento etc.), fora do roteiro fixo de qualificação.
    """
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="info_entries")
    title = models.CharField(max_length=160)
    content = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["title"]

class Area(models.Model):
    """Área de atendimento cadastrada pela própria empresa (tela "Equipe").

    Substitui o antigo choices fixo e global de Lead.especialidade: cada
    empresa define suas próprias áreas, e o roteiro/agente só pode classificar
    um lead numa área que já exista para aquela empresa (validado em
    services.apply_fields).
    """
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="areas")
    name = models.CharField(max_length=80)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "name"], name="unique_company_area")]
        ordering = ["name"]
    def __str__(self): return self.name

class AtendenteInvite(models.Model):
    """Convite de um novo atendente, validado por código de 6 dígitos enviado por e-mail.

    O código nunca é armazenado em texto puro (code_hash via make_password).
    Ao validar, o convite cria a conta do atendente e dispara um segundo
    e-mail com e-mail/senha provisória (ver services.validar_convite).

    O id é UUID (não sequencial) porque ele vai na URL pública do link de
    validação enviado por e-mail -- um id incremental deixaria convites de
    outras empresas adivinháveis só por tentativa.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="invites")
    name = models.CharField(max_length=160)
    email = models.EmailField()
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    verified_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ["-created_at"]

class PasswordChangeRequired(models.Model):
    """Presença de uma linha para um usuário força a troca de senha no próximo login.

    Criada quando um convite de atendente é validado (a senha provisória
    enviada por e-mail só deve valer até o primeiro acesso). Removida por
    services.trocar_senha ao definir a senha definitiva.
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="password_change_required")

class Profile(models.Model):
    """Dados de perfil que o User padrão do Django não tem (nome de exibição, foto).

    Criado sob demanda (get_or_create) em views.me -- contas antigas (admin,
    empresa.rufus-advocacia etc.) não têm uma linha aqui até o primeiro acesso
    à tela de perfil, e isso é esperado.
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=160, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True)

class EmailChangeRequest(models.Model):
    """Troca de e-mail da própria conta, confirmada por código de 6 dígitos
    enviado para o endereço NOVO (nunca o antigo) -- evita que uma sessão
    aberta troque o e-mail de contato da conta sem confirmar que quem está
    pedindo a troca realmente tem acesso à caixa nova."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_change_requests")
    new_email = models.EmailField()
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ["-created_at"]

class Lead(models.Model):
    ESPECIALIDADE_CHOICES = [("Previdenciário", "Previdenciário"), ("Consumidor", "Consumidor"), ("Trabalhista", "Trabalhista"), ("Fora de escopo", "Fora de escopo")]
    TEMPERATURA_CHOICES = [("Qualificado", "Qualificado"), ("Quente", "Quente"), ("Desconfiado", "Desconfiado"), ("Remarketing", "Remarketing"), ("Desqualificado", "Desqualificado")]
    INTERESSE_CHOICES = [("sim", "Sim"), ("nao", "Não"), ("depois", "Depois")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    name = models.CharField(max_length=160, blank=True)
    contact = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    funnel_stage = models.CharField(max_length=40, default="Novo lead")
    state = models.CharField(max_length=80, help_text="question_id atual (apresentacao, nome, situacao, ... ou ENCERRADO_CLASSIFICADO).")
    especialidade = models.CharField(max_length=80, blank=True, help_text="Nome de uma Area cadastrada pela empresa; validado em services.apply_fields, não é mais um choices fixo.")
    demand = models.CharField(max_length=300, blank=True, help_text="Campo 'tema' do protocolo Axioma.")
    impacto = models.CharField(max_length=300, blank=True)
    interesse = models.CharField(max_length=10, choices=INTERESSE_CHOICES, blank=True)
    temperature = models.CharField(max_length=20, choices=TEMPERATURA_CHOICES, blank=True)
    last_contact = models.DateTimeField(null=True, blank=True)
    next_action = models.CharField(max_length=250, blank=True)
    return_at = models.DateTimeField(null=True, blank=True)
    priority = models.CharField(max_length=10, choices=[("Alta", "Alta"), ("Média", "Média"), ("Baixa", "Baixa")], default="Média")
    owner = models.CharField(max_length=120, blank=True)
    mode = models.CharField(max_length=10, choices=[("AUTOMÁTICO", "Automático"), ("HUMANO", "Humano")], default="AUTOMÁTICO")
    last_audio_id = models.CharField(max_length=250, blank=True)
    bot_closed = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "contact"], name="unique_company_contact")]
        ordering = ["-created_at"]

class Event(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="events")
    message_id = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)
    summary = models.CharField(max_length=160)
    result = models.JSONField(default=dict)
    delivery = models.CharField(max_length=15, default="NOT_REQUIRED")
    class Meta:
        constraints = [models.UniqueConstraint(fields=["lead", "message_id"], name="unique_lead_message")]
        ordering = ["created_at"]
