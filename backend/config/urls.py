from .health import ready
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from crm.views import (
    CompanyViewSet, LeadViewSet, QuestionViewSet, CompanyInfoViewSet, AreaViewSet, AtendenteInviteViewSet,
    me, avatar, validar_convite, trocar_senha, trocar_email_solicitar, trocar_email_confirmar, excluir_conta, logout_view,
)
router = DefaultRouter()
router.register("companies", CompanyViewSet, basename="company")
router.register("leads", LeadViewSet)
router.register("questions", QuestionViewSet)
router.register("company-info", CompanyInfoViewSet, basename="companyinfo")
router.register("areas", AreaViewSet, basename="area")
router.register("convites", AtendenteInviteViewSet, basename="convite")
urlpatterns = [
    path("health/ready/", ready),
    path("admin/", admin.site.urls),
    # Humanos (frontend): JWT access + refresh. O agente Axioma usa um token
    # fixo (TokenAuthentication) pré-provisionado via Django shell/admin, nunca
    # passa por aqui -- ver docs/integracao-agente.md.
    path("api/login/", TokenObtainPairView.as_view()),
    path("api/login/refresh/", TokenRefreshView.as_view()),
    path("api/logout/", logout_view),
    path("api/me/", me),
    path("api/me/avatar/", avatar),
    path("api/me/email/", trocar_email_solicitar),
    path("api/me/email/confirmar/", trocar_email_confirmar),
    path("api/me/excluir/", excluir_conta),
    path("api/trocar-senha/", trocar_senha),
    path("api/convites/<int:pk>/validar/", validar_convite),
    path("api/", include(router.urls)),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
