const base = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

export type Api = (path: string, init?: RequestInit) => Promise<any>;

const ACCESS_KEY = 'conecta_access_token';
const REFRESH_KEY = 'conecta_refresh_token';

export function storeTokens(access: string, refresh: string) {
  localStorage.setItem(ACCESS_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export function hasSession(): boolean {
  return !!localStorage.getItem(REFRESH_KEY);
}

async function refreshAccessToken(): Promise<string | null> {
  const refresh = localStorage.getItem(REFRESH_KEY);
  if (!refresh) return null;
  try {
    const response = await fetch(`${base}/login/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh }),
    });
    if (!response.ok) return null;
    const data = await response.json();
    localStorage.setItem(ACCESS_KEY, data.access);
    // ROTATE_REFRESH_TOKENS=True no backend: cada refresh devolve um refresh novo.
    if (data.refresh) localStorage.setItem(REFRESH_KEY, data.refresh);
    return data.access;
  } catch {
    return null;
  }
}

/** `onSessionExpired` é chamado quando o access token expira E o refresh também falha (sessão morta de verdade). */
export function apiFactory(onSessionExpired: () => void): Api {
  return async function api(path: string, init: RequestInit = {}) {
    const isFormData = init.body instanceof FormData;
    async function doFetch(token: string) {
      return fetch(`${base}${path}`, {
        ...init,
        headers: {
          ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
          Authorization: `Bearer ${token}`,
          ...init.headers,
        },
      });
    }
    let response = await doFetch(localStorage.getItem(ACCESS_KEY) || '');
    if (response.status === 401) {
      const newAccess = await refreshAccessToken();
      if (!newAccess) {
        clearTokens();
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
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) throw new Error('Confira seu usuário e senha.');
  const data = await response.json();
  storeTokens(data.access, data.refresh);
}

export async function logoutRequest(): Promise<void> {
  const refresh = localStorage.getItem(REFRESH_KEY);
  if (!refresh) return;
  try {
    await fetch(`${base}/logout/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem(ACCESS_KEY) || ''}` },
      body: JSON.stringify({ refresh }),
    });
  } catch {
    // Best-effort: mesmo se a chamada falhar, o logout local (clearTokens) já desloga este navegador.
  }
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
