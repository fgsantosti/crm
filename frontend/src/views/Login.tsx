import { useState } from 'react';
import { Logo } from '../components/Logo';
import { Spinner } from '../components/Skeleton';
import { login } from '../api';

export function Login({ onLogin }: { onLogin: () => void }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError('');
    const form = new FormData(e.currentTarget);
    try {
      await login(String(form.get('username')), String(form.get('password')));
      onLogin();
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
          <p className="tagline">Conversas que se tornam oportunidades.</p>
          {error && (
            <p role="alert" className="login-error">
              {error}
            </p>
          )}
          <label>
            Usuário
            <input name="username" autoComplete="username" required />
          </label>
          <label>
            Senha
            <input name="password" type="password" autoComplete="current-password" required />
          </label>
          <button disabled={busy} style={{ width: '100%', marginTop: 16 }}>
            {busy && <Spinner />}
            {busy ? 'Entrando…' : 'Entrar no CRM →'}
          </button>
          <p style={{ marginTop: 20, fontSize: 13, color: '#A8957F' }}>Acesso restrito a contas vinculadas por administrador.</p>
        </form>
      </div>
      <div className="login-illustration-side">
        <div className="glow" />
        <div className="dots" />
        <div className="content">
          <h2>Da primeira mensagem ao negócio fechado.</h2>
          <p>O roteiro aprovado qualifica cada contato pelo WhatsApp e entrega ao time só o que já está pronto para avançar.</p>
        </div>
      </div>
    </div>
  );
}
