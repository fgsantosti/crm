import { useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { SaidaAnimada } from '../popupSaida';
import type { Api } from '../api';
import type { Lead } from '../types';
import { LeadNameField } from './LeadNameField';
import { ObservacoesLead } from './LeadDetalheDialog';
import { HistoricoConversaDialog } from './HistoricoConversaDialog';
import { Spinner } from './Skeleton';
import { IconeWhatsapp } from './Icones';

export function Overlay({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  return createPortal(
    <SaidaAnimada>
    <div
      className="popup-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      style={{ position: 'fixed', inset: 0, background: 'rgba(20,14,9,0.6)', backdropFilter: 'blur(2px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: 20 }}
    >
      <div className="panel" style={{ position: 'relative', width: 520, maxWidth: '100%', maxHeight: '100%', overflowY: 'auto', padding: 24, borderRadius: 16, boxShadow: '0 32px 70px rgba(0,0,0,0.4)' }}>
        {children}
      </div>
    </div>
    </SaidaAnimada>,
    document.body,
  );
}

/** Dados coletados pelo agente (nome editável, contato, área, temperatura, demanda e observações). */
export function TriagemResumo({ lead, api, onUpdated, historico }: {
  lead: Lead;
  api?: Api;
  onUpdated?: (lead: Lead) => void;
  /** Só quando a empresa liga a coleta de histórico no Admin: botão logo após as observações. */
  historico?: { api: Api; companyId: number };
}) {
  const [verHistorico, setVerHistorico] = useState(false);
  return (
    <div className="fields" style={{ marginBottom: 16 }}>
      {api && onUpdated ? (
        <LeadNameField key={lead.id} lead={lead} api={api} onUpdated={onUpdated} />
      ) : (
        <label style={{ margin: 0 }}>
          Nome
          <input readOnly value={lead.name || 'Sem nome informado'} />
        </label>
      )}
      <label style={{ margin: 0 }}>
        Contato
        <input readOnly value={lead.contact} />
      </label>
      <label style={{ margin: 0 }}>
        Área
        <input readOnly value={lead.especialidade || '—'} />
      </label>
      <label style={{ margin: 0 }}>
        Temperatura
        <input readOnly value={lead.temperature || '—'} />
      </label>
      <label style={{ margin: 0, gridColumn: '1 / -1' }}>
        Demanda
        <input readOnly value={lead.demand || '—'} />
      </label>
      {(lead.notes || historico) && (
        <div style={{ gridColumn: '1 / -1', fontSize: 14 }}>
          {lead.notes && (
            <>
              <small style={{ display: 'block', color: 'var(--muted)', marginBottom: 2 }}>Observações</small>
              <ObservacoesLead notes={lead.notes} />
            </>
          )}
          {historico && (
            <button type="button" className="secondary" style={{ marginTop: 10 }} onClick={() => setVerHistorico(true)}>
              Histórico de conversa
            </button>
          )}
        </div>
      )}
      {verHistorico && historico && <HistoricoConversaDialog api={historico.api} companyId={historico.companyId} lead={lead} onClose={() => setVerHistorico(false)} />}
    </div>
  );
}

/**
 * Popup "Cadastro do atendimento": o mesmo ao arrastar o card para Em negociação (Kanban) e ao
 * clicar em Pegar Lead (Pendências). "Acompanhar" confirma e move o lead para Em negociação.
 */
export function CadastroAtendimentoDialog({ lead, api, historico, busy, onUpdated, onConfirm, onClose }: {
  lead: Lead;
  api: Api;
  historico?: { api: Api; companyId: number };
  busy: boolean;
  onUpdated: (lead: Lead) => void;
  onConfirm: (lead: Lead) => void;
  onClose: () => void;
}) {
  return (
    <Overlay onClose={onClose}>
      <h2 style={{ marginTop: 0 }}>Cadastro do atendimento</h2>
      <p style={{ color: 'var(--muted)', marginBottom: 16 }}>Dados coletados pelo agente durante a triagem.</p>
      <TriagemResumo lead={lead} api={api} onUpdated={onUpdated} historico={historico} />
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <button type="button" onClick={() => onConfirm(lead)} disabled={busy} style={{ background: '#2563EB', borderColor: '#2563EB' }}>
          {busy && <Spinner />}
          Acompanhar
        </button>
        {lead.contact && (
          <a href={`https://wa.me/${lead.contact.replace(/\D/g, '')}`} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
            <button type="button" style={{ background: '#25D366', borderColor: '#25D366', display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <IconeWhatsapp size={22} />
              Contatar
            </button>
          </a>
        )}
        <button type="button" className="secondary" onClick={onClose}>
          Cancelar
        </button>
      </div>
    </Overlay>
  );
}
