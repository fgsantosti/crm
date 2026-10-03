const base = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

export type Api = (path: string, init?: RequestInit) => Promise<any>;

export function apiFactory(token: string): Api {
  return async function api(path: string, init: RequestInit = {}) {
    const response = await fetch(`${base}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', Authorization: `Token ${token}`, ...init.headers },
    });
    if (!response.ok) {
      throw new Error(response.status === 401 ? 'Sessão inválida. Entre novamente.' : `Não foi possível concluir a operação (${response.status}).`);
    }
    return response.json();
  };
}

export async function login(username: string, password: string): Promise<string> {
  const response = await fetch(`${base}/login/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) throw new Error('Confira seu usuário e senha.');
  return (await response.json()).token;
}
