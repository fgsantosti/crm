from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Case, When, Value, IntegerField
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action, api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from django.shortcuts import get_object_or_404
from .models import Company, Lead, Question, CompanyInfo, Event, Area, AtendenteInvite, Profile, Variavel, VariavelRoteiro, MANDATORY_QUESTION_IDS, MANDATORY_OFFFLOW_QUESTION_IDS
from .serializers import CompanySerializer, LeadSerializer, QuestionSerializer, CompanyInfoSerializer, IncomingSerializer, EventSerializer, DeliverySerializer, AreaSerializer, AtendenteInviteSerializer, AdminCompanySerializer, VariavelSerializer, VariavelRoteiroSerializer
from .services import (
    receive, escalate, create_invite,
    validar_convite as validar_convite_service,
    trocar_senha as trocar_senha_service,
    solicitar_troca_email, confirmar_troca_email as confirmar_troca_email_service,
    redefinir_senha_atendente as redefinir_senha_atendente_service,
    agent_status, gerar_token_agente, revogar_token_agente,
    reivindicar_lead as reivindicar_lead_service,
    mover_para_negociacao as mover_para_negociacao_service,
    preparar_despacho as preparar_despacho_service,
    liberar_lead as liberar_lead_service,
    enviar_despachos as enviar_despachos_service,
    criar_lead_manual as criar_lead_manual_service,
    seed_roteiro_padrao,
)

def _avatar_url(request, profile):
    return request.build_absolute_uri(profile.avatar.url) if profile.avatar else None

# O refresh token JWT fica só num cookie httpOnly (JS nunca consegue ler, então
# um XSS no frontend não rouba a sessão de longa duração) -- só o access token
# de 30min circula em memória no frontend, nunca persistido em disco/localStorage.
REFRESH_COOKIE = "refresh_token"
REFRESH_COOKIE_PATH = "/api/"
REFRESH_COOKIE_MAX_AGE = int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())

def _set_refresh_cookie(response, refresh_token):
    response.set_cookie(
        REFRESH_COOKIE, str(refresh_token), max_age=REFRESH_COOKIE_MAX_AGE,
        httponly=True, secure=settings.COOKIE_SECURE, samesite="Strict", path=REFRESH_COOKIE_PATH,
    )

def _clear_refresh_cookie(response):
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, samesite="Strict")

class LoginView(APIView):
    """POST /api/login/ -- autentica e devolve só o access token no corpo; o
    refresh vai num cookie httpOnly (ver REFRESH_COOKIE acima)."""
    permission_classes = [permissions.AllowAny]
    def post(self, request):
        serializer = TokenObtainPairSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        response = Response({"access": serializer.validated_data["access"]})
        _set_refresh_cookie(response, serializer.validated_data["refresh"])
        return response

class RefreshView(APIView):
    """POST /api/login/refresh/ -- lê o refresh do cookie (nunca do corpo).
    Usado tanto por um login silencioso ao abrir a página (sessão persistida só
    pelo cookie) quanto pelo api.ts quando um access token expira no meio do uso."""
    permission_classes = [permissions.AllowAny]
    def post(self, request):
        refresh = request.COOKIES.get(REFRESH_COOKIE)
        if not refresh:
            return Response({"detail": "Sessão não encontrada."}, status=401)
        serializer = TokenRefreshSerializer(data={"refresh": refresh})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError:
            response = Response({"detail": "Sessão expirada."}, status=401)
            _clear_refresh_cookie(response)
            return response
        response = Response({"access": serializer.validated_data["access"]})
        new_refresh = serializer.validated_data.get("refresh")
        if new_refresh:
            _set_refresh_cookie(response, new_refresh)
        return response

@api_view(["GET", "PATCH"])
@permission_classes([permissions.IsAuthenticated])
def me(request):
    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user)
    if request.method == "PATCH":
        if "display_name" in request.data:
            profile.display_name = str(request.data.get("display_name") or "")[:160]
            profile.save()
    return Response({
        "username": user.username,
        "email": user.email,
        "display_name": profile.display_name,
        "avatar_url": _avatar_url(request, profile),
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "is_agent": user.groups.filter(name="agente").exists(),
        "must_change_password": hasattr(user, "password_change_required"),
    })

