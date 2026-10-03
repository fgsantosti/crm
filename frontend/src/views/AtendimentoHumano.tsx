import { useEffect, useState } from 'react';
import type { Api } from '../api';
import type { Company, Lead, Paginated } from '../types';
import { SkeletonCards } from '../components/Skeleton';

export function AtendimentoHumano({ api, company }: { api: Api; company: Company }) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setBusy(true);
    setError('');
    api(`/leads/?company=${company.id}`)
      .then((d: Paginated<Lead>) => {
        if (active) setLeads(d.results.filter((l) => l.mode === 'HUMANO'));
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

  async function assumir(lead: Lead) {
    try {
      const updated = await api(`/leads/${lead.id}/?company=${company.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ owner: 'Você' }),
      });
      setLeads((v) => v.map((l) => (l.id === updated.id ? updated : l)));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const visible = leads.filter((l) => `${l.name} ${l.contact}`.toLowerCase().includes(search.toLowerCase()));

  return (
    <>
      <header className="page-header" style={{ alignItems: 'flex-end' }}>
        <div>
          <small className="eyebrow">Escalonamento</small>
          <h1>Atendimento humano</h1>
          <p>
            {leads.length} caso{leads.length === 1 ? '' : 's'} saíram da automação e esperam um atendente.
          </p>
        </div>
        <input
          placeholder="Buscar nome ou telefone"
          aria-label="Buscar atendimentos humanos"
          style={{ width: 260 }}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <section className="section">
        {busy && !visible.length && <SkeletonCards count={3} height={96} />}
        {visible.map((l) => (
          <article key={l.id} className="queue-card">
            <div style={{ flex: '1 1 320px', minWidth: 0 }}>
              <div className="queue-meta">
                <strong style={{ fontSize: 16 }}>{l.name || 'Sem nome informado'}</strong>
                <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 12.5, color: 'var(--muted)' }}>{l.contact}</span>
              </div>
              <p style={{ color: 'var(--ink)', marginBottom: 4 }}>{l.next_action || l.notes || 'Sem detalhes registrados.'}</p>
              <p style={{ fontSize: 12.5 }}>
                {l.last_contact ? `Último contato em ${new Date(l.last_contact).toLocaleString('pt-BR')}` : 'Sem contato registrado'} ·{' '}
                {l.owner ? `responsável ${l.owner}` : 'sem responsável'}
              </p>
            </div>
            {l.owner ? <span className="status-pill">Em atendimento</span> : <button onClick={() => assumir(l)}>Assumir atendimento</button>}
          </article>
        ))}
        {!busy && !visible.length && <div className="empty">Nenhum caso em atendimento humano nesta empresa.</div>}
      </section>
    </>
  );
}
