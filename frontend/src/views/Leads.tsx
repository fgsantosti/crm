import { useEffect, useState } from 'react';
import type { Api } from '../api';
import type { Company, Lead, LeadEvent, Paginated } from '../types';
import { SkeletonCards, Spinner } from '../components/Skeleton';

const PRIORITY_RANK: Record<string, number> = { Alta: 0, Média: 1, Baixa: 2 };

// Mesma ordem de services.URGENCIA_POR_FAIXA no backend (menos urgente -> mais urgente).
const URGENCIA_RANK: Record<string, number> = { Desqualificado: 0, Desconfiado: 1, Remarketing: 2, Qualificado: 3, Quente: 4 };
const FORA_DO_KANBAN = new Set(['Desqualificado', 'Desconfiado']);

const DESFECHO_OPTIONS: { value: 'encerrado' | 'comprometido' | 'falha'; label: string; color: string; help: string }[] = [
  { value: 'encerrado', label: 'Encerrado', color: 'var(--success)', help: 'Sucesso de comunicação — o cliente conseguiu realizar o que desejava.' },
  { value: 'comprometido', label: 'Comprometido', color: 'var(--warn)', help: 'Algo não saiu conforme o planejado; o cliente pode voltar ou não dar continuidade.' },
  { value: 'falha', label: 'Falha durante o atendimento', color: 'var(--danger)', help: 'O cliente desistiu ou cessou o contato durante o atendimento humano.' },
];

export function Leads({ api, company, role }: { api: Api; company: Company; role: 'atendente' | 'empresa' | 'admin' }) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Lead | null>(null);
  const [events, setEvents] = useState<LeadEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [error, setError] = useState('');
  const [despachando, setDespachando] = useState(false);

  const podeAtender = role === 'atendente';

  function load() {
    setBusy(true);
    setError('');
    api(`/leads/?company=${company.id}`)
      .then((d: Paginated<Lead>) => setLeads(d.results))
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }

  useEffect(() => {
    load();
    setSelected(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [company.id]);

  useEffect(() => {
    setDespachando(false);
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

  async function assumir() {
    if (!selected) return;
    setActionBusy(true);
    setError('');
    try {
      const updated = await api(`/leads/${selected.id}/assumir/?company=${company.id}`, { method: 'POST' });
      setLeads((v) => v.map((l) => (l.id === updated.id ? updated : l)));
      setSelected(updated);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setActionBusy(false);
    }
  }

  async function despachar(desfecho: 'encerrado' | 'comprometido' | 'falha') {
    if (!selected) return;
    setActionBusy(true);
    setError('');
    try {
      const updated = await api(`/leads/${selected.id}/despachar/?company=${company.id}`, { method: 'POST', body: JSON.stringify({ desfecho }) });
      setLeads((v) => v.map((l) => (l.id === updated.id ? updated : l)));
      setSelected(updated);
      setDespachando(false);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setActionBusy(false);
    }
  }

  const desqualificados = leads.filter((l) => FORA_DO_KANBAN.has(l.temperature));

  const visible = leads
    .filter((l) => !l.desfecho)
    .filter((l) => !FORA_DO_KANBAN.has(l.temperature))
    .filter((l) => `${l.name} ${l.contact}`.toLowerCase().includes(search.toLowerCase()));

  const columnOf = (l: Lead): 'novo' | 'triagem' | 'espera' | 'humano' => {
    if (l.mode === 'HUMANO') return 'humano';
    if (l.bot_closed) return 'espera';
    if (l.funnel_stage === 'Novo lead') return 'novo';
    return 'triagem';
  };
  const columns: { key: ReturnType<typeof columnOf>; label: string }[] = [
    { key: 'novo', label: 'Novo lead' },
    { key: 'triagem', label: 'Qualificados' },
    { key: 'espera', label: 'Atendimentos em espera' },
    { key: 'humano', label: 'Em negociação' },
  ];

  function orderedItems(key: ReturnType<typeof columnOf>) {
    const items = visible.filter((l) => columnOf(l) === key);
    if (key === 'espera') {
      // Mais urgente (Quente) primeiro, menos urgente (Remarketing) por último -- Desqualificado/Desconfiado
      // já não entram no Kanban (ver FORA_DO_KANBAN).
      return [...items].sort((a, b) => (URGENCIA_RANK[b.temperature] ?? -1) - (URGENCIA_RANK[a.temperature] ?? -1));
    }
    return items;
  }

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
              const items = orderedItems(col.key);
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
                          {col.key === 'espera' && l.temperature && (
                            <small style={{ display: 'block', marginTop: 4, color: 'var(--muted)' }}>{l.temperature}</small>
                          )}
                          {col.key === 'humano' && l.owner && (
                            <small style={{ display: 'block', marginTop: 4, color: 'var(--muted)' }}>em execução · {l.owner}</small>
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
        <p className="table-note">
          Exibindo até 100 leads por consulta.
          {desqualificados.length > 0 && (
            <> · {desqualificados.length} lead{desqualificados.length === 1 ? '' : 's'} desqualificado{desqualificados.length === 1 ? '' : 's'}/desconfiado{desqualificados.length === 1 ? '' : 's'} (fora do fluxo, ver Dashboard)</>
          )}
        </p>
      </section>

      {selected && (
        <section className="panel detail">
          <div className="detail-head">
            <h2>{selected.name || selected.contact}</h2>
            <button className="secondary" onClick={() => setSelected(null)}>
              Fechar
            </button>
          </div>
          <p style={{ marginBottom: 16 }}>
            Estado: <strong style={{ color: 'var(--ink)' }}>{selected.state}</strong> · Bot {selected.bot_closed ? 'encerrado' : 'ativo'}
            {selected.owner && (
              <>
                {' '}
                · Responsável: <strong style={{ color: 'var(--ink)' }}>{selected.owner}</strong>
              </>
            )}
          </p>

          {podeAtender && (
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 20 }}>
              {selected.bot_closed && !selected.owner && (
                <button type="button" onClick={assumir} disabled={actionBusy} style={{ background: '#2563EB', borderColor: '#2563EB' }}>
                  {actionBusy && <Spinner />}
                  Seguir com o contato
                </button>
              )}
              {selected.contact && (
                <a href={`https://wa.me/${selected.contact.replace(/\D/g, '')}`} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                  <button type="button" style={{ background: '#25D366', borderColor: '#25D366' }}>
                    Conversar
                  </button>
                </a>
              )}
              {selected.mode === 'HUMANO' && (
                <button type="button" className="danger-outline" onClick={() => setDespachando((v) => !v)}>
                  Despachar
                </button>
              )}
            </div>
          )}

          {despachando && (
            <div className="panel" style={{ padding: 16, marginBottom: 20, display: 'flex', flexDirection: 'column', gap: 10 }}>
              <h3 style={{ margin: 0, fontSize: 15 }}>Classificar desfecho</h3>
              {DESFECHO_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => despachar(opt.value)}
                  disabled={actionBusy}
                  style={{ textAlign: 'left', borderColor: opt.color, color: opt.color, background: '#fff' }}
                >
                  <strong style={{ display: 'block' }}>{opt.label}</strong>
                  <small style={{ color: 'var(--muted)', fontWeight: 400 }}>{opt.help}</small>
                </button>
              ))}
            </div>
          )}

          <form key={selected.id} onSubmit={save}>
            <div className="fields">
              <label>
                Nome
                <input name="name" defaultValue={selected.name} />
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
            {podeAtender && (
              <button disabled={busy}>
                {busy && <Spinner />}
                Salvar alterações
              </button>
            )}
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
