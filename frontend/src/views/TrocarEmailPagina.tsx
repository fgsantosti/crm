import { useState } from 'react';
import { Logo } from '../components/Logo';
import { Spinner } from '../components/Skeleton';
import { login, type Api } from '../api';
import type { Me } from '../types';

type Step = 'reauth' | 'email' | 'code';

export function TrocarEmailPagina({ api, me, onDone, onCancel }: { api: Api; me: Me; onDone: (email: string) => void; onCancel: () => void }) {
  const [step, setStep] = useState<Step>('reauth');
  const [novoEmail, setNovoEmail] = useState('');
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
      setStep('email');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function solicitar(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const email = String(form.get('email') || '');
    setBusy(true);
    setError('');
    try {
      await api('/me/email/', { method: 'POST', body: JSON.stringify({ email }) });
      setNovoEmail(email);
      setStep('code');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function confirmar(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError('');
    try {
      await api('/me/email/confirmar/', { method: 'POST', body: JSON.stringify({ code: form.get('code') }) });
      onDone(novoEmail);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-shell">
      <div className="login-form-side">
        {step === 'reauth' && (
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
        )}

        {step === 'email' && (
          <form onSubmit={solicitar}>
            <Logo size={64} />
            <h1>Conecta CRM</h1>
            <p className="tagline">Qual é o novo e-mail?</p>
            {error && (
              <p role="alert" className="login-error">
                {error}
              </p>
            )}
            <label>
              Novo e-mail
              <input name="email" type="email" required autoFocus defaultValue={me.email} />
            </label>
            <button disabled={busy} style={{ width: '100%', marginTop: 16 }}>
              {busy && <Spinner />}
              {busy ? 'Enviando…' : 'Enviar código →'}
            </button>
            <button type="button" className="secondary" style={{ width: '100%', marginTop: 10 }} onClick={onCancel}>
              Cancelar
            </button>
          </form>
        )}

        {step === 'code' && (
          <form onSubmit={confirmar}>
            <Logo size={64} />
            <h1>Conecta CRM</h1>
            <p className="tagline">Enviamos um código de confirmação para {novoEmail}.</p>
            {error && (
              <p role="alert" className="login-error">
                {error}
              </p>
            )}
            <label>
              Código recebido
              <input name="code" inputMode="numeric" pattern="\d{6}" maxLength={6} required autoFocus style={{ fontFamily: "'DM Mono',monospace" }} />
            </label>
            <button disabled={busy} style={{ width: '100%', marginTop: 16 }}>
              {busy && <Spinner />}
              {busy ? 'Confirmando…' : 'Confirmar →'}
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
