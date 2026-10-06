import uuid
from datetime import timedelta
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone

class Company(models.Model):
    name = models.CharField(max_length=160)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="companies")
    initial_state = models.CharField(max_length=80, default="apresentacao", help_text="question_id inicial enviado no primeiro contato.")
    allow_transcription = models.BooleanField(default=False)
    numero_agente = models.CharField(
        max_length=16, blank=True,
        help_text="Número de WhatsApp (E.164) conectado ao agente. Normalmente é o mesmo número em que a equipe "
        "faz os atendimentos; mensagens vindas dele mesmo nunca abrem lead.",
    )
    VOZES_TTS = [
        ("pt-BR-FranciscaNeural", "Francisca (feminina)"),
        ("pt-BR-AntonioNeural", "Antonio (masculina)"),
        ("pt-BR-ThalitaMultilingualNeural", "Thalita (feminina, multilíngue)"),
    ]
    mensagens_audio = models.BooleanField(
        default=False,
        help_text="O agente envia todas as mensagens como áudio (TTS automático; perguntas com gravação própria "
        "usam a gravação). Só vale com allow_transcription ligado pelo Admin -- ver Company.audio_ativo.",
    )
    voz_tts = models.CharField(max_length=60, choices=VOZES_TTS, default="pt-BR-FranciscaNeural")
    agente_conversacional = models.BooleanField(
        default=True,
        help_text="Marcado: o agente envia o texto de apresentação e pode conversar livremente sobre a empresa "
        "(fallback 'empresa') enquanto aguarda o lead entrar no funil. Desmarcado: o agente vai direto pro funil de "
        "triagem com um texto inicial próprio, só esperando qualquer resposta do lead para avançar -- sem conversa "
        "livre sobre a empresa nesse meio-tempo. Configurado na tela Roteiro, aba 'Opções do Agente'.",
    )
    def __str__(self): return self.name
    @property
    def audio_ativo(self):
        # O portão é do Admin: se ele desligar depois, a opção da empresa deixa de valer.
        return self.allow_transcription and self.mensagens_audio

MANDATORY_QUESTION_IDS = ["nome", "situacao", "demanda"]

# Textos fora do fluxo de triagem: apresentação (1ª mensagem, question_id = initial_state
# padrão), fallback sobre a empresa (perguntas livres durante o fluxo), confirmação dos
# dados coletados (VALIDAR) e encerramento (CLASSIFICADO). Não contam resposta do lead
# pra classificação, então não ficam atreladas a uma Variavel (ver QuestionSerializer).
MANDATORY_OFFFLOW_QUESTION_IDS = ["apresentacao", "empresa", "validar", "encerramento"]

