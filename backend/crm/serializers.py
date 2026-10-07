import re
from django.utils import timezone
from rest_framework import serializers
from .models import Blacklist, Company, Lead, Question, CompanyInfo, Event, Area, AtendenteInvite, Variavel, VariavelRoteiro, MANDATORY_OFFFLOW_QUESTION_IDS, MANDATORY_QUESTION_IDS

# Obrigatórias que nunca entram numa lista SPIN (a área só é conhecida depois delas).
FIXED_QUESTION_IDS = {"nome", "situacao"}

class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ["id", "name", "initial_state", "allow_transcription", "numero_agente", "agente_conversacional", "mensagens_audio", "voz_tts", "etapa_inicial", "spin_inicial"]
        # Só as opções do agente (tela Roteiro, aba "Opções do Agente") são editáveis
        # por aqui -- os demais campos de Company continuam no Painel Admin.
        read_only_fields = ["id", "name", "initial_state", "allow_transcription", "numero_agente"]
    def validate(self, attrs):
        area = attrs.get("spin_inicial", self.instance.spin_inicial if self.instance else None)
        ativa = attrs.get("etapa_inicial", self.instance.etapa_inicial if self.instance else False)
        if area and (not self.instance or area.company_id != self.instance.pk):
            raise serializers.ValidationError({"spin_inicial": "Selecione uma SPIN desta empresa."})
        if ativa and (not area or not Question.objects.filter(company=self.instance, area=area).exclude(text__regex=r"^\s*$").exists()):
            raise serializers.ValidationError({"spin_inicial": "Selecione uma SPIN com perguntas e texto cadastrado."})
        return attrs
    def validate_mensagens_audio(self, value):
        if value and self.instance is not None and not self.instance.allow_transcription:
            raise serializers.ValidationError("Habilite o áudio no painel Admin.")
        return value

class AdminCompanySerializer(serializers.ModelSerializer):
    """Só para a tela interna da Axioma (IsSuperUser) -- cross-tenant de propósito."""
    member_count = serializers.SerializerMethodField()
    tem_agente_ativo = serializers.SerializerMethodField()
    # Entrada livre (com espaços/traços); validate_numero_agente normaliza para E.164 (<= 16).
    numero_agente = serializers.CharField(max_length=40, allow_blank=True, required=False)
    class Meta:
        model = Company
        fields = ["id", "name", "initial_state", "allow_transcription", "numero_agente", "member_count", "tem_agente_ativo"]
        read_only_fields = ["id", "member_count", "tem_agente_ativo"]
    def validate_numero_agente(self, value):
        # Aceita como a pessoa digita ("+55 (86) 9423-8125", "5586...") e grava em E.164.
        bruto = (value or "").strip()
        digits = re.sub(r"\D", "", bruto)
        value = f"+{digits}" if digits else ""
        if bruto and not re.match(r"^\+[1-9]\d{7,14}$", value):
            raise serializers.ValidationError("Use o formato internacional, ex.: +5586999999999.")
        return value
    def get_member_count(self, obj):
        # Só atendentes/empresa ATIVOS -- uma conta desativada (ex.: via Django
        # Admin, fora do fluxo normal de "Desligar atendente") não deve inflar
        # essa contagem, e a conta de serviço do agente nunca conta aqui.
        return obj.members.filter(is_active=True).exclude(groups__name="agente").count()
    def get_tem_agente_ativo(self, obj):
        from .services import agent_status
        status = agent_status(obj)
        if not status["masked_key"]:
            return False
        return not (status["validade"] and status["validade"]["expirado"])

class LeadSerializer(serializers.ModelSerializer):
    # owner é o id do usuário (compare com /me/.id); owner_nome é só pra exibir.
    owner_nome = serializers.SerializerMethodField()
    # Ordem única de urgência (services.URGENCIA_RANK): o Kanban ordena por isto, maior = mais urgente.
    urgencia_rank = serializers.SerializerMethodField()

    def get_urgencia_rank(self, obj):
        from .services import URGENCIA_RANK
        return URGENCIA_RANK.get(obj.temperature, -1)

    def get_owner_nome(self, obj):
        from .services import _nome_usuario
        return _nome_usuario(obj.owner)

    class Meta:
        model = Lead
        fields = "__all__"
        # owner/mode só mudam via as actions assumir/despachar (services.py) --
        # nunca mais um PATCH livre de texto, pra garantir atomicidade real
        # na disputa por um lead entre atendentes.
        read_only_fields = ["id", "company", "contact", "contact_name", "created_at", "state", "last_audio_id", "bot_closed", "pedido_humano_pendente", "last_contact", "owner", "mode", "desfecho", "variaveis_roteiro", "urgencia_detalhe", "etapa_atendimento", "desfecho_pendente", "origem_manual"]

    def validate(self, attrs):
        if attrs.get("mode") == "AUTOMÁTICO" and self.instance and self.instance.mode == "HUMANO":
            raise serializers.ValidationError("Retomada exige comando administrativo autorizado; indisponível nesta versão.")
        return attrs

