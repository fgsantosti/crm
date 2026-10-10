const base = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

export type Api = (path: string, init?: RequestInit) => Promise<any>;

/** Listas da API são paginadas (100 por página): segue `next` até o fim. */
export async function fetchTodasAsPaginas<T>(api: Api, path: string): Promise<T[]> {
  const todos: T[] = [];
  for (let page = 1; ; page++) {
    const d: { next: string | null; results: T[] } = await api(`${path}${path.includes('?') ? '&' : '?'}page=${page}`);
    todos.push(...d.results);
    if (!d.next) return todos;
  }
}

// O access token vive só em memória (nunca localStorage/sessionStorage): some
// ao recarregar a página, e volta via refresh silencioso usando o cookie
// httpOnly do refresh token, que o JavaScript nunca consegue ler (proteção
// contra roubo de sessão via um eventual XSS no frontend).
let accessToken = '';
let refreshPromise: Promise<string | null> | null = null;

function refreshAccessToken(): Promise<string | null> {
  // A renovação invalida o cookie anterior: chamadas simultâneas precisam
  // compartilhar o resultado, inclusive o login silencioso no StrictMode.
  if (refreshPromise) return refreshPromise;
  const renew = async (): Promise<string | null> => {
    try {
      const response = await fetch(`${base}/login/refresh/`, { method: 'POST', credentials: 'include' });
      if (!response.ok) return null;
      const data = await response.json();
      accessToken = data.access;
      return accessToken;
    } catch {
      return null;
    }
  };
  // Abas compartilham o cookie. Em navegadores com Web Locks, uma aba
  // aguarda a outra atualizar o cookie antes de iniciar sua renovação.
  const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined;
  refreshPromise = (locks ? locks.request('conecta-crm-session-refresh', renew) : renew())
    .finally(() => { refreshPromise = null; });
  return refreshPromise;
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
    const usedAccess = accessToken;
    let response = await doFetch(usedAccess);
    if (response.status === 401) {
      // Um 401 atrasado pode chegar depois que outra chamada já renovou.
      const newAccess = accessToken && accessToken !== usedAccess
        ? accessToken
        : await refreshAccessToken();
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
    const tipo = response.headers.get('Content-Type') || '';
    if (tipo.startsWith('application/pdf') || tipo.startsWith('image/')) return response.blob(); // comprovantes e anexos
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
export async function validarConvite(inviteId: string, code: string): Promise<{ detail: string }> {
  const response = await fetch(`${base}/convites/${inviteId}/validar/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || 'Não foi possível confirmar o código.');
  return data;
}
