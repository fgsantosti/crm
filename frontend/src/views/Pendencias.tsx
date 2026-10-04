import { useEffect, useState } from 'react';
import { fetchTodasAsPaginas, type Api } from '../api';
import type { Company, Lead } from '../types';
import { SkeletonRows } from '../components/Skeleton';

export function Pendencias({ api, company }: { api: Api; company: Company }) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setBusy(true);
    setError('');
    fetchTodasAsPaginas<Lead>(api, `/leads/?company=${company.id}&pending=1`)
      .then((todos) => {
        if (active) setLeads(todos);
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [company.id]);

  const visible = leads.filter((l) => `${l.name} ${l.contact}`.toLowerCase().includes(search.toLowerCase()));

  return (
    <>
      <header className="page-header" style={{ alignItems: 'flex-end' }}>
        <div>
          <small className="eyebrow">Fila de ação</small>
          <h1>Pendências</h1>
          <p>Ordenadas por prioridade e data de retorno.{leads.length ? ` ${leads.length} casos aguardando próxima ação.` : ''}</p>
        </div>
        <input placeholder="Buscar nome ou telefone" aria-label="Buscar pendências" style={{ width: 260 }} value={search} onChange={(e) => setSearch(e.target.value)} />
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <section className="panel">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Prioridade</th>
                <th>Lead</th>
                <th>Etapa</th>
                <th>Próxima ação</th>
                <th>Retorno</th>
                <th>Responsável</th>
              </tr>
            </thead>
            <tbody>
              {busy && !visible.length && <SkeletonRows rows={4} cols={6} />}
              {visible.map((l) => (
                <tr key={l.id}>
                  <td>
                    <span className={`priority priority-${l.priority === 'Alta' ? 'alta' : l.priority === 'Média' ? 'media' : 'baixa'}`}>
                      <span className="priority-dot" />
                      {l.priority}
                    </span>
                  </td>
                  <td>
                    <div style={{ fontWeight: 600 }}>{l.name || 'Sem nome informado'}</div>
                    <small>{l.contact}</small>
                  </td>
                  <td>{l.funnel_stage}</td>
                  <td>{l.next_action}</td>
                  <td style={{ fontFamily: "'DM Mono',monospace", fontSize: 13, color: 'var(--muted)' }}>
                    {l.return_at ? new Date(l.return_at).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'}
                  </td>
                  <td style={{ color: 'var(--muted)' }}>{l.owner_nome || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!busy && !visible.length && <div className="empty">Nenhuma pendência nesta empresa.</div>}
        <p className="table-note">Casos em atendimento humano não aparecem aqui — veja em “Meus Atendimentos”.</p>
      </section>
    </>
  );
}
