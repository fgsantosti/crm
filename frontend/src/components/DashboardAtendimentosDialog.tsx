import { useEffect, useRef } from 'react';

export type AtendimentoResumo = {
  id: string;
  name: string;
  contact: string;
  demand: string;
  especialidade: string;
  temperature: string;
  priority: string;
  owner: string;
  created_at: string;
  desfecho: string;
  origem_manual: boolean;
  categoria_status: 'despachado' | 'automatico' | 'equipe' | 'desqualificado' | 'especial';
  triagem_concluida: boolean;
};

const STATUS = {
  automatico: { label: 'Em triagem', color: '#2563EB' },
  equipe: { label: 'Com a equipe', color: 'var(--accent)' },
  despachado: { label: 'Despachado', color: 'var(--success)' },
  desqualificado: { label: 'Desqualificado/desconfiado', color: 'var(--muted)' },
  especial: { label: 'Outras situações', color: '#7C3AED' },
};

export function DashboardAtendimentosDialog({ title, description, atendimentos, onClose }: {
  title: string;
  description: string;
  atendimentos: AtendimentoResumo[];
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);

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
    <dialog ref={ref} className="dashboard-dialog" aria-labelledby="dashboard-dialog-title" aria-describedby="dashboard-dialog-description" onClose={() => {
      // O StrictMode pode enfileirar close durante a montagem e reabrir em seguida.
      if (ref.current && !ref.current.open) onClose();
    }} onClick={(e) => {
      if (e.target !== e.currentTarget) return;
      const bounds = e.currentTarget.getBoundingClientRect();
      if (e.clientX < bounds.left || e.clientX > bounds.right || e.clientY < bounds.top || e.clientY > bounds.bottom) ref.current?.close();
    }}>
      <div className="panel-toolbar">
        <div>
          <h2 id="dashboard-dialog-title">{title}</h2>
          <p id="dashboard-dialog-description" style={{ margin: '6px 0 0', fontSize: 13 }}>{description}</p>
          <small>{atendimentos.length} atendimento{atendimentos.length === 1 ? '' : 's'} no período selecionado</small>
        </div>
        <button autoFocus type="button" className="secondary" aria-label="Fechar popup" onClick={() => ref.current?.close()}>Fechar ×</button>
      </div>
      <div className="table-wrap dashboard-dialog-content">
        {atendimentos.length ? (
          <table>
            <thead><tr><th>Lead</th><th>Área</th><th>Demanda</th><th>Urgência</th><th>Status</th><th>Responsável</th><th>Entrada</th></tr></thead>
            <tbody>
              {atendimentos.map((lead) => {
                const status = STATUS[lead.categoria_status];
                return (
                  <tr key={lead.id}>
                    <td><strong style={{ display: 'block' }}>{lead.name || 'Sem nome informado'}</strong><small>{lead.contact}{lead.origem_manual ? ' · cadastro manual' : ''}</small></td>
                    <td>{lead.especialidade || '—'}</td>
                    <td className="dashboard-demand">{lead.demand || '—'}</td>
                    <td>{lead.temperature || '—'}</td>
                    <td style={{ color: status.color, fontWeight: 600 }}>{status.label}</td>
                    <td>{lead.owner || '—'}</td>
                    <td style={{ whiteSpace: 'nowrap', fontSize: 12 }}>{new Date(lead.created_at).toLocaleString('pt-BR', { timeZone: 'America/Fortaleza' })}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : <div className="empty">Nenhum atendimento deste grupo no período selecionado.</div>}
      </div>
    </dialog>
  );
}
