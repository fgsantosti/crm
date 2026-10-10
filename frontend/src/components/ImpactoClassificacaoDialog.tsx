import { useEffect, useRef } from 'react';
import { useSaidaDoPopup } from '../popupSaida';

export type LeadAfetada = { id: string; name: string; contact: string; especialidade: string; media: number | null; de: string; para: string };

export const ICONE_ALERTA = (
  <>
    <path d="M8 2.5l5.5 10h-11z" strokeLinejoin="round" />
    <path d="M8 6.5v2.5" strokeLinecap="round" />
    <circle cx="8" cy="11" r=".55" fill="currentColor" stroke="none" />
  </>
);

const fmt = (n: number | null) => (n === null ? '—' : (Math.round(n * 10) / 10).toFixed(1).replace('.', ','));

/** Popup de aviso: leads de Classificados que sairiam do Kanban com as faixas em edição. Mesmo padrão das confirmações (faixa Conecta). */
export function ImpactoClassificacaoDialog({ afetadas, alteradas, cores, saving, onVoltar, onSalvar }: {
  /** Saem do Kanban (concluem como desqualificadas). */
  afetadas: LeadAfetada[];
  /** Continuam no Kanban, mas trocam de classificação. */
  alteradas: LeadAfetada[];
  cores: Record<string, string>;
  saving: boolean;
  onVoltar: () => void;
  onSalvar: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useSaidaDoPopup(ref);

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

  const n = afetadas.length + alteradas.length;
  const linhas = (lista: LeadAfetada[], fora: boolean) => (
    <ul className="impacto-lista">
      {lista.map((l) => (
        <li key={l.id}>
          <div className="impacto-id">
            <strong>{l.name || 'Sem nome informado'}</strong>
            <small>{l.contact}</small>
          </div>
          <span className="impacto-media">média {fmt(l.media)}</span>
          <span className="impacto-troca">
            <span><span className="classif-cor" style={{ background: cores[l.de] }} aria-hidden="true" />{l.de}</span>
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 8h9M9 4l4 4-4 4" stroke="#6E5F4F" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
            <span className={fora ? 'impacto-para' : undefined}><span className="classif-cor" style={{ background: cores[l.para] }} aria-hidden="true" />{l.para}{fora ? ' (fora do Kanban)' : ''}</span>
          </span>
        </li>
      ))}
    </ul>
  );
  return (
    <dialog
      ref={ref}
      className="confirm-dialog impacto-dialog"
      data-tom="atencao"
      aria-labelledby="impacto-titulo"
      onClose={() => {
        if (ref.current && !ref.current.open) onVoltar();
      }}
      onClick={(e) => {
        if (e.target !== e.currentTarget) return;
        const b = e.currentTarget.getBoundingClientRect();
        if (e.clientX < b.left || e.clientX > b.right || e.clientY < b.top || e.clientY > b.bottom) ref.current?.close();
      }}
    >
      <div className="confirm-faixa">
        <div className="confirm-icone">
          <svg width="24" height="24" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">{ICONE_ALERTA}</svg>
        </div>
      </div>
      <div className="confirm-corpo">
        <h2 id="impacto-titulo">{n} lead{n === 1 ? ' seria afetada' : 's seriam afetadas'} pelas novas faixas</h2>
        <p className="confirm-mensagem">
          Só leads em Classificados são reavaliadas pela média que já têm. Leads em espera, em negociação ou concluídas não mudam.
        </p>
        {afetadas.length > 0 && (
          <section className="impacto-grupo">
            <h3>{afetadas.length} sa{afetadas.length === 1 ? 'i' : 'em'} do Kanban</h3>
            <p>Concluem sozinhas como desqualificadas e o número é liberado.</p>
            {linhas(afetadas, true)}
          </section>
        )}
        {alteradas.length > 0 && (
          <section className="impacto-grupo">
            <h3>{alteradas.length} muda{alteradas.length === 1 ? '' : 'm'} de classificação e continua{alteradas.length === 1 ? '' : 'm'} no Kanban</h3>
            <p>A temperatura (e a prioridade, se era a padrão) é atualizada.</p>
            {linhas(alteradas, false)}
          </section>
        )}
        <div className="confirm-acoes">
          <span className="confirm-dica"><kbd>Esc</kbd> volta</span>
          <div className="confirm-botoes">
            <button type="button" className="secondary" onClick={() => ref.current?.close()}>
              Voltar e ajustar
            </button>
            <button type="button" className="confirm-ok" disabled={saving} onClick={onSalvar}>
              Salvar mesmo assim
            </button>
          </div>
        </div>
      </div>
    </dialog>
  );
}
