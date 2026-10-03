from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from rest_framework.authtoken.models import TokenProxy
from rest_framework.authtoken.admin import TokenAdmin
from .models import Company, Lead, Question, CompanyInfo, Event, Area, AtendenteInvite, PasswordChangeRequired, Profile, EmailChangeRequest

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ["name", "initial_state", "default_owner", "allow_transcription", "member_count"]
    list_filter = ["allow_transcription"]
    search_fields = ["name"]
    filter_horizontal = ["members"]
    fieldsets = [
        ("Dados gerais", {"fields": ["name", "initial_state", "default_owner", "allow_transcription"]}),
        ("Membros", {"fields": ["members"]}),
    ]
    @admin.display(description="Members")
    def member_count(self, obj):
        return obj.members.count()

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ["question_id", "company", "has_audio"]
    list_filter = ["company"]
    search_fields = ["question_id", "text"]
    @admin.display(description="Audio", boolean=True)
    def has_audio(self, obj):
        return bool(obj.audio_asset)

@admin.register(CompanyInfo)
class CompanyInfoAdmin(admin.ModelAdmin):
    list_display = ["title", "company", "updated_at"]
    list_filter = ["company"]
    search_fields = ["title", "content"]

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ["name", "contact", "company", "state", "mode", "priority", "temperature", "bot_closed"]
    list_filter = ["company", "mode", "bot_closed", "priority", "especialidade"]
    search_fields = ["name", "contact"]
    readonly_fields = ["id", "created_at", "last_contact", "last_audio_id"]

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["lead", "message_id", "summary", "delivery", "created_at"]
    list_filter = ["delivery"]
    search_fields = ["message_id", "summary"]
    readonly_fields = ["lead", "message_id", "created_at", "summary", "result", "delivery"]

@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ["name", "company"]
    list_filter = ["company"]
    search_fields = ["name"]

@admin.register(AtendenteInvite)
class AtendenteInviteAdmin(admin.ModelAdmin):
    list_display = ["name", "email", "company", "created_at", "expires_at", "verified_at", "attempts"]
    list_filter = ["company"]
    search_fields = ["name", "email"]
    readonly_fields = ["company", "name", "email", "code_hash", "created_at", "expires_at", "attempts", "verified_at"]

@admin.register(PasswordChangeRequired)
class PasswordChangeRequiredAdmin(admin.ModelAdmin):
    list_display = ["user"]
    search_fields = ["user__username"]

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "display_name"]
    search_fields = ["user__username", "display_name"]

@admin.register(EmailChangeRequest)
class EmailChangeRequestAdmin(admin.ModelAdmin):
    list_display = ["user", "new_email", "created_at", "expires_at", "confirmed_at", "attempts"]
    search_fields = ["user__username", "new_email"]
    readonly_fields = ["user", "new_email", "code_hash", "created_at", "expires_at", "attempts", "confirmed_at"]

# --- Usuários e tokens: reforça na UI a mesma restrição que já existe no backend
# (grupo "agente" só acessa /incoming/ e /delivery/ — ver crm/views.py NotAgentAccount) ---

class GroupListFilterUserAdmin(UserAdmin):
    list_display = UserAdmin.list_display + ("group_list",)
    @admin.display(description="Grupos")
    def group_list(self, obj):
        return ", ".join(g.name for g in obj.groups.all()) or "—"

admin.site.unregister(User)
admin.site.register(User, GroupListFilterUserAdmin)

class MaskedKeyTokenAdmin(TokenAdmin):
    list_display = ["masked_key", "user", "user_groups", "created"]
    @admin.display(description="Key")
    def masked_key(self, obj):
        return f"{obj.key[:8]}…{obj.key[-4:]}"
    @admin.display(description="Grupos")
    def user_groups(self, obj):
        return ", ".join(g.name for g in obj.user.groups.all()) or "—"

admin.site.unregister(TokenProxy)
admin.site.register(TokenProxy, MaskedKeyTokenAdmin)

# Reskin com a identidade da Conecta CRM -- ver templates/admin/base_site.html
# e crm/static/admin/conecta-admin.css (mesma paleta do frontend).
admin.site.site_header = "Conecta CRM"
admin.site.site_title = "Conecta CRM"
admin.site.index_title = "Painel administrativo"
