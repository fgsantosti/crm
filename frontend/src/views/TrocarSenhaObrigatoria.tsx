import { useState } from 'react';
import { Logo } from '../components/Logo';
import { Spinner } from '../components/Skeleton';
import type { Api } from '../api';

export function TrocarSenhaObrigatoria({ api, onDone, onLogout }: { api: Api; onDone: () => void; onLogout: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const currentPassword = String(form.get('current_password') || '');
    const password = String(form.get('password') || '');
    const confirm = String(form.get('confirm') || '');
    if (password !== confirm) {
      setError('As senhas não coincidem.');
      return;
    }
    if (password.length < 8) {
      setError('A senha deve ter ao menos 8 caracteres.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await api('/trocar-senha/', { method: 'POST', body: JSON.stringify({ current_password: currentPassword, password }) });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-shell">
      <div className="login-form-side">
        <form onSubmit={submit}>
          <Logo size={64} />
          <h1>Conecta CRM</h1>
          <p className="tagline">Defina sua senha definitiva para continuar.</p>
          {error && (
            <p role="alert" className="login-error">
              {error}
            </p>
          )}
          <label>
            Senha provisória recebida por e-mail
            <input name="current_password" type="password" autoComplete="current-password" required />
          </label>
          <label>
            Nova senha
            <input name="password" type="password" autoComplete="new-password" required minLength={8} />
          </label>
          <label>
            Confirmar nova senha
            <input name="confirm" type="password" autoComplete="new-password" required minLength={8} />
          </label>
          <button disabled={busy} style={{ width: '100%', marginTop: 16 }}>
            {busy && <Spinner />}
            {busy ? 'Salvando…' : 'Definir senha →'}
          </button>
          <button type="button" className="secondary" style={{ width: '100%', marginTop: 10 }} onClick={onLogout}>
            Sair
          </button>
        </form>
      </div>
      <div className="login-illustration-side">
        <div className="glow" />
        <div className="dots" />
        <div className="content">
          <h2>Por segurança, só mais um passo.</h2>
          <p>A senha provisória que chegou no seu e-mail só vale para o primeiro acesso.</p>
        </div>
      </div>
    </div>
  );
}
