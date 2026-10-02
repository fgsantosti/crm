from django.contrib import admin
from .models import Company, Lead, Step, Event
admin.site.register([Company, Lead, Step, Event])