@api_view(["POST", "DELETE"])
@permission_classes([permissions.IsAuthenticated])
@parser_classes([MultiPartParser])
def avatar(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == "DELETE":
        profile.avatar.delete(save=True)
        return Response({"avatar_url": None})
    file = request.FILES.get("avatar")
    if not file:
        return Response({"detail": "Envie um arquivo em 'avatar'."}, status=400)
    if file.content_type not in ("image/png", "image/jpeg", "image/webp"):
        return Response({"detail": "Formato não suportado. Use PNG, JPEG ou WEBP."}, status=400)
    if file.size > 2 * 1024 * 1024:
        return Response({"detail": "Imagem muito grande (máximo 2MB)."}, status=400)
    profile.avatar = file
    profile.save()
    return Response({"avatar_url": _avatar_url(request, profile)})

@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def validar_convite(request, pk):
    code = str(request.data.get("code") or "").strip()
    result = validar_convite_service(pk, code)
    return Response({"detail": result["detail"]}, status=200 if result["ok"] else 400)

@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def trocar_senha(request):
    current_password = str(request.data.get("current_password") or "")
    new_password = str(request.data.get("password") or "")
    if len(new_password) < 8:
        return Response({"detail": "A nova senha deve ter ao menos 8 caracteres."}, status=400)
    error = trocar_senha_service(request.user, current_password, new_password)
    if error:
        return Response({"detail": error}, status=400)
    return Response({"detail": "Senha atualizada."})

@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def trocar_email_solicitar(request):
    new_email = str(request.data.get("email") or "").strip()
    if not new_email:
        return Response({"detail": "Informe um e-mail."}, status=400)
    try:
        solicitar_troca_email(request.user, new_email)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=400)
    return Response({"detail": "Enviamos um código de confirmação para o novo e-mail."})

@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def trocar_email_confirmar(request):
    code = str(request.data.get("code") or "").strip()
    result = confirmar_troca_email_service(request.user, code)
    return Response({"detail": result["detail"]}, status=200 if result["ok"] else 400)

@api_view(["DELETE"])
@permission_classes([permissions.IsAuthenticated])
def excluir_conta(request):
    password = str(request.data.get("password") or "")
    if not request.user.check_password(password):
        return Response({"detail": "Senha incorreta."}, status=400)
    request.user.delete()
    response = Response({"detail": "Conta excluída."})
    _clear_refresh_cookie(response)
    return response

@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def logout_view(request):
    refresh = request.COOKIES.get(REFRESH_COOKIE)
    if refresh:
        try:
            RefreshToken(refresh).blacklist()
        except Exception:
            pass
    response = Response({"detail": "Sessão encerrada."})
    _clear_refresh_cookie(response)
    return response

class NotAgentAccount(permissions.BasePermission):
    """Nega acesso a contas de serviço do agente de IA (membros do grupo "agente").

    A conta de serviço do agente (ex.: username agente.<empresa>) só deve poder
    chamar as actions `incoming`/`delivery` de CompanyViewSet. Qualquer outro
    endpoint de escrita/leitura de dados do CRM (leads, roteiro, dados da
    empresa) é reservado a usuários humanos (atendentes/empresa).
    """
    message = "Conta de serviço do agente não tem acesso a este recurso."
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and not user.groups.filter(name="agente").exists())

class IsSuperUser(permissions.BasePermission):
    """Restrito à equipe interna da Axioma (is_superuser=True).

    Importante: NÃO é o mesmo que IsAdminUser do DRF (que só checa is_staff).
    Contas "Empresa" também têm is_staff=True -- usar IsAdminUser aqui
    deixaria qualquer empresa cliente enxergar/editar TODAS as empresas,
    já que os endpoints deste grupo não são filtrados por tenant de propósito
    (são a própria ferramenta interna de operação multi-empresa da Axioma).
    """
    message = "Restrito à equipe Axioma."
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_superuser)

