from rest_framework import serializers
from .models import Company, Lead, Step, Event
class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ["id", "name", "initial_state", "output_channel", "allow_transcription", "default_owner"]
class LeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = "__all__"
        read_only_fields = ["id", "company", "contact", "created_at", "state", "output_channel", "last_audio_id", "bot_closed", "last_contact"]
    def validate(self, attrs):
        if attrs.get("mode") == "AUTOMÁTICO" and self.instance and self.instance.mode == "HUMANO":
            raise serializers.ValidationError("Retomada exige comando administrativo autorizado; indisponível nesta versão.")
        return attrs
class StepSerializer(serializers.ModelSerializer):
    class Meta:
        model = Step
        fields = "__all__"
        read_only_fields = ["company"]
    def validate_accepted_answers(self, value):
        if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
            raise serializers.ValidationError("Informe uma lista de respostas textuais aprovadas.")
        return value
class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ["id", "message_id", "created_at", "summary", "delivery"]
class IncomingSerializer(serializers.Serializer):
    contact = serializers.RegexField(r"^\+[1-9]\d{7,14}$")
    message_id = serializers.CharField(max_length=160)
    answer = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    kind = serializers.ChoiceField(choices=["text", "audio"], default="text")
    human_required = serializers.BooleanField(default=False)
    reason = serializers.ChoiceField(choices=["pedido humano", "urgência ou risco", "fora de escopo", "decisão profissional", "falha de integração"], required=False, default="pedido humano")

class DeliverySerializer(serializers.Serializer):
    event_id = serializers.IntegerField(min_value=1)
    status = serializers.ChoiceField(choices=["SENT", "FAILED"])
