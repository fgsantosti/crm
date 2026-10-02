import uuid
from django.conf import settings
from django.db import models

class Company(models.Model):
    name = models.CharField(max_length=160)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="companies")
    initial_state = models.CharField(max_length=80, default="INICIAL")
    output_channel = models.CharField(max_length=20, choices=[("TEXTO", "Texto"), ("AUDIO_GRAVADO", "Áudio gravado")], default="TEXTO")
    allow_transcription = models.BooleanField(default=False)
    default_owner = models.CharField(max_length=120, blank=True)
    def __str__(self): return self.name

class Step(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    state = models.CharField(max_length=80)
    next_state = models.CharField(max_length=80)
    question_id = models.CharField(max_length=80)
    text = models.TextField(blank=True)
    audio_asset = models.CharField(max_length=250, blank=True)
    accepted_answers = models.JSONField(default=list, help_text="Respostas exatas aprovadas, normalizadas sem distinção de maiúsculas.")
    terminal = models.BooleanField(default=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "state"], name="unique_company_state")]

class Lead(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    name = models.CharField(max_length=160, blank=True)
    contact = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    funnel_stage = models.CharField(max_length=40, default="Novo lead")
    state = models.CharField(max_length=80)
    demand = models.CharField(max_length=300, blank=True)
    temperature = models.CharField(max_length=30, blank=True)
    last_contact = models.DateTimeField(null=True, blank=True)
    next_action = models.CharField(max_length=250, blank=True)
    return_at = models.DateTimeField(null=True, blank=True)
    priority = models.CharField(max_length=10, choices=[("Alta", "Alta"), ("Média", "Média"), ("Baixa", "Baixa")], default="Média")
    owner = models.CharField(max_length=120, blank=True)
    mode = models.CharField(max_length=10, choices=[("AUTOMÁTICO", "Automático"), ("HUMANO", "Humano")], default="AUTOMÁTICO")
    output_channel = models.CharField(max_length=20, choices=[("TEXTO", "Texto"), ("AUDIO_GRAVADO", "Áudio gravado")], default="TEXTO")
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
