from .health import ready
from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.authtoken.views import obtain_auth_token
from crm.views import CompanyViewSet, LeadViewSet, QuestionViewSet, CompanyInfoViewSet, AreaViewSet, AtendenteInviteViewSet, me, validar_convite, trocar_senha
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
    path("api/login/", obtain_auth_token),
    path("api/me/", me),
    path("api/trocar-senha/", trocar_senha),
    path("api/convites/<int:pk>/validar/", validar_convite),
    path("api/", include(router.urls)),
]