class Variavel(models.Model):
    """Variável que a empresa define pra orientar a classificação de urgência
    do agente (tela "Variáveis do Agente"). Cada pergunta do roteiro fica
    sempre atrelada a uma dessas, com o peso valendo pra classificação --
    ver services.calcular_urgencia (média das notas do agente ponderada pelos
    pesos, convertida nas 5 faixas de services.FAIXAS_URGENCIA)."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="variaveis")
    name = models.CharField(max_length=120)
    peso = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(10)])
    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "name"], name="unique_company_variavel")]
        ordering = ["name"]
    def __str__(self): return self.name

class VariavelRoteiro(models.Model):
    """Variável de ROTEIRO: nome que a empresa dá pra guardar o texto coletado numa
    pergunta e reusar como placeholder ({slug}) no texto de outras perguntas -- sem
    peso, não entra na classificação de urgência (isso é papel de Variavel, a
    "Variável do agente"). As 3 builtin (Nome/Área da Lead/Demanda) existem em toda
    empresa e reaproveitam os placeholders fixos já existentes (nome/especialidade/
    tema), sem precisar de armazenamento extra; variáveis de perguntas adicionais
    gravam em Lead.variaveis_roteiro (ver services.apply_fields/render_text)."""
    PALETA_CORES = ["#D97757", "#5B8DEF", "#3FA66C", "#B8609B", "#D4A72C", "#6366F1", "#E2574C", "#14919B"]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="variaveis_roteiro")
    name = models.CharField(max_length=120)
    slug = models.CharField(max_length=80, help_text="Token usado como {slug} no texto; gerado a partir do nome, só letras minúsculas e _.")
    cor = models.CharField(max_length=7, default="#D97757", help_text="Cor do marcador na tela Roteiro, pra confirmação visual.")
    builtin = models.BooleanField(default=False)
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="unique_company_variavelroteiro_name"),
            models.UniqueConstraint(fields=["company", "slug"], name="unique_company_variavelroteiro_slug"),
        ]
        ordering = ["name"]
    def __str__(self): return self.name

class Question(models.Model):
    """Conteúdo fixo aprovado para um question_id do agente Axioma.

    O agente decide sozinho qual é a próxima pergunta (via os marcadores
    Q/ATUALIZAR/VALIDAR/CLASSIFICADO); este modelo só resolve um question_id
    para o texto ou áudio aprovado que de fato é enviado ao contato.

    3 question_id são obrigatórias em toda empresa (MANDATORY_QUESTION_IDS) e
    não podem ser excluídas (ver views.QuestionViewSet.destroy): nome,
    situacao e demanda. Toda pergunta do FLUXO (obrigatória ou não) fica
    sempre atrelada a uma Variavel com peso, nunca null (on_delete=PROTECT:
    não dá pra apagar uma variável ainda em uso por uma pergunta) -- exceto
    os 4 textos fora do fluxo (MANDATORY_OFFFLOW_QUESTION_IDS), que não
    coletam resposta classificável e por isso não têm Variavel.
    """
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    question_id = models.CharField(max_length=80, help_text="Ex.: apresentacao, empresa, nome, situacao, ainda_na_empresa, tipo_de_situacao, afetou_renda, equipe_avaliar_situacao, demanda, validar, encerramento, repetir.")
    text = models.TextField(blank=True)
    audio_asset = models.CharField(max_length=250, blank=True, help_text="Obsoleto (não usado): substituído por audio_gravado.")
    audio_gravado = models.FileField(
        upload_to="roteiro_audio/", blank=True,
        help_text="Gravação própria desta pergunta (OGG/Opus mono 48k, convertida no upload). Com 'Mensagens via áudio' "
        "ligado, substitui o TTS automático.",
    )
    variavel = models.ForeignKey(Variavel, on_delete=models.PROTECT, related_name="perguntas", null=True, blank=True)
    obrigatoria = models.BooleanField(default=False)
    ordem = models.PositiveIntegerField(default=0, help_text="Posição no fluxo de perguntas, definida por arrastar-e-soltar na tela Roteiro; sem efeito nos textos fora do fluxo.")
    variavel_roteiro = models.ForeignKey(
        VariavelRoteiro, on_delete=models.PROTECT, related_name="perguntas", null=True, blank=True,
        help_text="Opcional: guarda a resposta desta pergunta pra reusar como placeholder em outro texto do roteiro. Fixo nas 3 obrigatórias, opcional (via checkbox) nas demais.",
    )
    # SPIN por área: null = pergunta fixa (feita para todos antes de o agente definir a área);
    # com área = pergunta da lista "{Área}-SPIN", feita só depois que o lead é classificado nela.
    # `ordem` vale dentro da lista (fixas, ou cada área).
    ETAPAS_SPIN = [("", "—"), ("situacao", "Situação"), ("problema", "Problema"), ("implicacao", "Implicação"), ("necessidade", "Necessidade")]
    area = models.ForeignKey("Area", on_delete=models.PROTECT, related_name="perguntas_spin", null=True, blank=True)
    etapa_spin = models.CharField(max_length=12, choices=ETAPAS_SPIN, blank=True, default="")
    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "question_id"], name="unique_company_question")]
        ordering = ["ordem", "id"]

class CompanyInfo(models.Model):
    """Entrada de 'Dados da empresa': título + texto que o agente pode consultar
    para responder perguntas livres sobre a empresa (horário, endereço, serviços,
    formas de pagamento etc.), fora do roteiro fixo de qualificação.

    3 entradas são obrigatórias em toda empresa (não podem ser excluídas --
    ver views.CompanyInfoViewSet.destroy): nome da empresa, áreas de
    atendimento e disponibilidade de horários. O agente precisa delas prontas
    pra responder perguntas comuns de cliente sem inventar."""
    MANDATORY_TITLES = ["Nome da empresa", "Áreas de atendimento", "Disponibilidade de horários"]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="info_entries")
    title = models.CharField(max_length=160)
    content = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    obrigatorio = models.BooleanField(default=False)
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
    DESFECHO_CHOICES = [
        ("encerrado", "Encerrado"),
        ("comprometido", "Comprometido"),
        ("falha", "Falha durante o atendimento"),
        # Automático: CLASSIFICADO como Desqualificado/Desconfiado (nunca entram no Kanban
        # humano, então nunca receberiam desfecho e o número ficaria mudo pra sempre).
        ("desqualificado", "Desqualificado na triagem"),
        # "Despachar e bloquear": concluído e número na BlackList (conta como concluído, não sucesso).
        ("bloqueado", "Bloqueado"),
    ]
    # Desfechos que um atendente pode escolher no Despacho (o automático fica de fora).
    DESFECHO_DESPACHO = {"encerrado", "comprometido", "falha"}
    # Conclusões feitas por atendente (dashboard): despacho normal ou "Despachar e bloquear".
    DESFECHO_CONCLUIDO = DESFECHO_DESPACHO | {"bloqueado"}

    id =models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="leads_atendidos",
        help_text="Atendente responsável. FK (não texto): trocar o nome de exibição nunca faz o atendente perder os próprios leads.",
    )
    mode =models.CharField(max_length=10, choices=[("AUTOMÁTICO", "Automático"), ("HUMANO", "Humano")], default="AUTOMÁTICO")
    last_audio_id = models.CharField(max_length=250, blank=True)
    bot_closed = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    urgencia_detalhe = models.JSONField(default=dict, blank=True, help_text="Auditoria do CLASSIFICADO por notas: {notas, pesos, score, temperatura_calculada} (ver services.calcular_urgencia).")
    variaveis_roteiro = models.JSONField(default=dict, blank=True, help_text="slug->texto coletado nas perguntas com Variável de roteiro customizada (ver services.apply_fields/render_text). Os 3 builtin (nome/especialidade/tema) não usam isto -- já são campos próprios do Lead.")
    desfecho = models.CharField(max_length=20, choices=DESFECHO_CHOICES, blank=True, help_text="Definitivo: setado ao despachar (services.enviar_despachos) ou automaticamente ao classificar como Desqualificado/Desconfiado. Lead some do Kanban quando preenchido.")
    concluido_em = models.DateTimeField(null=True, blank=True, help_text="Quando o desfecho virou definitivo.")
    ETAPA_ATENDIMENTO_CHOICES = [
        ("espera", "Atendimentos em espera"),
        ("negociacao", "Em negociação"),
        ("despacho", "Despacho"),
    ]
    etapa_atendimento = models.CharField(
        max_length=20, choices=ETAPA_ATENDIMENTO_CHOICES, blank=True,
        help_text="Coluna do Kanban pós-classificação. Qualificados (vazio) e Em espera não têm responsável; negociação e despacho atribuem o atendente. Ver services.reivindicar_lead/mover_para_negociacao/preparar_despacho/liberar_lead.",
    )
    desfecho_pendente = models.CharField(
        max_length=20, choices=DESFECHO_CHOICES, blank=True,
        help_text="Desfecho escolhido ao arrastar pra 'Despacho', mas ainda NÃO definitivo -- só vira Lead.desfecho (e some do Kanban) quando o owner clica 'Enviar Despachos' (services.enviar_despachos).",
    )
    origem_manual = models.BooleanField(
        default=False,
        help_text="Lead cadastrado manualmente por um atendente na tela Atendimento Humano (ver services.criar_lead_manual) -- nunca passou pelo funil do agente, não aparece no Kanban de Leads, só entra nas contagens do Dashboard.",
    )
    class Meta:
        constraints = [
            # Único por contato SÓ entre leads ainda ativos (desfecho em aberto) -- depois que
            # um lead é despachado (desfecho definitivo), o número fica livre pra abrir um lead
            # novo caso o cliente volte a escrever. Enquanto ativo, o agente nunca recebe mensagem
            # de novo pra esse número (ver services.receive -- bot_closed/desfecho em aberto =
            # NO_REPLY sempre); histórico de leads concluídos nunca é apagado nem reaproveitado.
            models.UniqueConstraint(fields=["company", "contact"], condition=models.Q(desfecho=""), name="unique_company_contact_ativo"),
        ]
        ordering = ["-created_at"]

class Blacklist(models.Model):
    """Números que nunca entram no funil: o agente ignora (NO_REPLY sem lead nem evento).
    Empresa e atendentes adicionam/removem pela tela BlackList; remover reverte na hora."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="blacklist")
    contact = models.CharField(max_length=20, help_text="E.164 normalizado (+55...).")
    motivo = models.CharField(max_length=200, blank=True)
    adicionado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "contact"], name="unique_company_blacklist_contact")]
        ordering = ["-created_at"]
    def __str__(self): return self.contact

