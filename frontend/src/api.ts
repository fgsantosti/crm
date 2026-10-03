const base = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

export type Api = (path: string, init?: RequestInit) => Promise<any>;

// O access token vive só em memória (nunca localStorage/sessionStorage): some
// ao recarregar a página, e volta via refresh silencioso usando o cookie
// httpOnly do refresh token, que o JavaScript nunca consegue ler (proteção
// contra roubo de sessão via um eventual XSS no frontend).
let accessToken = '';

async function refreshAccessToken(): Promise<string | null> {
  try {
    const response = await fetch(`${base}/login/refresh/`, { method: 'POST', credentials: 'include' });
    if (!response.ok) return null;
    const data = await response.json();
    accessToken = data.access;
    return accessToken;
  } catch {
    return null;
  }
}

/** Tenta restaurar a sessão a partir do cookie de refresh (ex.: ao abrir a página). */
export async function trySilentLogin(): Promise<boolean> {
  return !!(await refreshAccessToken());
}

/** `onSessionExpired` é chamado quando o access token expira E o refresh via cookie também falha (sessão morta de verdade). */
export function apiFactory(onSessionExpired: () => void): Api {
  return async function api(path: string, init: RequestInit = {}) {
    const isFormData = init.body instanceof FormData;
    async function doFetch(token: string) {
      return fetch(`${base}${path}`, {
        ...init,
        credentials: 'include',
        headers: {
          ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
          Authorization: `Bearer ${token}`,
          ...init.headers,
        },
      });
    }
    let response = await doFetch(accessToken);
    if (response.status === 401) {
      const newAccess = await refreshAccessToken();
      if (!newAccess) {
        accessToken = '';
        onSessionExpired();
        throw new Error('Sessão expirada. Entre novamente.');
      }
      response = await doFetch(newAccess);
    }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || `Não foi possível concluir a operação (${response.status}).`);
    }
    if (response.status === 204) return null;
    return response.json().catch(() => null);
  };
}

export async function login(username: string, password: string): Promise<void> {
  const response = await fetch(`${base}/login/`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) throw new Error('Confira seu usuário e senha.');
  const data = await response.json();
  accessToken = data.access;
}

export async function logoutRequest(): Promise<void> {
  try {
    await fetch(`${base}/logout/`, {
      method: 'POST',
      credentials: 'include',
      headers: { Authorization: `Bearer ${accessToken}` },
    });
  } catch {
    // Best-effort: mesmo se a chamada falhar, zerar accessToken abaixo já desloga este navegador.
  }
  accessToken = '';
}

// Sem token: o atendente ainda não tem conta nesse ponto do fluxo de convite.
export async function validarConvite(inviteId: number, code: string): Promise<{ detail: string }> {
  const response = await fetch(`${base}/convites/${inviteId}/validar/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || 'Não foi possível confirmar o código.');
  return data;
}
