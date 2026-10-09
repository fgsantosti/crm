import { useEffect, useRef, useState } from 'react';
import type { Api } from '../api';
import type { Company } from '../types';
import { paletaDaIdentidade } from '../identidade';
import { Logo } from './Logo';
import { Spinner } from './Skeleton';

const PADRAO_PRINCIPAL = '#241a12';
const PADRAO_CONTRASTE = '#4a2410';

/**
 * Popup "Identidade visual" (conta Empresa): nome e logo exibidos na barra lateral e as duas cores do
 * gradiente de fundo. As duas cores são obrigatórias; o texto da barra se ajusta pela luminância.
 */
export function IdentidadeVisualDialog({ api, company, onSaved, onClose }: { api: Api; company: Company; onSaved: (c: Company) => void; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const atual = company.identidade_visual;
  const [nome, setNome] = useState(atual?.nome ?? '');
  const [principal, setPrincipal] = useState(atual?.cor_principal ?? PADRAO_PRINCIPAL);
  const [contraste, setContraste] = useState(atual?.cor_contraste ?? PADRAO_CONTRASTE);
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [previaLogo, setPreviaLogo] = useState<string | null>(atual?.logo_url ?? null);
  const [removerLogo, setRemoverLogo] = useState(false);
  const [busy, setBusy] = useState(false);
  const [erro, setErro] = useState('');

  useEffect(() => {
    const dialog = ref.current!;
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.showModal();
    return () => {
      dialog.close();
      document.body.style.overflow = previousOverflow;
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, []);

  useEffect(() => {
    if (!arquivo) return;
    const url = URL.createObjectURL(arquivo);
    setPreviaLogo(url);
    return () => URL.revokeObjectURL(url);
  }, [arquivo]);

  const paleta = paletaDaIdentidade(principal, contraste);

  async function enviar(corpo: FormData) {
    setBusy(true);
    setErro('');
    try {
      const atualizada: Company = await api(`/companies/${company.id}/identidade/`, { method: 'POST', body: corpo });
      onSaved(atualizada);
      ref.current?.close();
    } catch (e) {
      setErro((e as Error).message);
      setBusy(false);
    }
  }

  function salvar(e: React.FormEvent) {
    e.preventDefault();
    const form = new FormData();
    form.append('nome', nome.trim());
    form.append('cor_principal', principal);
    form.append('cor_contraste', contraste);
    if (arquivo) form.append('logo', arquivo);
    if (removerLogo && !arquivo) form.append('remover_logo', '1');
    void enviar(form);
  }

  function restaurar() {
    if (!window.confirm('Voltar ao padrão Conecta (logo, nome e cores originais)?')) return;
    const form = new FormData();
    form.append('restaurar', '1');
    void enviar(form);
  }

  return (
    <dialog
      ref={ref}
      className="lead-dialog"
      aria-labelledby="identidade-dialog-title"
      onClose={() => {
        // O StrictMode pode enfileirar close durante a montagem e reabrir em seguida.
        if (ref.current && !ref.current.open) onClose();
      }}
      onClick={(e) => {
        if (e.target !== e.currentTarget) return;
        const b = e.currentTarget.getBoundingClientRect();
        if (e.clientX < b.left || e.clientX > b.right || e.clientY < b.top || e.clientY > b.bottom) ref.current?.close();
      }}
    >
      <form onSubmit={salvar} style={{ display: 'contents' }}>
        <div className="panel-toolbar">
          <div>
            <h2 id="identidade-dialog-title">Identidade visual</h2>
            <small>Nome, logo e cores da barra lateral. Só a sua empresa e a equipe dela veem.</small>
          </div>
          <button type="button" className="secondary" onClick={() => ref.current?.close()}>
            Fechar
          </button>
        </div>
        <div className="lead-dialog-content" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {erro && (
            <p role="alert" className="error">
              {erro}
            </p>
          )}

          <div className="identidade-previa" style={{ background: paleta.fundo, color: paleta.vars['--sb-fg'] }} aria-label="Prévia da barra lateral">
            <div className="brand">
              {previaLogo && !removerLogo ? <img src={previaLogo} alt="" /> : <Logo />}
              <span>{nome.trim() || 'Conecta'}</span>
            </div>
            <small style={{ color: paleta.vars['--sb-mudo'] }}>Prévia · texto {paleta.textoClaro ? 'claro' : 'escuro'} para boa leitura</small>
          </div>

          <label style={{ margin: 0 }}>
            Nome exibido
            <input value={nome} maxLength={30} placeholder="Conecta" onChange={(e) => setNome(e.target.value)} />
          </label>

          <div>
            <small style={{ display: 'block', fontWeight: 600, marginBottom: 6 }}>Logo (PNG, JPEG ou WEBP, até 2 MB)</small>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <label className="secondary" style={{ margin: 0, padding: '9px 16px', borderRadius: 10, cursor: 'pointer', fontWeight: 600, fontSize: 14 }}>
                Trocar logo
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  style={{ display: 'none' }}
                  onChange={(e) => {
                    setArquivo(e.target.files?.[0] ?? null);
                    setRemoverLogo(false);
                  }}
                />
              </label>
              {(previaLogo || arquivo) && !removerLogo && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    setArquivo(null);
                    setPreviaLogo(null);
                    setRemoverLogo(true);
                  }}
                >
                  Usar o logo Conecta
                </button>
              )}
            </div>
          </div>

          <div className="identidade-cores">
            <label style={{ margin: 0 }}>
              Cor principal
              <input type="color" value={principal} onChange={(e) => setPrincipal(e.target.value)} />
              <small style={{ fontFamily: "'DM Mono',monospace" }}>{principal}</small>
            </label>
            <label style={{ margin: 0 }}>
              Cor de contraste
              <input type="color" value={contraste} onChange={(e) => setContraste(e.target.value)} />
              <small style={{ fontFamily: "'DM Mono',monospace" }}>{contraste}</small>
            </label>
          </div>
          <small style={{ color: 'var(--muted)' }}>As duas cores formam o gradiente do fundo e o texto da barra se ajusta sozinho conforme a luminosidade.</small>
        </div>
        <div className="lead-dialog-footer">
          <button type="button" className="secondary" onClick={restaurar} disabled={busy}>
            Restaurar padrão
          </button>
          <button disabled={busy}>
            {busy && <Spinner />}
            Salvar
          </button>
        </div>
      </form>
    </dialog>
  );
}
