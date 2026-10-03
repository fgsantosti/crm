import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Api } from '../api';
import type { Me } from '../types';
import { Spinner } from './Skeleton';

type Section = 'menu' | 'excluir';

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

const ghostLightBtn: React.CSSProperties = {
  width: '100%',
  background: 'rgba(255,255,255,0.12)',
  border: '1px solid rgba(255,255,255,0.4)',
  color: '#fff',
  marginBottom: 8,
};

export function ProfileMenu({
  api,
  me,
  onMeChange,
  onAccountDeleted,
  onOpenTrocarEmail,
  onOpenTrocarSenha,
  onLogout,
}: {
  api: Api;
  me: Me;
  onMeChange: (patch: Partial<Me>) => void;
  onAccountDeleted: () => void;
  onOpenTrocarEmail: () => void;
  onOpenTrocarSenha: () => void;
  onLogout: () => void;
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
            <div
              className="panel"
              style={{
                position: 'relative',
                width: 680,
                maxWidth: '100%',
                padding: 0,
                overflow: 'hidden',
                borderRadius: 20,
                boxShadow: '0 32px 70px rgba(0,0,0,0.4)',
                display: 'flex',
                flexWrap: 'wrap',
              }}
            >
              <button
                type="button"
                onClick={close}
                aria-label="Fechar"
                style={{
                  position: 'absolute',
                  top: 14,
                  right: 14,
                  border: 'none',
                  background: 'rgba(255,255,255,0.7)',
                  width: 30,
                  height: 30,
                  borderRadius: '50%',
                  cursor: 'pointer',
                  fontSize: 16,
                  lineHeight: '30px',
                  textAlign: 'center',
                  padding: 0,
                  zIndex: 1,
                }}
              >
                ×
              </button>

              {section === 'menu' && (
                <>
                  {/* Coluna esquerda: mesmo tratamento de fundo das telas comuns (ink + glow + pontilhado), não laranja chapado */}
                  <div
                    style={{
                      width: 240,
                      flex: 'none',
                      position: 'relative',
                      overflow: 'hidden',
                      background: 'var(--ink)',
                      padding: '44px 26px 28px',
                      boxSizing: 'border-box',
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                    }}
                  >
                    <div
                      style={{
                        position: 'absolute',
                        inset: 0,
                        pointerEvents: 'none',
                        background:
                          'radial-gradient(260px 260px at 90% -10%, rgba(217,83,26,.35), transparent 60%), radial-gradient(200px 200px at -10% 70%, rgba(217,83,26,.20), transparent 65%)',
                      }}
                    />
                    <div
                      style={{
                        position: 'absolute',
                        inset: 0,
                        opacity: 0.5,
                        pointerEvents: 'none',
                        backgroundImage: 'radial-gradient(rgba(255,255,255,.06) 1px, transparent 1px)',
                        backgroundSize: '14px 14px',
                      }}
                    />
                    <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', flex: 1, width: '100%' }}>
                      <div style={{ marginBottom: 16 }}>
                        <Avatar me={me} size={104} />
                      </div>
                      <div style={{ color: '#fff', fontWeight: 600, fontSize: 15.5, textAlign: 'center', marginBottom: 20 }}>
                        {me.display_name || me.username}
                      </div>
                      <input
                        ref={fileRef}
                        type="file"
                        accept="image/png,image/jpeg,image/webp"
                        style={{ display: 'none' }}
                        onChange={(e) => e.target.files?.[0] && uploadAvatar(e.target.files[0])}
                      />
                      <button type="button" style={ghostLightBtn} onClick={() => fileRef.current?.click()} disabled={busy}>
                        {busy && <Spinner />}
                        Trocar foto
                      </button>
                      {me.avatar_url && (
                        <button type="button" style={ghostLightBtn} onClick={removeAvatar} disabled={busy}>
                          Remover foto
                        </button>
                      )}
                      <div style={{ flex: 1 }} />
                      <button type="button" style={{ ...ghostLightBtn, marginBottom: 0 }} onClick={onLogout}>
                        Sair da conta
                      </button>
                    </div>
                  </div>

                  {/* Coluna direita: campos */}
                  <div style={{ flex: '1 1 360px', padding: '40px 34px', boxSizing: 'border-box', minWidth: 320 }}>
                    <h2 style={{ fontSize: 19, margin: '0 0 20px', fontFamily: "'Neuton',serif", fontWeight: 700 }}>Editar conta</h2>
                    {error && <p className="error">{error}</p>}

                    <form onSubmit={saveNome} className="field-card" style={fieldCardStyle}>
                      <div style={fieldLabelStyle}>Nome</div>
                      <div style={fieldHelpStyle}>Como você aparece para o resto da equipe.</div>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <input name="display_name" defaultValue={me.display_name} style={{ flex: 1 }} />
                        <button disabled={busy} style={{ whiteSpace: 'nowrap' }}>
                          {busy && <Spinner />}
                          Salvar
                        </button>
                      </div>
                    </form>

                    <div className="field-card" style={fieldCardStyle}>
                      <div style={fieldLabelStyle}>E-mail</div>
                      <div style={fieldHelpStyle}>Usado para entrar e para receber códigos de confirmação.</div>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <input value={me.email || me.username} disabled style={{ flex: 1 }} />
                        <button
                          type="button"
                          className="secondary"
                          style={{ whiteSpace: 'nowrap' }}
                          onClick={() => {
                            close();
                            onOpenTrocarEmail();
                          }}
                        >
                          Trocar e-mail
                        </button>
                      </div>
                    </div>

                    <div className="field-card" style={{ ...fieldCardStyle, marginBottom: 22 }}>
                      <div style={fieldLabelStyle}>Senha</div>
                      <div style={fieldHelpStyle}>Por segurança, trocar e-mail ou senha pede login novamente.</div>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <input value="********" disabled style={{ flex: 1 }} />
                        <button
                          type="button"
                          className="secondary"
                          style={{ whiteSpace: 'nowrap' }}
                          onClick={() => {
                            close();
                            onOpenTrocarSenha();
                          }}
                        >
                          Trocar senha
                        </button>
                      </div>
                    </div>

                    <button type="button" style={{ width: '100%', background: 'var(--danger)', border: '1px solid var(--danger)', color: '#fff' }} onClick={() => setSection('excluir')}>
                      Excluir conta
                    </button>
                  </div>
                </>
              )}

              {section === 'excluir' && (
                <form onSubmit={excluirConta} style={{ padding: '40px 34px', boxSizing: 'border-box', width: '100%' }}>
                  <h2 style={{ fontSize: 19, margin: '0 0 10px' }}>Excluir conta</h2>
                  <p style={{ fontSize: 13, color: 'var(--danger)', marginBottom: 16 }}>
                    Isso remove sua conta e o acesso ao CRM permanentemente. Não pode ser desfeito.
                  </p>
                  <label style={{ margin: 0 }}>
                    Confirme sua senha
                    <input name="password" type="password" autoComplete="current-password" required autoFocus />
                  </label>
                  {error && <p className="error">{error}</p>}
                  <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
                    <button type="submit" style={{ background: 'var(--danger)', border: '1px solid var(--danger)', color: '#fff' }} disabled={busy}>
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

const fieldCardStyle: React.CSSProperties = {
  border: '1px solid var(--line)',
  borderRadius: 12,
  padding: '16px 18px',
  marginBottom: 14,
};
const fieldLabelStyle: React.CSSProperties = { fontWeight: 600, fontSize: 14, marginBottom: 3 };
const fieldHelpStyle: React.CSSProperties = { fontSize: 12.5, color: 'var(--muted)', marginBottom: 12 };
