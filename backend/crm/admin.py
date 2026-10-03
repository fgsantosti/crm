from django.contrib import admin
from .models import Company, Lead, Question, Event
admin.site.register([Company, Lead, Question, Event])
