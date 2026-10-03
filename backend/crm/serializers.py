from django.utils import timezone
from rest_framework import serializers
from .models import Company, Lead, Question, CompanyInfo, Event, Area, AtendenteInvite

class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ["id", "name", "initial_state", "allow_transcription", "default_owner"]

class LeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = "__all__"
        read_only_fields = ["id", "company", "contact", "created_at", "state", "last_audio_id", "bot_closed", "last_contact"]

    def validate(self, attrs):
        if attrs.get("mode") == "AUTOMÁTICO" and self.instance and self.instance.mode == "HUMANO":
            raise serializers.ValidationError("Retomada exige comando administrativo autorizado; indisponível nesta versão.")
        return attrs

class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = "__all__"
        read_only_fields = ["company"]

class CompanyInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyInfo
        fields = "__all__"
        read_only_fields = ["company", "updated_at"]

class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ["id", "message_id", "created_at", "summary", "delivery"]

class AgentFieldsSerializer(serializers.Serializer):
    nome = serializers.CharField(max_length=160, required=False, allow_blank=True)
    # Antes era um ChoiceField fixo e global. Agora cada empresa cadastra suas
    # próprias áreas (tela "Equipe"), então a validação de que o valor é uma
    # área real da empresa acontece em services.apply_fields, não aqui.
    especialidade = serializers.CharField(max_length=80, required=False, allow_blank=True)
    tema = serializers.CharField(max_length=300, required=False, allow_blank=True)
    impacto = serializers.CharField(max_length=300, required=False, allow_blank=True)
    interesse = serializers.ChoiceField(choices=[c[0] for c in Lead.INTERESSE_CHOICES], required=False, allow_blank=True)
    temperatura = serializers.ChoiceField(choices=[c[0] for c in Lead.TEMPERATURA_CHOICES], required=False, allow_blank=True)
    prioridade = serializers.ChoiceField(choices=["Alta", "Média", "Baixa"], required=False, allow_blank=True)
    proxima = serializers.ChoiceField(
        choices=[
            "apresentacao",
            "empresa",
            "nome",
            "situacao",
            "ainda_na_empresa",
            "tipo_de_situacao",
            "afetou_renda",
            "equipe_avaliar_situacao",
        ],
        required=False,
        allow_blank=True,
    )

class IncomingSerializer(serializers.Serializer):
    contact = serializers.RegexField(r"^\+[1-9]\d{7,14}$")
    message_id = serializers.CharField(max_length=160)
    kind = serializers.ChoiceField(choices=["text", "audio"], default="text")
    marker = serializers.ChoiceField(choices=["Q", "REPETIR", "ATUALIZAR", "VALIDAR", "CLASSIFICADO"])
    question_id = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    fields = AgentFieldsSerializer(required=False, default=dict)
    human_required = serializers.BooleanField(default=False)
    reason = serializers.ChoiceField(choices=["pedido humano", "urgência ou risco", "fora de escopo", "decisão profissional", "falha de integração"], required=False, default="pedido humano")

    def validate(self, attrs):
        if attrs["marker"] == "CLASSIFICADO":
            fields = attrs.get("fields") or {}
            if not fields.get("temperatura") or not fields.get("prioridade"):
                raise serializers.ValidationError("fields.temperatura e fields.prioridade são obrigatórios quando marker=CLASSIFICADO.")
        return attrs

class DeliverySerializer(serializers.Serializer):
    event_id = serializers.IntegerField(min_value=1)
    status = serializers.ChoiceField(choices=["SENT", "FAILED"])

class AreaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Area
        fields = ["id", "name"]
        read_only_fields = ["id"]

class AtendenteInviteSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    class Meta:
        model = AtendenteInvite
        fields = ["id", "name", "email", "created_at", "expires_at", "verified_at", "attempts", "status"]
        read_only_fields = ["id", "created_at", "expires_at", "verified_at", "attempts", "status"]
    def get_status(self, obj):
        if obj.verified_at:
            return "verificado"
        if obj.expires_at < timezone.now():
            return "expirado"
        return "pendente"
