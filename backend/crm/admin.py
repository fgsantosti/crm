from datetime import timedelta
from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.authtoken.models import TokenProxy
from rest_framework.authtoken.admin import TokenAdmin
from .models import Company, Lead, Question, CompanyInfo, Event, Area, AtendenteInvite, PasswordChangeRequired, Profile, EmailChangeRequest, AgentTokenExpiry, default_token_expiry, Variavel, VariavelRoteiro

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ["name", "initial_state", "numero_agente", "allow_transcription", "member_count"]
    list_filter = ["allow_transcription"]
    search_fields = ["name"]
    filter_horizontal = ["members"]
    fieldsets = [
        ("Dados gerais", {"fields": ["name", "initial_state", "numero_agente", "allow_transcription"]}),
        ("Membros", {"fields": ["members"]}),
    ]
    @admin.display(description="Members")
    def member_count(self, obj):
        return obj.members.count()

@admin.register(Variavel)
class VariavelAdmin(admin.ModelAdmin):
    list_display = ["name", "company", "peso"]
    list_filter = ["company"]
    search_fields = ["name"]

@admin.register(VariavelRoteiro)
class VariavelRoteiroAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "company", "builtin", "cor"]
    list_filter = ["company", "builtin"]
    search_fields = ["name", "slug"]

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ["question_id", "company", "obrigatoria", "variavel", "variavel_roteiro", "has_audio"]
    list_filter = ["company", "obrigatoria"]
    search_fields = ["question_id", "text"]
    @admin.display(description="Audio", boolean=True)
    def has_audio(self, obj):
        return bool(obj.audio_asset)

@admin.register(CompanyInfo)
class CompanyInfoAdmin(admin.ModelAdmin):
    list_display = ["title", "company", "obrigatorio", "updated_at"]
    list_filter = ["company", "obrigatorio"]
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

MAX_TOKEN_VALIDITY = timedelta(days=730)  # 2 anos

class AgentTokenExpiryForm(forms.ModelForm):
    class Meta:
        model = AgentTokenExpiry
        fields = ["expires_at"]
    def clean_expires_at(self):
        expires_at = self.cleaned_data["expires_at"]
        if expires_at <= timezone.now():
            raise forms.ValidationError("A validade precisa ser uma data futura.")
        if expires_at > timezone.now() + MAX_TOKEN_VALIDITY:
            raise forms.ValidationError("A validade não pode passar de 2 anos a partir de hoje.")
        return expires_at

class AgentTokenExpiryInline(admin.StackedInline):
    """Validade por tempo do token: padrão 6 meses, até 2 anos (ver AgentTokenExpiryForm).
    Deixar sem preencher = token sem validade (comportamento antigo, permanente)."""
    model = AgentTokenExpiry
    form = AgentTokenExpiryForm
    extra = 0
    max_num = 1
    can_delete = True

class MaskedKeyTokenAdmin(TokenAdmin):
    list_display = ["masked_key", "user", "user_groups", "created", "validade"]
    inlines = [AgentTokenExpiryInline]
    @admin.display(description="Key")
    def masked_key(self, obj):
        return f"{obj.key[:8]}…{obj.key[-4:]}"
    @admin.display(description="Grupos")
    def user_groups(self, obj):
        return ", ".join(g.name for g in obj.user.groups.all()) or "—"
    @admin.display(description="Validade")
    def validade(self, obj):
        expiry = getattr(obj, "expiry", None)
        if not expiry:
            return "Sem validade"
        if expiry.expires_at < timezone.now():
            return f"Expirado em {expiry.expires_at:%d/%m/%Y}"
        return f"Expira em {expiry.expires_at:%d/%m/%Y}"

admin.site.unregister(TokenProxy)
admin.site.register(TokenProxy, MaskedKeyTokenAdmin)

# Reskin com a identidade da Conecta CRM -- ver templates/admin/base_site.html
# e crm/static/admin/conecta-admin.css (mesma paleta do frontend).
admin.site.site_header = "Conecta CRM"
admin.site.site_title = "Conecta CRM"
admin.site.index_title = "Painel administrativo"