class LeadManualSerializer(serializers.Serializer):
    """Entrada do cadastro manual (tela Meus Atendimentos): limites iguais aos do
    model (senão estoura DataError/500) e contato normalizado pra E.164 -- mesma
    chave que o agente usa, senão o mesmo cliente vira dois leads ativos."""
    ROTULOS = {"name": "Nome", "contact": "Contato", "demand": "Demanda"}
    name = serializers.CharField(max_length=160, required=False, allow_blank=True, default="", trim_whitespace=True)
    contact = serializers.CharField(max_length=40, error_messages={"required": "obrigatório.", "blank": "obrigatório."})
    demand = serializers.CharField(max_length=300, required=False, allow_blank=True, default="", trim_whitespace=True)

    def validate_contact(self, value):
        digitos = re.sub(r"\D", "", value)
        if value.strip().startswith("+"):
            e164 = f"+{digitos}"
        elif digitos.startswith("55") and len(digitos) in (12, 13):
            e164 = f"+{digitos}"
        else:
            e164 = f"+55{digitos}"
        if not re.fullmatch(r"\+[1-9]\d{7,14}", e164):
            raise serializers.ValidationError("use um telefone válido com DDD (ex.: +55 85 99999-8888).")
        return e164

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
    variaveis_obrigatorias = serializers.PrimaryKeyRelatedField(queryset=VariavelRoteiro.objects.all(), many=True, required=False)
    area = serializers.PrimaryKeyRelatedField(queryset=Area.objects.all(), required=False, allow_null=True)
    class Meta:
        model = Question
        fields = "__all__"
        # Gravação só pelo endpoint dedicado (POST/DELETE /questions/{id}/audio/), que converte e valida.
        read_only_fields = ["company", "obrigatoria", "audio_gravado"]
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
    def validate_question_id(self, question_id):
        # company é read-only aqui, então o DRF não checa a UniqueConstraint(company, question_id)
        # sozinho: sem isso um question_id repetido virava IntegrityError (500).
        company = self.context.get("company")
        if company:
            iguais = Question.objects.filter(company=company, question_id=question_id)
            if self.instance:
                iguais = iguais.exclude(pk=self.instance.pk)
            if iguais.exists():
                raise serializers.ValidationError(f"Já existe uma pergunta '{question_id}' nesta empresa.")
        return question_id
    def validate_area(self, area):
        company = self.context.get("company")
        if area and company and area.company_id != company.id:
            raise serializers.ValidationError("Área não pertence a esta empresa.")
        return area
    def _validar_spin(self, attrs, question_id, is_offflow):
        """Lista da pergunta (fixas = sem área, ou {Área}-SPIN) e regras que dependem dela."""
        inst = self.instance
        area = attrs["area"] if "area" in attrs else (inst.area if inst else None)
        etapa = attrs["etapa_spin"] if "etapa_spin" in attrs else (inst.etapa_spin if inst else "")
        if area and (is_offflow or question_id in FIXED_QUESTION_IDS):
            raise serializers.ValidationError({"area": f"'{question_id}' é sempre uma pergunta fixa (sem área)."})
        if etapa and not area:
            raise serializers.ValidationError({"etapa_spin": "Etapa SPIN só vale para perguntas de uma área."})
        vr = attrs["variavel_roteiro"] if "variavel_roteiro" in attrs else (inst.variavel_roteiro if inst else None)
        if vr and vr.builtin and question_id not in MANDATORY_QUESTION_IDS:
            # Builtins ficam nas obrigatórias; a única exceção é "Demanda" (tema) em UMA pergunta
            # por lista de área — a de "Problema" que guarda a demanda daquela área.
            if vr.slug != "tema" or not area:
                raise serializers.ValidationError({"variavel_roteiro": "Essa Variável de roteiro é fixa das perguntas obrigatórias. "
                                                   "Só 'Demanda' pode ser usada, numa pergunta SPIN de uma área."})
            outras = Question.objects.filter(company_id=area.company_id, area=area, variavel_roteiro=vr).exclude(question_id="demanda")
            if inst:
                outras = outras.exclude(pk=inst.pk)
            if outras.exists():
                raise serializers.ValidationError({"variavel_roteiro": f"A lista {area.name}-SPIN já tem uma pergunta que guarda a Demanda."})
        if not area:
            attrs["etapa_spin"] = ""
    def validate(self, attrs):
        question_id = attrs.get("question_id") or (self.instance.question_id if self.instance else "")
        if self.instance and self.instance.question_id in MANDATORY_QUESTION_IDS + MANDATORY_OFFFLOW_QUESTION_IDS and question_id != self.instance.question_id:
            raise serializers.ValidationError({"question_id": "O identificador de uma pergunta obrigatória não pode ser alterado."})
        required = attrs.get("variaveis_obrigatorias", list(self.instance.variaveis_obrigatorias.all()) if self.instance else [])
        if required and question_id != "necessidade_humana":
            raise serializers.ValidationError({"variaveis_obrigatorias": "Este seletor é exclusivo da mensagem de Necessidade humana."})
        company = self.context.get("company")
        if company and any(v.company_id != company.pk for v in required):
            raise serializers.ValidationError({"variaveis_obrigatorias": "Variável de roteiro não pertence a esta empresa."})
        if question_id == "necessidade_humana":
            text = attrs.get("text", self.instance.text if self.instance else "")
            if not text.strip():
                raise serializers.ValidationError({"text": "Cadastre a mensagem de Necessidade humana."})
        if question_id in MANDATORY_QUESTION_IDS + MANDATORY_OFFFLOW_QUESTION_IDS:
            attrs["obrigatoria"] = True
        self._validar_spin(attrs, question_id, question_id in MANDATORY_OFFFLOW_QUESTION_IDS)
        area = attrs.get("area", self.instance.area if self.instance else None)
        envio_obrigatorio = attrs.get("envio_obrigatorio", self.instance.envio_obrigatorio if self.instance else False)
        if attrs.get("envio_obrigatorio") and not area:
            raise serializers.ValidationError({"envio_obrigatorio": "O envio obrigatório é exclusivo das perguntas SPIN."})
        if not area:
            attrs["envio_obrigatorio"] = False
        elif envio_obrigatorio and not attrs.get("text", self.instance.text if self.instance else "").strip():
            raise serializers.ValidationError({"text": "Cadastre o texto da pergunta antes de marcar o envio obrigatório."})
        is_offflow = question_id in MANDATORY_OFFFLOW_QUESTION_IDS
        if not is_offflow and attrs.get("habilitada") is False:
            raise serializers.ValidationError({"habilitada": "O controle de envio é exclusivo dos textos fora do fluxo."})
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

