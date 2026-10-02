from .health import ready
from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.authtoken.views import obtain_auth_token
from crm.views import CompanyViewSet, LeadViewSet, StepViewSet
router = DefaultRouter()
router.register("companies", CompanyViewSet, basename="company")
router.register("leads", LeadViewSet)
router.register("steps", StepViewSet)
urlpatterns = [path("health/ready/", ready), path("admin/", admin.site.urls), path("api/login/", obtain_auth_token), path("api/", include(router.urls))]
