from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication

class ExpiringTokenAuthentication(TokenAuthentication):
    """Token fixo só para a conta de serviço do agente (grupo "agente") e sempre com validade (AgentTokenExpiry).

    Humanos usam JWT. Um Token DRF de outro usuário (ex.: criado à mão no Django Admin para uma conta Empresa)
    não autentica, e token de agente sem linha de validade é tratado como expirado: antes ele valia para sempre
    e com os poderes da conta (HARDENING F1-03)."""
    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if not user.groups.filter(name="agente").exists():
            raise exceptions.AuthenticationFailed("Token inválido.")
        expiry = getattr(token, "expiry", None)
        if expiry is None or expiry.expires_at < timezone.now():
            raise exceptions.AuthenticationFailed("Token expirado.")
        return user, token
