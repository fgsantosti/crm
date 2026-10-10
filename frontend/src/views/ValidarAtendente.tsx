import { useState } from 'react';
import { Logo } from '../components/Logo';
import { Spinner } from '../components/Skeleton';
import { validarConvite } from '../api';

export function ValidarAtendente({ inviteId }: { inviteId: string }) {
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await validarConvite(inviteId, code);
      setDone(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-shell">
      <div className="login-form-side">
        {done ? (
          <div>
            <Logo size={64} />
            <h1>Conecta Axioma CRM</h1>
            <p className="tagline">Cadastro confirmado!</p>
            <p style={{ marginTop: 20 }}>
              Enviamos a senha provisória de acesso para o seu e-mail. Você vai precisar definir uma senha nova no
              primeiro login.
            </p>
          </div>
        ) : (
          <form onSubmit={submit}>
            <Logo size={64} />
            <h1>Conecta Axioma CRM</h1>
            <p className="tagline">Confirme seu cadastro na equipe.</p>
            {error && (
              <p role="alert" className="login-error">
                {error}
              </p>
            )}
            <label>
              Código recebido por e-mail
              <input
                name="code"
                inputMode="numeric"
                pattern="\d{6}"
                maxLength={6}
                placeholder="000000"
                required
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                style={{ fontFamily: "'DM Mono',monospace", fontSize: 20, textAlign: 'center', letterSpacing: 4 }}
              />
            </label>
            <button disabled={busy} style={{ width: '100%', marginTop: 16 }}>
              {busy && <Spinner />}
              {busy ? 'Confirmando…' : 'Confirmar código →'}
            </button>
          </form>
        )}
      </div>
      <div className="login-illustration-side">
        <div className="glow" />
        <div className="dots" />
        <div className="content">
          <h2>Quase lá.</h2>
          <p>Confirme o código enviado para o seu e-mail e receba suas credenciais de acesso ao CRM.</p>
        </div>
      </div>
    </div>
  );
}
