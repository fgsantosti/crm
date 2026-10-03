import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Api } from '../api';
import type { Me } from '../types';
import { Spinner } from './Skeleton';

type Section = 'menu' | 'nome' | 'email' | 'email-code' | 'senha' | 'excluir';

function Avatar({ me, size }: { me: Me; size: number }) {
  const initials = (me.display_name || me.username).trim().slice(0, 2).toUpperCase();
  if (me.avatar_url) {
    return <img src={me.avatar_url} alt="" style={{ width: size, height: size, borderRadius: '50%', objectFit: 'cover', display: 'block' }} />;
  }
  return (
    <span
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--accent)',
        color: '#fff',
        fontWeight: 700,
        fontSize: size * 0.4,
        fontFamily: "'DM Sans',sans-serif",
      }}
    >
      {initials}
    </span>
  );
}

export function ProfileMenu({
  api,
  me,
  onMeChange,
  onAccountDeleted,
}: {
  api: Api;
  me: Me;
  onMeChange: (patch: Partial<Me>) => void;
  onAccountDeleted: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [section, setSection] = useState<Section>('menu');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [coords, setCoords] = useState({ top: 0, left: 0 });
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      const target = e.target as Node;
      if (buttonRef.current?.contains(target)) return;
      if (popupRef.current?.contains(target)) return;
      close();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') close();
    }
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  function close() {
    setOpen(false);
    setSection('menu');
    setError('');
    setNotice('');
  }

  function toggle() {
    if (open) {
      close();
      return;
    }
    const rect = buttonRef.current?.getBoundingClientRect();
    if (rect) setCoords({ top: rect.top - 8, left: rect.left });
    setOpen(true);
  }

  async function uploadAvatar(file: File) {
    setBusy(true);
    setError('');
    const form = new FormData();
    form.append('avatar', file);
    try {
      const data = await api('/me/avatar/', { method: 'POST', body: form });
      onMeChange({ avatar_url: data.avatar_url });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function removeAvatar() {
    setBusy(true);
    setError('');
    try {
      await api('/me/avatar/', { method: 'DELETE' });
      onMeChange({ avatar_url: null });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveNome(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError('');
    const form = new FormData(e.currentTarget);
    try {
      const data = await api('/me/', { method: 'PATCH', body: JSON.stringify({ display_name: form.get('display_name') }) });
      onMeChange({ display_name: data.display_name });
      setSection('menu');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function solicitarEmail(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError('');
    const form = new FormData(e.currentTarget);
    try {
      await api('/me/email/', { method: 'POST', body: JSON.stringify({ email: form.get('email') }) });
      setSection('email-code');
      setNotice('Enviamos um código de confirmação para o e-mail novo.');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function confirmarEmail(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError('');
    const form = new FormData(e.currentTarget);
    try {
      await api('/me/email/confirmar/', { method: 'POST', body: JSON.stringify({ code: form.get('code') }) });
      const data = await api('/me/');
      onMeChange({ email: data.email });
      setSection('menu');
      setNotice('E-mail atualizado.');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function salvarSenha(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const current = String(form.get('current_password') || '');
    const nova = String(form.get('password') || '');
    const confirm = String(form.get('confirm') || '');
    if (nova !== confirm) {
      setError('As senhas não coincidem.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await api('/trocar-senha/', { method: 'POST', body: JSON.stringify({ current_password: current, password: nova }) });
      setSection('menu');
      setNotice('Senha atualizada.');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function excluirConta(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError('');
    try {
      await api('/me/excluir/', { method: 'DELETE', body: JSON.stringify({ password: form.get('password') }) });
      onAccountDeleted();
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={toggle}
        aria-label="Abrir menu de perfil"
        style={{ border: 'none', background: 'none', padding: 0, cursor: 'pointer', borderRadius: '50%', lineHeight: 0 }}
      >
        <Avatar me={me} size={38} />
      </button>

      {open &&
        createPortal(
          <div
            ref={popupRef}
            className="panel"
            style={{
              position: 'fixed',
              top: coords.top,
              left: coords.left,
              transform: 'translateY(-100%)',
              width: 280,
              padding: 18,
              zIndex: 1000,
              boxShadow: '0 12px 30px rgba(0,0,0,0.25)',
            }}
          >
          {section === 'menu' && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
                <Avatar me={me} size={44} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {me.display_name || me.username}
                  </div>
                  <small style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--muted)' }}>
                    {me.email || me.username}
                  </small>
                </div>
              </div>
              {notice && <p style={{ fontSize: 12.5, color: 'var(--muted)', marginBottom: 10 }}>{notice}</p>}
              <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" style={{ display: 'none' }} onChange={(e) => e.target.files?.[0] && uploadAvatar(e.target.files[0])} />
              <button type="button" className="secondary" style={{ width: '100%', marginBottom: 6 }} onClick={() => fileRef.current?.click()} disabled={busy}>
                {busy && <Spinner />}
                Trocar foto
              </button>
              {me.avatar_url && (
                <button type="button" className="secondary" style={{ width: '100%', marginBottom: 6 }} onClick={removeAvatar} disabled={busy}>
                  Remover foto
                </button>
              )}
              <button type="button" className="secondary" style={{ width: '100%', marginBottom: 6 }} onClick={() => setSection('nome')}>
                Editar nome
              </button>
              <button type="button" className="secondary" style={{ width: '100%', marginBottom: 6 }} onClick={() => setSection('email')}>
                Trocar e-mail
              </button>
              <button type="button" className="secondary" style={{ width: '100%', marginBottom: 6 }} onClick={() => setSection('senha')}>
                Trocar senha
              </button>
              <div className="section-divider" />
              <button type="button" className="danger-outline" style={{ width: '100%' }} onClick={() => setSection('excluir')}>
                Excluir conta
              </button>
            </>
          )}

          {section === 'nome' && (
            <form onSubmit={saveNome}>
              <label style={{ margin: 0 }}>
                Nome de exibição
                <input name="display_name" defaultValue={me.display_name} autoFocus />
              </label>
              {error && <p className="error">{error}</p>}
              <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                <button disabled={busy}>
                  {busy && <Spinner />}
                  Salvar
                </button>
                <button type="button" className="secondary" onClick={() => setSection('menu')}>
                  Voltar
                </button>
              </div>
            </form>
          )}

          {section === 'email' && (
            <form onSubmit={solicitarEmail}>
              <p style={{ fontSize: 12.5, color: 'var(--muted)', marginBottom: 10 }}>
                Vamos enviar um código de confirmação para o e-mail novo antes de trocar.
              </p>
              <label style={{ margin: 0 }}>
                Novo e-mail
                <input name="email" type="email" required autoFocus />
              </label>
              {error && <p className="error">{error}</p>}
              <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                <button disabled={busy}>
                  {busy && <Spinner />}
                  Enviar código
                </button>
                <button type="button" className="secondary" onClick={() => setSection('menu')}>
                  Voltar
                </button>
              </div>
            </form>
          )}

          {section === 'email-code' && (
            <form onSubmit={confirmarEmail}>
              {notice && <p style={{ fontSize: 12.5, color: 'var(--muted)', marginBottom: 10 }}>{notice}</p>}
              <label style={{ margin: 0 }}>
                Código recebido
                <input name="code" inputMode="numeric" pattern="\d{6}" maxLength={6} required autoFocus style={{ fontFamily: "'DM Mono',monospace" }} />
              </label>
              {error && <p className="error">{error}</p>}
              <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                <button disabled={busy}>
                  {busy && <Spinner />}
                  Confirmar
                </button>
                <button type="button" className="secondary" onClick={() => setSection('menu')}>
                  Voltar
                </button>
              </div>
            </form>
          )}

          {section === 'senha' && (
            <form onSubmit={salvarSenha}>
              <label style={{ margin: 0 }}>
                Senha atual
                <input name="current_password" type="password" autoComplete="current-password" required autoFocus />
              </label>
              <label>
                Nova senha
                <input name="password" type="password" autoComplete="new-password" required minLength={8} />
              </label>
              <label>
                Confirmar nova senha
                <input name="confirm" type="password" autoComplete="new-password" required minLength={8} />
              </label>
              {error && <p className="error">{error}</p>}
              <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                <button disabled={busy}>
                  {busy && <Spinner />}
                  Salvar
                </button>
                <button type="button" className="secondary" onClick={() => setSection('menu')}>
                  Voltar
                </button>
              </div>
            </form>
          )}

          {section === 'excluir' && (
            <form onSubmit={excluirConta}>
              <p style={{ fontSize: 12.5, color: 'var(--danger, #c0392b)', marginBottom: 10 }}>
                Isso remove sua conta e o acesso ao CRM permanentemente. Não pode ser desfeito.
              </p>
              <label style={{ margin: 0 }}>
                Confirme sua senha
                <input name="password" type="password" autoComplete="current-password" required autoFocus />
              </label>
              {error && <p className="error">{error}</p>}
              <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                <button type="submit" className="danger-outline" disabled={busy}>
                  {busy && <Spinner />}
                  Excluir conta
                </button>
                <button type="button" className="secondary" onClick={() => setSection('menu')}>
                  Cancelar
                </button>
              </div>
            </form>
          )}
          </div>,
          document.body,
        )}
    </>
  );
}