class Event(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="events")
    message_id = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)
    summary = models.CharField(max_length=160)
    result = models.JSONField(default=dict)
    # NOT_REQUIRED | PENDING | SENT | FAILED | EXPIRADO (pendente há 90s+ e superado por um marcador novo)
    delivery = models.CharField(max_length=15, default="NOT_REQUIRED")
    # Marcador do agente que gerou o evento (Q/REPETIR/...); base da contagem de repetições.
    marker = models.CharField(max_length=20, blank=True, default="")
    class Meta:
        constraints = [models.UniqueConstraint(fields=["lead", "message_id"], name="unique_lead_message")]
        ordering = ["created_at"]

def default_token_expiry():
    return timezone.now() + timedelta(days=183)  # ~6 meses

class AgentTokenExpiry(models.Model):
    """Validade por tempo para um token de serviço (DRF Token) do agente Axioma.

    Opcional: um Token sem linha aqui nunca expira (comportamento padrão do
    DRF, preservado para não quebrar tokens já em produção antes desta
    feature). Criado pelo inline em Tokens no Django Admin; o padrão de 6
    meses e o teto de 2 anos são aplicados lá (AgentTokenExpiryForm).
    """
    token = models.OneToOneField("authtoken.Token", on_delete=models.CASCADE, related_name="expiry")
    expires_at = models.DateTimeField(default=default_token_expiry)