class CompanyViewSet(viewsets.ModelViewSet):
    serializer_class = CompanySerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "agent-incoming"
    http_method_names = ["get", "post", "patch", "head", "options"]
    def get_queryset(self): return self.request.user.companies.all()
    def create(self, request, *args, **kwargs):
        # "post" no http_method_names é só pra incoming/delivery (@action detail=True
        # abaixo) -- criar Company é exclusivo do Painel Admin (AdminCompanyViewSet).
        return Response({"detail": "Use o Painel Admin interno para cadastrar uma empresa."}, status=405)
    def get_permissions(self):
        # Só o PATCH genérico (tela Roteiro, "Opções do Agente") é restrito à
        # empresa/admin -- "incoming"/"delivery" são as rotas do próprio agente
        # (POST) e continuam com a permissão padrão (IsAuthenticated), senão
        # quebra a conta de serviço do agente. "equipe" já tem permission_classes
        # próprio no @action.
        if self.action == "partial_update":
            return [permissions.IsAdminUser(), NotAgentAccount()]
        return [permissions.IsAuthenticated()]
    @action(detail=True, methods=["get"], permission_classes=[permissions.IsAuthenticated, NotAgentAccount])
    def equipe(self, request, pk=None):
        """Só atendentes ATIVOS (is_staff=False) -- nem a conta de serviço do
        agente, nem os usuários com papel Empresa/Admin, nem contas desativadas
        (ex.: via Django Admin, fora do fluxo normal de "Desligar atendente")
        aparecem aqui, já que esta tela existe pra Empresa gerenciar o time de
        atendentes em atividade, não a si mesma."""
        company = self.get_object()
        members = (
            company.members.filter(is_staff=False, is_active=True)
            .exclude(groups__name="agente")
            .select_related("profile")
            .order_by("username")
        )
        result = []
        for u in members:
            profile = getattr(u, "profile", None)
            result.append({
                "id": u.id, "username": u.username, "email": u.email or u.username,
                "display_name": profile.display_name if profile else "",
                "avatar_url": _avatar_url(request, profile) if profile else None,
                "is_staff": u.is_staff, "is_superuser": u.is_superuser, "date_joined": u.date_joined,
            })
        return Response(result)
    @action(detail=True, methods=["post"])
    def incoming(self, request, pk=None):
        company = self.get_object()
        data = IncomingSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(receive(company, data.validated_data))
    @action(detail=True, methods=["post"])
    def delivery(self, request, pk=None):
        from django.db import transaction
        authorized_company = self.get_object()
        payload = DeliverySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        with transaction.atomic():
            company = Company.objects.select_for_update().get(pk=authorized_company.pk)
            event = get_object_or_404(Event.objects.select_for_update(), pk=payload.validated_data["event_id"], lead__company=company)
            value = payload.validated_data["status"]
            if value not in ["SENT", "FAILED"]: return Response({"detail": "status deve ser SENT ou FAILED"}, status=400)
            if event.delivery == "PENDING":
                event.delivery = value
                event.save()
                if value == "FAILED": escalate(event.lead, "Falha de envio: revisar entrega antes de qualquer retomada")
            return Response({"delivery": event.delivery})

def _get_atendente_or_404(request, company_id, user_id):
    company = get_object_or_404(request.user.companies.all(), pk=company_id)
    return get_object_or_404(company.members.filter(is_staff=False), pk=user_id)

@api_view(["POST"])
@permission_classes([permissions.IsAdminUser, NotAgentAccount])
def redefinir_senha_atendente_view(request, company_id, user_id):
    atendente = _get_atendente_or_404(request, company_id, user_id)
    redefinir_senha_atendente_service(atendente)
    return Response({"detail": "Nova senha enviada para o e-mail do atendente."})

@api_view(["DELETE"])
@permission_classes([permissions.IsAdminUser, NotAgentAccount])
def desligar_atendente(request, company_id, user_id):
    atendente = _get_atendente_or_404(request, company_id, user_id)
    atendente.delete()
    return Response({"detail": "Atendente desligado."})

class TenantMixin:
    def company(self):
        return get_object_or_404(self.request.user.companies.all(), pk=self.request.query_params.get("company"))
    def get_queryset(self): return self.queryset.filter(company=self.company())

