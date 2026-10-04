from django.utils import timezone
from rest_framework import serializers
from .models import Company, Lead, Question, CompanyInfo, Event, Area, AtendenteInvite, Variavel, VariavelRoteiro, MANDATORY_OFFFLOW_QUESTION_IDS, MANDATORY_QUESTION_IDS

class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ["id", "name", "initial_state", "allow_transcription", "default_owner", "agente_conversacional"]
        # Só "agente_conversacional" é editável por aqui (tela Roteiro, aba "Opções
        # do Agente") -- os demais campos de Company continuam só pelo Django Admin.
        read_only_fields = ["id", "name", "initial_state", "allow_transcription", "default_owner"]

class AdminCompanySerializer(serializers.ModelSerializer):
    """Só para a tela interna da Axioma (IsSuperUser) -- cross-tenant de propósito."""
    member_count = serializers.SerializerMethodField()
    tem_agente_ativo = serializers.SerializerMethodField()
    class Meta:
        model = Company
        fields = ["id", "name", "initial_state", "allow_transcription", "default_owner", "member_count", "tem_agente_ativo"]
        read_only_fields = ["id", "member_count", "tem_agente_ativo"]
    def get_member_count(self, obj):
        return obj.members.exclude(groups__name="agente").count()
    def get_tem_agente_ativo(self, obj):
        from .services import agent_status
        status = agent_status(obj)
        if not status["masked_key"]:
            return False
        return not (status["validade"] and status["validade"]["expirado"])

class LeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = "__all__"
        # owner/mode só mudam via as actions assumir/despachar (services.py) --
        # nunca mais um PATCH livre de texto, pra garantir atomicidade real
        # na disputa por um lead entre atendentes.
        read_only_fields = ["id", "company", "contact", "created_at", "state", "last_audio_id", "bot_closed", "last_contact", "owner", "mode", "desfecho", "variaveis_roteiro", "etapa_atendimento", "desfecho_pendente", "origem_manual"]

    def validate(self, attrs):
        if attrs.get("mode") == "AUTOMÁTICO" and self.instance and self.instance.mode == "HUMANO":
            raise serializers.ValidationError("Retomada exige comando administrativo autorizado; indisponível nesta versão.")
        return attrs

class VariavelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Variavel
        fields = ["id", "name", "peso"]
        read_only_fields = ["id"]

class VariavelRoteiroSerializer(serializers.ModelSerializer):
    class Meta:
        model = VariavelRoteiro
        fields = ["id", "name", "slug", "cor", "builtin"]
        read_only_fields = ["id", "slug", "cor", "builtin"]

class QuestionSerializer(serializers.ModelSerializer):
    # Declarado explícito: variavel é null=True só pra migração não quebrar
    # perguntas antigas (ver crm/migrations/0009) e pros 4 textos fora do fluxo
    # (MANDATORY_OFFFLOW_QUESTION_IDS, que não são classificáveis), mas pra
    # qualquer pergunta de FLUXO a API continua exigindo -- sem isso o
    # ModelSerializer relaxa "required" sozinho pra qualquer campo com
    # null=True no modelo (ver validate() abaixo pra regra condicional real).
    variavel = serializers.PrimaryKeyRelatedField(queryset=Variavel.objects.all(), required=False, allow_null=True)
    variavel_roteiro = serializers.PrimaryKeyRelatedField(queryset=VariavelRoteiro.objects.all(), required=False, allow_null=True)
    class Meta:
        model = Question
        fields = "__all__"
        read_only_fields = ["company", "obrigatoria"]
    def validate_variavel(self, variavel):
        # "uma pergunta SEMPRE estará atrelada a uma variável" -- nunca aceita
        # variável de outra empresa (o FK sozinho não garante isolamento de tenant).
        company = self.context.get("company")
        if variavel and company and variavel.company_id != company.id:
            raise serializers.ValidationError("Variável não pertence a esta empresa.")
        return variavel
    def validate_variavel_roteiro(self, variavel_roteiro):
        company = self.context.get("company")
        if variavel_roteiro and company and variavel_roteiro.company_id != company.id:
            raise serializers.ValidationError("Variável de roteiro não pertence a esta empresa.")
        return variavel_roteiro
    def validate(self, attrs):
        question_id = attrs.get("question_id") or (self.instance.question_id if self.instance else "")
        is_offflow = question_id in MANDATORY_OFFFLOW_QUESTION_IDS
        variavel = attrs.get("variavel", self.instance.variavel if self.instance else None)
        if not is_offflow and not variavel:
            raise serializers.ValidationError({"variavel": "Toda pergunta do fluxo precisa de uma variável vinculada."})
        if is_offflow and variavel:
            raise serializers.ValidationError({"variavel": "Textos fora do fluxo não têm variável (não são classificáveis)."})
        if is_offflow and attrs.get("variavel_roteiro"):
            raise serializers.ValidationError({"variavel_roteiro": "Textos fora do fluxo não armazenam resposta em Variável de roteiro."})
        if question_id in MANDATORY_QUESTION_IDS and "variavel_roteiro" in attrs:
            esperada = self.instance.variavel_roteiro_id if self.instance else None
            nova = attrs["variavel_roteiro"].pk if attrs["variavel_roteiro"] else None
            if nova != esperada:
                raise serializers.ValidationError({"variavel_roteiro": "Perguntas obrigatórias já têm a Variável de roteiro fixa (Nome/Área da Lead/Demanda)."})
        return attrs

class CompanyInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyInfo
        fields = "__all__"
        read_only_fields = ["company", "updated_at", "obrigatorio"]

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
    # Antes era um ChoiceField fixo com os 8 question_id do roteiro da Rufus.
    # Agora a empresa adiciona/remove perguntas (Roteiro), então a lista de
    # question_id válidos é por empresa -- validado dinamicamente em
    # services.receive() contra os Question cadastrados, mesmo padrão já
    # usado pra especialidade/Area. "validar" e "encerramento" continuam
    # reservados (nunca um "proxima" válido), também checado lá.
    proxima = serializers.CharField(max_length=80, required=False, allow_blank=True)

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
