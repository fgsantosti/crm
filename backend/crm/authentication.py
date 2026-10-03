from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication

class ExpiringTokenAuthentication(TokenAuthentication):
    """Igual ao TokenAuthentication padrão do DRF, só que respeita
    AgentTokenExpiry quando existe uma linha para o token (ver crm/models.py).
    Sem essa linha, o token nunca expira -- mesmo comportamento de sempre."""
    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        expiry = getattr(token, "expiry", None)
        if expiry and expiry.expires_at < timezone.now():
            raise exceptions.AuthenticationFailed("Token expirado.")
        return user, token