class LeadViewSet(TenantMixin, viewsets.ModelViewSet):
    queryset = Lead.objects.all()
    serializer_class = LeadSerializer
    http_method_names = ["get", "patch", "post", "delete", "head", "options"]
    def get_permissions(self):
        # Excluir um lead é fallback de admin (empresa) pra destravar um caso preso no Kanban
        # (ex.: o agente nunca o classificou) -- nunca disponível pra atendente nem pro agente.
        if self.action == "destroy":
            return [permissions.IsAdminUser(), NotAgentAccount()]
        return [permissions.IsAuthenticated(), NotAgentAccount()]
    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get("pending") == "1":
            # "Pendências" = coluna "Atendimentos em espera" do Kanban: já classificado,
            # já tem owner, mas ainda não entrou em negociação nem foi despachado.
            qs = qs.filter(etapa_atendimento="espera").annotate(
                rank=Case(When(priority="Alta", then=Value(0)), When(priority="Média", then=Value(1)), default=Value(2), output_field=IntegerField())
            ).order_by("rank", "return_at")
        return qs
    @action(detail=True)
    def events(self, request, pk=None):
        return Response(EventSerializer(self.get_object().events.all(), many=True).data)
    def _bloqueia_staff(self, request):
        """Empresa/admin (is_staff) nunca opera o Kanban pós-triagem -- só atendente."""
        return request.user.is_staff
    @action(detail=True, methods=["post"])
    def reivindicar(self, request, pk=None):
        """Qualificados -> Atendimentos em espera."""
        if self._bloqueia_staff(request):
            return Response({"detail": "Esse perfil não assume atendimentos."}, status=403)
        erro = reivindicar_lead_service(self.get_object().pk, request.user)
        if erro:
            return Response({"detail": erro}, status=400)
        return Response(LeadSerializer(self.get_object()).data)
    @action(detail=True, methods=["post"])
    def negociar(self, request, pk=None):
        """Qualificados ou Em espera -> Em negociação (botão 'Acompanhar')."""
        if self._bloqueia_staff(request):
            return Response({"detail": "Esse perfil não assume atendimentos."}, status=403)
        erro = mover_para_negociacao_service(self.get_object().pk, request.user)
        if erro:
            return Response({"detail": erro}, status=400)
        return Response(LeadSerializer(self.get_object()).data)
    @action(detail=True, methods=["post"], url_path="preparar-despacho")
    def preparar_despacho(self, request, pk=None):
        """Qualificados, Em espera ou Em negociação -> Despacho (ainda não definitivo)."""
        if self._bloqueia_staff(request):
            return Response({"detail": "Esse perfil não despacha atendimentos."}, status=403)
        auto_falha = bool(request.data.get("auto_falha"))
        erro = preparar_despacho_service(self.get_object().pk, request.data.get("desfecho"), request.user, auto_falha=auto_falha)
        if erro:
            return Response({"detail": erro}, status=400)
        return Response(LeadSerializer(self.get_object()).data)
    @action(detail=True, methods=["post"])
    def liberar(self, request, pk=None):
        """Qualquer coluna assumida -> de volta pra Qualificados (solta o owner)."""
        if self._bloqueia_staff(request):
            return Response({"detail": "Esse perfil não opera atendimentos."}, status=403)
        erro = liberar_lead_service(self.get_object().pk, request.user)
        if erro:
            return Response({"detail": erro}, status=400)
        return Response(LeadSerializer(self.get_object()).data)
    @action(detail=False, methods=["post"], url_path="enviar-despachos")
    def enviar_despachos(self, request):
        """Botão 'Enviar Despachos': finaliza de uma vez todo o Despacho deste atendente."""
        if self._bloqueia_staff(request):
            return Response({"detail": "Esse perfil não despacha atendimentos."}, status=403)
        enviados = enviar_despachos_service(request.user, self.company())
        return Response({"enviados": enviados})
    @action(detail=False, methods=["post"])
    def manual(self, request):
        """Atendimento Humano: atendente cadastra um atendimento próprio que não
        veio do agente -- nunca aparece no Kanban (Lead.origem_manual), só conta
        no Dashboard."""
        if self._bloqueia_staff(request):
            return Response({"detail": "Esse perfil não cadastra atendimentos."}, status=403)
        lead, erro = criar_lead_manual_service(self.company(), request.user, request.data)
        if erro:
            return Response({"detail": erro}, status=400)
        return Response(LeadSerializer(lead).data, status=201)