class DashboardPeriodSerializer(serializers.Serializer):
    data_inicio = serializers.DateField(required=False, input_formats=["%Y-%m-%d"])
    data_fim = serializers.DateField(required=False, input_formats=["%Y-%m-%d"])

    def validate(self, attrs):
        inicio, fim = attrs.get("data_inicio"), attrs.get("data_fim")
        if bool(inicio) != bool(fim):
            raise serializers.ValidationError("Informe as datas de início e fim do período.")
        if inicio and inicio > fim:
            raise serializers.ValidationError("A data de início deve ser anterior ou igual à data de fim.")
        return attrs

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
    # CLASSIFICADO: nota 0-10 por question_id respondido; o CRM calcula a urgência
    # ponderando pelos pesos das Variáveis (services.calcular_urgencia).
    notas = serializers.DictField(child=serializers.FloatField(min_value=0, max_value=10), required=False)
    # CLASSIFICADO direto (sem VALIDAR) quando o contato desiste no meio da triagem.
    encerramento_antecipado = serializers.BooleanField(required=False)
    variaveis_roteiro = serializers.DictField(child=serializers.CharField(max_length=300, allow_blank=True), required=False)

class IncomingSerializer(serializers.Serializer):
    contact = serializers.RegexField(r"^\+[1-9]\d{7,14}$")
    contact_name = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")
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
            if fields.get("encerramento_antecipado"):
                return attrs
            if not fields.get("notas") and not (fields.get("temperatura") and fields.get("prioridade")):
                raise serializers.ValidationError("CLASSIFICADO exige fields.notas (recomendado) ou fields.temperatura e fields.prioridade.")
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


class BlacklistSerializer(serializers.ModelSerializer):
    adicionado_por_nome = serializers.SerializerMethodField()
    contact = serializers.CharField(max_length=40)

    def get_adicionado_por_nome(self, obj):
        from .services import _nome_usuario
        return _nome_usuario(obj.adicionado_por) if obj.adicionado_por else ""

    def validate_contact(self, value):
        from .services import normalizar_contato
        e164 = normalizar_contato(value)
        if not e164:
            raise serializers.ValidationError("use um telefone válido com DDD (ex.: +55 85 99999-8888).")
        return e164

    class Meta:
        model = Blacklist
        fields = ["id", "contact", "motivo", "adicionado_por", "adicionado_por_nome", "created_at"]
        read_only_fields = ["id", "adicionado_por", "adicionado_por_nome", "created_at"]
