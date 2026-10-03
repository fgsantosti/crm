import { useState } from 'react';
import { Logo } from '../components/Logo';
import { Spinner } from '../components/Skeleton';
import { login, type Api } from '../api';
import type { Me } from '../types';

type Step = 'reauth' | 'form';

export function TrocarSenhaPagina({ api, me, onDone, onCancel }: { api: Api; me: Me; onDone: () => void; onCancel: () => void }) {
  const [step, setStep] = useState<Step>('reauth');
  const [currentPassword, setCurrentPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function reauth(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const password = String(form.get('password') || '');
    setBusy(true);
    setError('');
    try {
      await login(me.username, password);
      setCurrentPassword(password);
      setStep('form');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function salvar(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const nova = String(form.get('password') || '');
    const confirm = String(form.get('confirm') || '');
    if (nova !== confirm) {
      setError('As senhas não coincidem.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await api('/trocar-senha/', { method: 'POST', body: JSON.stringify({ current_password: currentPassword, password: nova }) });
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
        {step === 'reauth' ? (
          <form onSubmit={reauth}>
            <Logo size={64} />
            <h1>Conecta CRM</h1>
            <p className="tagline">Confirme sua senha para continuar.</p>
            {error && (
              <p role="alert" className="login-error">
                {error}
              </p>
            )}
            <label>
              Usuário
              <input value={me.username} disabled />
            </label>
            <label>
              Senha atual
              <input name="password" type="password" autoComplete="current-password" required autoFocus />
            </label>
            <button disabled={busy} style={{ width: '100%', marginTop: 16 }}>
              {busy && <Spinner />}
              {busy ? 'Confirmando…' : 'Continuar →'}
            </button>
            <button type="button" className="secondary" style={{ width: '100%', marginTop: 10 }} onClick={onCancel}>
              Cancelar
            </button>
          </form>
        ) : (
          <form onSubmit={salvar}>
            <Logo size={64} />
            <h1>Conecta CRM</h1>
            <p className="tagline">Defina sua nova senha.</p>
            {error && (
              <p role="alert" className="login-error">
                {error}
              </p>
            )}
            <label>
              Nova senha
              <input name="password" type="password" autoComplete="new-password" required minLength={8} autoFocus />
            </label>
            <label>
              Confirmar nova senha
              <input name="confirm" type="password" autoComplete="new-password" required minLength={8} />
            </label>
            <button disabled={busy} style={{ width: '100%', marginTop: 16 }}>
              {busy && <Spinner />}
              {busy ? 'Salvando…' : 'Salvar nova senha →'}
            </button>
            <button type="button" className="secondary" style={{ width: '100%', marginTop: 10 }} onClick={onCancel}>
              Cancelar
            </button>
          </form>
        )}
      </div>
      <div className="login-illustration-side">
        <div className="glow" />
        <div className="dots" />
        <div className="content">
          <h2>Sua segurança em primeiro lugar.</h2>
          <p>Confirmamos sua identidade antes de qualquer alteração sensível na conta.</p>
        </div>
      </div>
    </div>
  );
}