class QuestionViewSet(TenantMixin, viewsets.ModelViewSet):
    queryset = Question.objects.all().order_by("id")
    serializer_class = QuestionSerializer
    def get_permissions(self):
        base = [permissions.IsAuthenticated()] if self.request.method in permissions.SAFE_METHODS else [permissions.IsAdminUser()]
        return base + [NotAgentAccount()]
    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if self.request.method not in permissions.SAFE_METHODS:
            ctx["company"] = self.company()
        return ctx
    def perform_create(self, serializer): serializer.save(company=self.company())
    def destroy(self, request, *args, **kwargs):
        question = self.get_object()
        if question.question_id in MANDATORY_QUESTION_IDS:
            return Response({"detail": f"'{question.question_id}' é uma pergunta obrigatória do roteiro e não pode ser excluída."}, status=400)
        if question.question_id in MANDATORY_OFFFLOW_QUESTION_IDS:
            return Response({"detail": f"'{question.question_id}' é um texto obrigatório fora do fluxo e não pode ser excluído."}, status=400)
        return super().destroy(request, *args, **kwargs)

class VariavelViewSet(TenantMixin, viewsets.ModelViewSet):
    """Variáveis do Agente (peso 1-10, usadas na classificação de urgência --
    ver services.calcular_urgencia_sugerida). Toda Question fica atrelada a
    uma dessas (on_delete=PROTECT), então apagar uma em uso falha com 400."""
    queryset = Variavel.objects.all()
    serializer_class = VariavelSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    def get_permissions(self):
        base = [permissions.IsAuthenticated()] if self.request.method in permissions.SAFE_METHODS else [permissions.IsAdminUser()]
        return base + [NotAgentAccount()]
    def perform_create(self, serializer): serializer.save(company=self.company())
    def destroy(self, request, *args, **kwargs):
        from django.db.models import ProtectedError
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response({"detail": "Essa variável está em uso por uma ou mais perguntas do roteiro -- troque a variável delas antes de excluir."}, status=400)

class VariavelRoteiroViewSet(TenantMixin, viewsets.ModelViewSet):
    """Variáveis de ROTEIRO: sem peso, só guardam a resposta de uma pergunta pra
    reusar como placeholder em outro texto (ver seed_roteiro_padrao e
    services.slugify_variavel_roteiro). As 3 builtin (Nome/Área da Lead/Demanda)
    são fixas -- não podem ser excluídas nem recriadas por aqui."""
    queryset = VariavelRoteiro.objects.all()
    serializer_class = VariavelRoteiroSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    def get_permissions(self):
        base = [permissions.IsAuthenticated()] if self.request.method in permissions.SAFE_METHODS else [permissions.IsAdminUser()]
        return base + [NotAgentAccount()]
    def perform_create(self, serializer):
        from .services import slugify_variavel_roteiro, proxima_cor_roteiro
        company = self.company()
        name = serializer.validated_data["name"]
        serializer.save(company=company, slug=slugify_variavel_roteiro(company, name), cor=proxima_cor_roteiro(company))
    def destroy(self, request, *args, **kwargs):
        from django.db.models import ProtectedError
        variavel = self.get_object()
        if variavel.builtin:
            return Response({"detail": f"'{variavel.name}' é uma Variável de roteiro obrigatória e não pode ser excluída."}, status=400)
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response({"detail": "Essa Variável de roteiro está em uso por uma pergunta -- desmarque a opção na pergunta antes de excluir."}, status=400)

class CompanyInfoViewSet(TenantMixin, viewsets.ModelViewSet):
    """Dados da empresa: o agente de IA precisa LER isto (para responder perguntas
    livres sobre a empresa fora do roteiro fixo), então a leitura fica aberta a
    qualquer membro autenticado da empresa, inclusive a conta de serviço do
    agente. Só a escrita é restrita a staff humano (NotAgentAccount)."""
    queryset = CompanyInfo.objects.all()
    serializer_class = CompanyInfoSerializer
    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser(), NotAgentAccount()]
    def perform_create(self, serializer): serializer.save(company=self.company())
    def destroy(self, request, *args, **kwargs):
        info = self.get_object()
        if info.obrigatorio:
            return Response({"detail": f"\"{info.title}\" é obrigatório e não pode ser excluído -- o agente depende disso pra responder clientes."}, status=400)
        return super().destroy(request, *args, **kwargs)

