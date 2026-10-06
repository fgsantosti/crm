import { useEffect, useState } from 'react';
import { fetchTodasAsPaginas, type Api } from '../api';
import type { Company, Lead } from '../types';
import { SkeletonRows } from '../components/Skeleton';

// Pendências = Kanban "Qualificados" + "Atendimentos em espera" (backend: ?pending=1, já ordenado
// com Em espera antes de Classificado). "Pegar Lead" assume o atendimento e leva o lead para
// "Meus Atendimentos" (mesma ação do Kanban ao mover para Em negociação).
function estagio(l: Lead): 'Em espera' | 'Classificado' {
  return l.etapa_atendimento === 'espera' ? 'Em espera' : 'Classificado';
}

export function Pendencias({ api, company }: { api: Api; company: Company }) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [pegandoId, setPegandoId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [recarregar, setRecarregar] = useState(0);

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
  }, [company.id, recarregar]);

  async function pegarLead(lead: Lead) {
    if (!window.confirm(`Pegar "${lead.name || lead.contact}"? Você passa a ser o responsável e o lead vai para "Meus Atendimentos".`)) return;
    setPegandoId(lead.id);
    setError('');
    try {
      await api(`/leads/${lead.id}/negociar/?company=${company.id}`, { method: 'POST' });
      setLeads((v) => v.filter((l) => l.id !== lead.id));
    } catch (e) {
      setError((e as Error).message);
      setRecarregar((n) => n + 1);
    } finally {
      setPegandoId(null);
    }
  }

  const visible = leads.filter((l) => `${l.name} ${l.contact}`.toLowerCase().includes(search.toLowerCase()));

  return (
    <>
      <header className="page-header" style={{ alignItems: 'flex-end' }}>
        <div>
          <small className="eyebrow">Fila de ação</small>
          <h1>Pendências</h1>
          <p>Em espera primeiro, depois classificados, por prioridade.{leads.length ? ` ${leads.length} casos aguardando atendimento.` : ''}</p>
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
                <th>Estágio</th>
                <th>Próxima ação</th>
                <th>Pegar Lead</th>
              </tr>
            </thead>
            <tbody>
              {busy && !visible.length && <SkeletonRows rows={4} cols={5} />}
              {visible.map((l) => {
                return (
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
                    <td>{estagio(l)}</td>
                    <td>{l.next_action}</td>
                    <td>
                      <button
                        type="button"
                        onClick={() => pegarLead(l)}
                        disabled={pegandoId !== null}
                        title="Assumir e levar para Meus Atendimentos"
                      >
                        {pegandoId === l.id ? 'Pegando…' : 'Pegar Lead'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {!busy && !visible.length && <div className="empty">Nenhuma pendência nesta empresa.</div>}
        <p className="table-note">Casos em negociação ou despacho não aparecem aqui — veja em “Meus Atendimentos”.</p>
      </section>
    </>
  );
}
