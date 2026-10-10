"""Apoio aos testes: conta de serviço do agente e cliente que manda as rotas do agente por ela.

Desde o HARDENING F1-03/F1-05, /incoming/, /delivery/ e /agente/* só aceitam a conta do grupo "agente", e o token fixo
precisa de validade. Testes antigos chamavam essas rotas com o usuário humano da própria classe; o ClienteRoteado
mantém esses testes como estão e só troca quem chama as rotas do agente."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APIClient

ROTAS_DO_AGENTE = ("/incoming/", "/delivery/", "/agente/")


def conta_de_agente(company, username=None):
    user = get_user_model().objects.create_user(username=username or f"agente.teste-{company.pk}")
    user.groups.add(Group.objects.get_or_create(name="agente")[0])
    company.members.add(user)
    return user


def token_de_agente(user, dias=30):
    """Token fixo com validade, como o Painel Admin gera para a conta do agente."""
    from rest_framework.authtoken.models import Token
    from .models import AgentTokenExpiry
    token, _ = Token.objects.get_or_create(user=user)
    AgentTokenExpiry.objects.update_or_create(token=token, defaults={"expires_at": timezone.now() + timedelta(days=dias)})
    return token.key


class ClienteRoteado:
    """Rotas do agente vão pela conta de serviço do agente; o resto, pelo cliente humano original. A conta do agente
    só é criada na primeira chamada a uma rota do agente (para não aparecer em testes que contam contas da empresa)."""
    def __init__(self, humano, company, agente=None):
        self.humano, self._company, self._agente_user, self._agente = humano, company, agente, None

    @property
    def agente(self):
        if self._agente is None:
            self._agente = APIClient()
            self._agente.force_authenticate(self._agente_user or conta_de_agente(self._company))
        return self._agente

    def _cliente(self, path):
        return self.agente if any(r in str(path) for r in ROTAS_DO_AGENTE) else self.humano

    def get(self, path, *a, **k): return self._cliente(path).get(path, *a, **k)
    def post(self, path, *a, **k): return self._cliente(path).post(path, *a, **k)
    def patch(self, path, *a, **k): return self._cliente(path).patch(path, *a, **k)
    def put(self, path, *a, **k): return self._cliente(path).put(path, *a, **k)
    def delete(self, path, *a, **k): return self._cliente(path).delete(path, *a, **k)
    def __getattr__(self, nome): return getattr(self.humano, nome)


def cliente_roteado(humano, company, agente=None):
    return ClienteRoteado(humano, company, agente)
