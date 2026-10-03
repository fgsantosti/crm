import { useEffect, useState } from 'react';
import type { Api } from '../api';
import type { Company, Lead, LeadEvent, Paginated } from '../types';
import { SkeletonRows, Spinner } from '../components/Skeleton';

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

  return (
    <>
      <header className="page-header">
        <div>
          <small className="eyebrow">Relacionamento · WhatsApp</small>
          <h1>Seus leads, próximos passos claros.</h1>
          <p>Acompanhe a qualificação de cada contato, etapa por etapa.</p>
        </div>
        <span className="tag-pill">CRM multiempresa</span>
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <section className="panel">
        <div className="panel-toolbar">
          <h2>Central de leads</h2>
          <input placeholder="Buscar nome ou telefone" aria-label="Buscar leads" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Contato</th>
                <th>Etapa</th>
                <th>Atendimento</th>
                <th>Prioridade</th>
                <th>Próxima ação</th>
              </tr>
            </thead>
            <tbody>
              {busy && !visible.length && <SkeletonRows rows={4} cols={5} />}
              {visible.map((l) => (
                <tr key={l.id} onClick={() => setSelected(l)} style={{ cursor: 'pointer' }}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{l.name || 'Sem nome informado'}</div>
                    <small>{l.contact}</small>
                  </td>
                  <td>{l.funnel_stage}</td>
                  <td>
                    <span className={`badge ${l.mode === 'HUMANO' ? 'badge-human' : 'badge-auto'}`}>{l.mode === 'HUMANO' ? 'Humano' : 'Automático'}</span>
                  </td>
                  <td>
                    <span className={`priority priority-${l.priority === 'Alta' ? 'alta' : l.priority === 'Média' ? 'media' : 'baixa'}`}>
                      <span className="priority-dot" />
                      {l.priority}
                    </span>
                  </td>
                  <td style={{ color: 'var(--muted)' }}>{l.next_action || 'Aguardando resposta'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
