import { useEffect, useState } from 'react';
import type { Api } from '../api';
import type { Company, Lead, LeadEvent, Paginated } from '../types';
import { SkeletonCards, Spinner } from '../components/Skeleton';

export function Leads({ api, company }: { api: Api; company: Company }) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Lead | null>(null);
  const [events, setEvents] = useState<LeadEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setBusy(true);
    setSelected(null);
    setError('');
    api(`/leads/?company=${company.id}`)
      .then((d: Paginated<Lead>) => {
        if (active) setLeads(d.results);
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

  useEffect(() => {
    if (!selected) {
      setEvents([]);
      return;
    }
    let active = true;
    api(`/leads/${selected.id}/events/?company=${company.id}`)
      .then((d) => {
        if (active) setEvents(d);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [selected?.id]);

  async function save(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!selected) return;
    setBusy(true);
    const form = new FormData(e.currentTarget);
    try {
      const updated = await api(`/leads/${selected.id}/?company=${company.id}`, {
        method: 'PATCH',
        body: JSON.stringify(Object.fromEntries(form.entries())),
      });
      setLeads((v) => v.map((l) => (l.id === updated.id ? updated : l)));
      setSelected(updated);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const visible = leads.filter((l) => `${l.name} ${l.contact}`.toLowerCase().includes(search.toLowerCase()));

  const columnOf = (l: Lead): 'novo' | 'triagem' | 'humano' | 'classificado' => {
    if (l.mode === 'HUMANO') return 'humano';
    if (l.bot_closed) return 'classificado';
    if (l.funnel_stage === 'Novo lead') return 'novo';
    return 'triagem';
  };
  const columns: { key: ReturnType<typeof columnOf>; label: string }[] = [
    { key: 'novo', label: 'Novo lead' },
    { key: 'triagem', label: 'Em triagem' },
    { key: 'humano', label: 'Atendimento humano' },
    { key: 'classificado', label: 'Classificado' },
  ];

  return (
    <>
      <header className="page-header">
        <div>
          <small className="eyebrow">Relacionamento · WhatsApp</small>
          <h1>Seus leads, próximos passos claros.</h1>
          <p>Acompanhe a qualificação de cada contato, etapa por etapa.</p>
        </div>
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <section className="panel" style={{ padding: 0 }}>
        <div className="panel-toolbar">
          <h2>Central de leads</h2>
          <input placeholder="Buscar nome ou telefone" aria-label="Buscar leads" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        {busy && !visible.length ? (
          <div style={{ padding: '18px 24px' }}>
            <SkeletonCards count={4} height={90} />
          </div>
        ) : (
          <div className="kanban">
            {columns.map((col) => {
              const items = visible.filter((l) => columnOf(l) === col.key);
              return (
                <div key={col.key} className="kanban-col">
                  <div className="kanban-col-head">
                    <h3>{col.label}</h3>
                    <small>
                      {items.length} lead{items.length === 1 ? '' : 's'}
                    </small>
                  </div>
                  <div className="kanban-col-body">
                    {items.map((l) => (
                      <article
                        key={l.id}
                        className={`kanban-card${selected?.id === l.id ? ' selected' : ''}`}
                        onClick={() => setSelected(l)}
                        tabIndex={0}
                        role="button"
                        aria-label={`Ver detalhes de ${l.name || l.contact}`}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            setSelected(l);
                          }
                        }}
                      >
                        <span className={`priority-dot priority-dot-${l.priority === 'Alta' ? 'alta' : l.priority === 'Média' ? 'media' : 'baixa'}`} />
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <div style={{ fontWeight: 600, fontSize: 13.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {l.name || 'Sem nome informado'}
                          </div>
                          <small style={{ display: 'block', fontFamily: "'DM Mono',monospace" }}>{l.contact}</small>
                          {l.demand && (
                            <small style={{ display: 'block', marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {l.demand}
                            </small>
                          )}
                        </div>
                      </article>
                    ))}
                    {!items.length && <p style={{ fontSize: 12.5, color: 'var(--muted-soft)', padding: '4px 2px' }}>Nenhum lead aqui.</p>}
                  </div>
                </div>
              );
            })}
          </div>
        )}
        {!busy && !visible.length && (
          <div className="empty">
            {'Nenhum lead nesta visão. Os contatos aparecerão ao receber mensagens pela integração.'}
          </div>
        )}
        <p className="table-note">Exibindo até 100 leads por consulta.</p>
      </section>

      {selected && (
        <section className="panel detail">
          <div className="detail-head">
            <h2>{selected.name || selected.contact}</h2>
            <button className="secondary" onClick={() => setSelected(null)}>
              Fechar
            </button>
          </div>
          <p style={{ marginBottom: 20 }}>
            Estado: <strong style={{ color: 'var(--ink)' }}>{selected.state}</strong> · Bot {selected.bot_closed ? 'encerrado' : 'ativo'}
          </p>
          <form key={selected.id} onSubmit={save}>
            <div className="fields">
              <label>
                Nome
                <input name="name" defaultValue={selected.name} />
              </label>
              <label>
                Responsável
                <input name="owner" defaultValue={selected.owner} />
              </label>
              <label>
                Prioridade
                <select name="priority" defaultValue={selected.priority}>
                  <option>Alta</option>
                  <option>Média</option>
                  <option>Baixa</option>
                </select>
              </label>
              <label>
                Demanda
                <input name="demand" defaultValue={selected.demand} />
              </label>
              <label>
                Especialidade
                <input readOnly value={selected.especialidade || '—'} />
              </label>
              <label>
                Temperatura
                <input readOnly value={selected.temperature || '—'} />
              </label>
            </div>
            <label>
              Observações
              <textarea name="notes" defaultValue={selected.notes} />
            </label>
            <button disabled={busy}>
              {busy && <Spinner />}
              Salvar alterações
            </button>
          </form>
          <h3 style={{ margin: '26px 0 10px' }}>Histórico operacional</h3>
          {events.length ? (
            events.map((ev) => (
              <p key={ev.id} style={{ marginBottom: 6, fontSize: '13.5px' }}>
                {new Date(ev.created_at).toLocaleString('pt-BR')} · {ev.summary} · {ev.delivery}
              </p>
            ))
          ) : (
            <p>Nenhum evento registrado.</p>
          )}
        </section>
      )}
    </>
  );
}
