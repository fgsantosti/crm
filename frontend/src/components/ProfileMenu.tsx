import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Api } from '../api';
import type { Me } from '../types';
import { Spinner } from './Skeleton';

type Section = 'menu' | 'nome' | 'excluir';

export function Avatar({ me, size }: { me: Pick<Me, 'display_name' | 'username' | 'avatar_url'>; size: number }) {
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
  onOpenTrocarEmail,
  onOpenTrocarSenha,
}: {
  api: Api;
  me: Me;
  onMeChange: (patch: Partial<Me>) => void;
  onAccountDeleted: () => void;
  onOpenTrocarEmail: () => void;
  onOpenTrocarSenha: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [section, setSection] = useState<Section>('menu');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const buttonRef = useRef<HTMLButtonElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') close();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);

  function close() {
    setOpen(false);
    setSection('menu');
    setError('');
  }

  function toggle() {
    if (open) close();
    else setOpen(true);
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
            onMouseDown={(e) => {
              if (e.target === e.currentTarget) close();
            }}
            style={{
              position: 'fixed',
              inset: 0,
              background: 'rgba(20,14,9,0.6)',
              backdropFilter: 'blur(2px)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 1000,
              padding: 20,
            }}
          >
            <div className="panel" style={{ width: 340, maxWidth: '100%', padding: 26, boxShadow: '0 24px 60px rgba(0,0,0,0.35)' }}>
              {section === 'menu' && (
                <>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, marginBottom: 20 }}>
                    <Avatar me={me} size={72} />
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontWeight: 600, fontSize: 16 }}>{me.display_name || me.username}</div>
                      <small style={{ display: 'block', color: 'var(--muted)' }}>{me.email || me.username}</small>
                    </div>
                  </div>
                  {error && <p className="error">{error}</p>}
                  <input
                    ref={fileRef}
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    style={{ display: 'none' }}
                    onChange={(e) => e.target.files?.[0] && uploadAvatar(e.target.files[0])}
                  />
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
                  <div className="section-divider" />
                  <button
                    type="button"
                    className="secondary"
                    style={{ width: '100%', marginBottom: 6 }}
                    onClick={() => {
                      close();
                      onOpenTrocarEmail();
                    }}
                  >
                    E-mail
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    style={{ width: '100%', marginBottom: 6 }}
                    onClick={() => {
                      close();
                      onOpenTrocarSenha();
                    }}
                  >
                    Trocar senha
                  </button>
                  <p style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: -2, marginBottom: 14 }}>
                    Por segurança, essas duas opções pedem para você entrar novamente.
                  </p>
                  <button type="button" className="danger-outline" style={{ width: '100%' }} onClick={() => setSection('excluir')}>
                    Excluir conta
                  </button>
                  <button type="button" className="secondary" style={{ width: '100%', marginTop: 14 }} onClick={close}>
                    Fechar
                  </button>
                </>
              )}

              {section === 'nome' && (
                <form onSubmit={saveNome}>
                  <h2 style={{ fontSize: 18, marginBottom: 14 }}>Editar nome</h2>
                  <label style={{ margin: 0 }}>
                    Nome de exibição
                    <input name="display_name" defaultValue={me.display_name} autoFocus />
                  </label>
                  {error && <p className="error">{error}</p>}
                  <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
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
                  <h2 style={{ fontSize: 18, marginBottom: 10 }}>Excluir conta</h2>
                  <p style={{ fontSize: 12.5, color: 'var(--danger, #c0392b)', marginBottom: 10 }}>
                    Isso remove sua conta e o acesso ao CRM permanentemente. Não pode ser desfeito.
                  </p>
                  <label style={{ margin: 0 }}>
                    Confirme sua senha
                    <input name="password" type="password" autoComplete="current-password" required autoFocus />
                  </label>
                  {error && <p className="error">{error}</p>}
                  <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
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
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
