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
        {/* imagem esmaecida: watermark ampliado do mesmo motivo de conexões da ilustração
            principal, atrás dos glows e da textura de pontos já existentes */}
        <svg className="watermark" width="860" height="860" viewBox="0 0 320 220" fill="none" aria-hidden="true">
          <circle cx="70" cy="60" r="34" fill="#F3E9DD" />
          <circle cx="150" cy="118" r="30" fill="#F3E9DD" />
          <circle cx="60" cy="168" r="26" fill="#F3E9DD" />
          <line x1="94" y1="74" x2="128" y2="104" stroke="#F3E9DD" strokeWidth="2" />
          <line x1="128" y1="134" x2="80" y2="156" stroke="#F3E9DD" strokeWidth="2" />
          <line x1="178" y1="112" x2="238" y2="100" stroke="#F3E9DD" strokeWidth="2" />
          <circle cx="252" cy="96" r="40" fill="#F3E9DD" />
        </svg>
        <div className="glow" />
        <div className="dots" />
        <div className="content">
          <svg width="100%" height="220" viewBox="0 0 320 220" fill="none" aria-hidden="true" style={{ display: 'block', margin: '0 auto 28px' }}>
            <circle cx="70" cy="60" r="34" fill="#352416" stroke="#4A3321" />
            <circle cx="70" cy="60" r="6" fill="#D9531A" />
            <circle cx="150" cy="118" r="30" fill="#352416" stroke="#4A3321" />
            <circle cx="150" cy="118" r="5" fill="#D9531A" />
            <circle cx="60" cy="168" r="26" fill="#352416" stroke="#4A3321" />
            <circle cx="60" cy="168" r="5" fill="#D9531A" />
            <line x1="94" y1="74" x2="128" y2="104" stroke="#6B5540" strokeWidth="2" strokeDasharray="3 5" />
            <line x1="128" y1="134" x2="80" y2="156" stroke="#6B5540" strokeWidth="2" strokeDasharray="3 5" />
            <line x1="178" y1="112" x2="238" y2="100" stroke="#6B5540" strokeWidth="2" strokeDasharray="3 5" />
            <circle cx="252" cy="96" r="40" fill="#D9531A" />
            <path d="M236 96l10 10 20-22" stroke="#241A12" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
          </svg>
          <h2>Da primeira mensagem ao negócio fechado.</h2>
          <p>O roteiro aprovado qualifica cada contato pelo WhatsApp e entrega ao time só o que já está pronto para avançar.</p>
        </div>
      </div>
    </div>
  );
}