class AdminCompanyViewSet(viewsets.ModelViewSet):
    """Painel Admin interno da Axioma: cadastro de empresas e token do agente.

    Propositalmente SEM TenantMixin -- é a única tela do sistema com visão
    cross-tenant de verdade, então IsSuperUser (não IsAdminUser, que também
    deixaria passar contas "Empresa" com is_staff=True) é quem garante que
    só a equipe interna da Axioma chega aqui.
    """
    queryset = Company.objects.all().order_by("name")
    serializer_class = AdminCompanySerializer
    permission_classes = [IsSuperUser]
    # "delete" precisa ficar habilitado pra action "agente" (revogar token) --
    # destroy() é desligado explicitamente abaixo pra isso não virar exclusão
    # de empresa (destrutivo demais pra expor sem uma tela própria de confirmação).
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def perform_create(self, serializer):
        company = serializer.save()
        seed_roteiro_padrao(company)

    def destroy(self, request, *args, **kwargs):
        return Response({"detail": "Exclusão de empresa não é suportada por aqui."}, status=405)

    @action(detail=True, methods=["get", "post", "delete"])
    def agente(self, request, pk=None):
        company = self.get_object()
        if request.method == "GET":
            return Response(agent_status(company))
        if request.method == "POST":
            raw = request.data.get("validade_dias")
            try:
                dias = int(raw) if raw not in (None, "") else 180
            except (TypeError, ValueError):
                return Response({"detail": "validade_dias precisa ser um número inteiro."}, status=400)
            if dias < 1 or dias > 730:
                return Response({"detail": "Validade deve ser entre 1 e 730 dias."}, status=400)
            return Response(gerar_token_agente(company, dias))
        revogar_token_agente(company)
        return Response({"detail": "Token revogado."})

    @action(detail=False, methods=["get"])
    def overview(self, request):
        """Dashboard do admin geral: visão agregada, nunca por empresa específica
        (o admin geral não opera dentro do workspace de nenhuma empresa)."""
        companies = list(self.get_queryset())
        data = AdminCompanySerializer(companies, many=True).data
        com_agente_ativo = sum(1 for c in data if c["tem_agente_ativo"])
        User = get_user_model()
        usuarios_ativos = User.objects.filter(is_active=True).exclude(groups__name="agente").count()
        return Response({
            "empresas_total": len(data),
            "empresas_com_agente_ativo": com_agente_ativo,
            "empresas_sem_agente_ativo": len(data) - com_agente_ativo,
            "usuarios_ativos": usuarios_ativos,
        })

    @action(detail=False, methods=["get"], url_path="contas-empresa")
    def contas_empresa(self, request):
        """Lista só as contas "Empresa" (is_staff, não agente, não superuser),
        cross-tenant -- é o que vira a aba "Equipe" do admin geral (só empresas,
        nunca atendentes, que ficam na Equipe de dentro de cada empresa)."""
        User = get_user_model()
        users = (
            User.objects.filter(is_staff=True, is_superuser=False)
            .exclude(groups__name="agente")
            .prefetch_related("companies")
            .order_by("username")
        )
        result = []
        for u in users:
            profile = getattr(u, "profile", None)
            result.append({
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "display_name": profile.display_name if profile else "",
                "is_active": u.is_active,
                "date_joined": u.date_joined,
                "companies": [c.name for c in u.companies.all()],
            })
        return Response(result)

class AreaViewSet(TenantMixin, viewsets.ModelViewSet):
    """Áreas de atendimento cadastradas pela empresa (tela "Equipe")."""
    queryset = Area.objects.all()
    serializer_class = AreaSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]
    def get_permissions(self):
        base = [permissions.IsAuthenticated()] if self.request.method in permissions.SAFE_METHODS else [permissions.IsAdminUser()]
        return base + [NotAgentAccount()]
    def perform_create(self, serializer): serializer.save(company=self.company())

class AtendenteInviteViewSet(TenantMixin, viewsets.ModelViewSet):
    """Convites de novo atendente (tela "Equipe"): só a empresa cria/cancela;
    a validação do código em si é feita pelo atendente, sem conta ainda, na
    view pública `validar_convite` -- não passa por este ViewSet autenticado."""
    queryset = AtendenteInvite.objects.all()
    serializer_class = AtendenteInviteSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]
    def get_permissions(self):
        base = [permissions.IsAuthenticated()] if self.request.method in permissions.SAFE_METHODS else [permissions.IsAdminUser()]
        return base + [NotAgentAccount()]
    def perform_create(self, serializer):
        company = self.company()
        try:
            invite = create_invite(company, serializer.validated_data["name"], serializer.validated_data["email"])
        except ValueError as exc:
            from rest_framework import serializers as drf_serializers
            raise drf_serializers.ValidationError({"email": str(exc)})
        serializer.instance = invite
