import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useSaidaDoPopup } from '../popupSaida';
import type { Api } from '../api';
import type { Lead } from '../types';
import { HistoricoConversaDialog } from './HistoricoConversaDialog';

/** Observações do agente = itens curtos separados por ";" (services.mesclar_observacoes). */
export function itensObservacao(notes: string): string[] {
  return (notes || '').split(';').map((i) => i.trim()).filter(Boolean);
}

/** Lista de observações do lead, um item por linha; vazio mostra o texto de apoio. */
export function ObservacoesLead({ notes, vazio = 'Nenhuma observação registrada.' }: { notes: string; vazio?: string }) {
  const itens = itensObservacao(notes);
  if (!itens.length) return <span style={{ color: 'var(--muted)' }}>{vazio}</span>;
  return (
    <ul style={{ margin: 0, paddingLeft: 18 }}>
      {itens.map((i, n) => (
        <li key={n}>{i}</li>
      ))}
    </ul>
  );
}

function Campo({ rotulo, children, largo }: { rotulo: string; children: ReactNode; largo?: boolean }) {
  return (
    <div style={{ gridColumn: largo ? '1 / -1' : undefined }}>
      <small style={{ display: 'block', color: 'var(--muted)', marginBottom: 2 }}>{rotulo}</small>
      <div style={{ fontSize: 14, wordBreak: 'break-word' }}>{children}</div>
    </div>
  );
}

/**
 * Popup com os dados do lead (tela Pendências): ajuda a atendente a decidir se consegue atender.
 * Demanda = situação-problema; observações = dados auxiliares não sensíveis gravados pelo agente.
 */
export function LeadDetalheDialog({ lead, estagio, onClose, onPegar, pegando, historico }: {
  lead: Lead;
  /** Presente só quando a empresa liga a coleta de histórico no Admin: mostra o botão "Histórico de conversa". */
  historico?: { api: Api; companyId: number };
  estagio: string;
  onClose: () => void;
  onPegar?: (lead: Lead) => void;
  pegando?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useSaidaDoPopup(ref);
  const [verHistorico, setVerHistorico] = useState(false);

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

  return (
    <dialog
      ref={ref}
      className="lead-dialog"
      aria-labelledby="lead-dialog-title"
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
      <div className="panel-toolbar">
        <div>
          <h2 id="lead-dialog-title">{lead.name || 'Sem nome informado'}</h2>
          <small style={{ fontFamily: "'DM Mono',monospace" }}>{lead.contact}</small>
        </div>
        <button type="button" className="secondary" onClick={() => ref.current?.close()} aria-label="Fechar">
          Fechar
        </button>
      </div>
      <div className="lead-dialog-content">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 14 }}>
          <Campo rotulo="Área">{lead.especialidade || '—'}</Campo>
          <Campo rotulo="Temperatura">{lead.temperature || '—'}</Campo>
          <Campo rotulo="Prioridade">{lead.priority}</Campo>
          <Campo rotulo="Estágio">{estagio}</Campo>
          <Campo rotulo="Entrou em">{new Date(lead.created_at).toLocaleString('pt-BR')}</Campo>
          <Campo rotulo="Próxima ação">{lead.next_action || '—'}</Campo>
          <Campo rotulo="Demanda (situação do cliente)" largo>
            {lead.demand || <span style={{ color: 'var(--muted)' }}>Sem demanda registrada.</span>}
          </Campo>
          <Campo rotulo="Observações" largo>
            <ObservacoesLead notes={lead.notes} />
            {historico && (
              <button type="button" className="secondary" style={{ marginTop: 10 }} onClick={() => setVerHistorico(true)}>
                Histórico de conversa
              </button>
            )}
          </Campo>
          {lead.impacto && (
            <Campo rotulo="Impacto" largo>
              {lead.impacto}
            </Campo>
          )}
        </div>
      </div>
      {verHistorico && historico && <HistoricoConversaDialog api={historico.api} companyId={historico.companyId} lead={lead} onClose={() => setVerHistorico(false)} />}
      {onPegar && (
        <div className="lead-dialog-footer">
          <button type="button" className="secondary" onClick={() => ref.current?.close()}>
            Voltar
          </button>
          <button type="button" onClick={() => onPegar(lead)} disabled={pegando}>
              {pegando ? 'Pegando…' : 'Pegar Lead'}
            </button>
        </div>
      )}
    </dialog>
  );
}
