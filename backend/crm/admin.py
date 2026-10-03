from django.contrib import admin
from .models import Company, Lead, Question, CompanyInfo, Event
admin.site.register([Company, Lead, Question, CompanyInfo, Event])
