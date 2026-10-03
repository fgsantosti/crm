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
    especialidade = models.CharField(max_length=20, choices=ESPECIALIDADE_CHOICES, blank=True)
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
