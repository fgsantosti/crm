from .health import ready
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.static import serve


import mimetypes
mimetypes.add_type("audio/ogg", ".ogg")  # a imagem slim não traz o mapeamento; a ponte precisa do MIME certo


def servir_media(request, path):
    return serve(request, path, document_root=settings.MEDIA_ROOT)
from rest_framework.routers import DefaultRouter
from crm.views import (
    AdminPrecosView, AdminGestorViewSet, AdminFaturamentoView, AdminPagamentoView, AdminRegrasCobrancaView, AdminNotificacoesConfigView, AdminNotificacoesEnviarView, AdminNotificacoesHistoricoView, AdminNotificacoesChavesView, AdminNotificacoesProcessarView,
    CompanyViewSet, LeadViewSet, QuestionViewSet, CompanyInfoViewSet, AreaViewSet, AtendenteInviteViewSet, BlacklistViewSet, AdminCompanyViewSet, VariavelViewSet, VariavelRoteiroViewSet,
    me, avatar, validar_convite, trocar_senha, trocar_email_solicitar, trocar_email_confirmar, excluir_conta,
    redefinir_senha_atendente_view, desligar_atendente,
    LoginView, RefreshView, logout_view,
)
router = DefaultRouter()
router.register("companies", CompanyViewSet, basename="company")
router.register("leads", LeadViewSet)
router.register("questions", QuestionViewSet)
router.register("company-info", CompanyInfoViewSet, basename="companyinfo")
router.register("areas", AreaViewSet, basename="area")
router.register("blacklist", BlacklistViewSet, basename="blacklist")
router.register("convites", AtendenteInviteViewSet, basename="convite")
router.register("admin-companies", AdminCompanyViewSet, basename="admin-company")
router.register("admin-gestores", AdminGestorViewSet, basename="admin-gestor")
router.register("variaveis", VariavelViewSet, basename="variavel")
router.register("variaveis-roteiro", VariavelRoteiroViewSet, basename="variavelroteiro")
urlpatterns = [
    path("health/ready/", ready),
    path("admin/", admin.site.urls),
    # Humanos (frontend): JWT access + refresh. O agente Axioma usa um token
    # fixo (TokenAuthentication) pré-provisionado via Django shell/admin, nunca
    # passa por aqui -- ver docs/integracao-agente.md.
    path("api/login/", LoginView.as_view()),
    path("api/login/refresh/", RefreshView.as_view()),
    path("api/logout/", logout_view),
    path("api/me/", me),
    path("api/me/avatar/", avatar),
    path("api/me/email/", trocar_email_solicitar),
    path("api/me/email/confirmar/", trocar_email_confirmar),
    path("api/me/excluir/", excluir_conta),
    path("api/trocar-senha/", trocar_senha),
    path("api/convites/<uuid:pk>/validar/", validar_convite),
    path("api/companies/<int:company_id>/equipe/<int:user_id>/redefinir-senha/", redefinir_senha_atendente_view),
    path("api/companies/<int:company_id>/equipe/<int:user_id>/", desligar_atendente),
    path("api/admin-precos/", AdminPrecosView.as_view()),
    path("api/admin-faturamento/", AdminFaturamentoView.as_view()),
    path("api/admin-regras-cobranca/", AdminRegrasCobrancaView.as_view()),
    path("api/admin-notificacoes/config/", AdminNotificacoesConfigView.as_view()),
    path("api/admin-notificacoes/enviar/", AdminNotificacoesEnviarView.as_view()),
    path("api/admin-notificacoes/historico/", AdminNotificacoesHistoricoView.as_view()),
    path("api/admin-notificacoes/chaves/", AdminNotificacoesChavesView.as_view()),
    path("api/admin-notificacoes/processar/", AdminNotificacoesProcessarView.as_view()),
    path("api/admin-cobrancas/<int:cobranca_id>/pagamentos/", AdminPagamentoView.as_view()),
    path("api/admin-pagamentos/<int:pagamento_id>/", AdminPagamentoView.as_view()),
    path("api/", include(router.urls)),
]
# Áudios do roteiro/TTS também servidos pelo Django: o agente os baixa pela rede interna
# (http://web:8000/media/...), que não passa pelo Caddy. Pelo domínio público o Caddy serve o mesmo volume.
urlpatterns += [
    re_path(r"^media/(?P<path>(?:tts|roteiro_audio)/[\w.-]+\.ogg)$", servir_media),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
