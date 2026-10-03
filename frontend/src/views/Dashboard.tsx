import { useEffect, useMemo, useState } from 'react';
import type { Api } from '../api';
import type { Company, Lead, Paginated } from '../types';
import { DonutChart } from '../components/DonutChart';
import { SkeletonTiles } from '../components/Skeleton';

const DAY = 24 * 60 * 60 * 1000;

export function Dashboard({ api, company, role }: { api: Api; company: Company; role: 'atendente' | 'empresa' }) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [search, setSearch] = useState('');
  const [area, setArea] = useState('');
  const [periodo, setPeriodo] = useState<'30' | 'all'>('30');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setBusy(true);
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

  const filtered = useMemo(() => {
    const now = Date.now();
    return leads.filter((l) => {
      if (search && !`${l.name} ${l.contact} ${l.owner}`.toLowerCase().includes(search.toLowerCase())) return false;
      if (area && l.especialidade !== area) return false;
      if (periodo === '30' && now - new Date(l.created_at).getTime() > 30 * DAY) return false;
      return true;
    });
  }, [leads, search, area, periodo]);

  const total = filtered.length;
  const concluidos = filtered.filter((l) => l.bot_closed).length;
  const automatico = filtered.filter((l) => !l.bot_closed && l.mode === 'AUTOMÁTICO').length;
  const humano = filtered.filter((l) => l.mode === 'HUMANO').length;

  const monthly = useMemo(() => {
    const buckets = new Map<string, number>();
    filtered.forEach((l) => {
      const key = new Date(l.created_at).toLocaleDateString('pt-BR', { month: 'short' });
      buckets.set(key, (buckets.get(key) || 0) + 1);
    });
    return Array.from(buckets.entries());
  }, [filtered]);
  const maxMonthly = Math.max(1, ...monthly.map(([, v]) => v));

  const byOwner = useMemo(() => {
    const buckets = new Map<string, number>();
    filtered.forEach((l) => {
      const key = l.owner || 'Sem responsável';
      buckets.set(key, (buckets.get(key) || 0) + 1);
    });
    return Array.from(buckets.entries()).sort((a, b) => b[1] - a[1]).slice(0, 5);
  }, [filtered]);

  const byArea = useMemo(() => {
    const buckets = new Map<string, number>();
    filtered.forEach((l) => {
      const key = l.especialidade || 'Sem especialidade';
      buckets.set(key, (buckets.get(key) || 0) + 1);
    });
    return Array.from(buckets.entries()).sort((a, b) => b[1] - a[1]);
  }, [filtered]);

  const pct = (n: number) => (total ? ` · ${Math.round((n / total) * 100)}%` : '');

  return (
    <>
      <header>
        <small className="eyebrow">{role === 'empresa' ? 'Visão consolidada' : 'Visão geral'}</small>
        <h1>{role === 'empresa' ? 'Dashboard da empresa' : 'Dashboard de atendimentos'}</h1>
        <p>{role === 'empresa' ? 'Volume, status e desempenho de toda a equipe.' : 'Volume e status de qualificação da sua empresa.'}</p>
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <section className="section">
        <div className="section-head">
          <h2>Filtros</h2>
          <span style={{ fontSize: 12, color: 'var(--muted)' }}>
            {total} atendimento{total === 1 ? '' : 's'} no período selecionado
          </span>
        </div>
        <div className="filters-bar">
          <label className="search-field">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <circle cx="7" cy="7" r="5" stroke="#8A7A68" strokeWidth="1.5" />
              <path d="M11 11l3.5 3.5" stroke="#8A7A68" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <input placeholder="Buscar lead, contato ou responsável" aria-label="Buscar atendimentos" value={search} onChange={(e) => setSearch(e.target.value)} />
          </label>
          <label className="select-field">
            <select value={area} onChange={(e) => setArea(e.target.value)}>
              <option value="">Todas as áreas</option>
              <option value="Previdenciário">Previdenciário</option>
              <option value="Consumidor">Consumidor</option>
              <option value="Trabalhista">Trabalhista</option>
              <option value="Fora de escopo">Fora de escopo</option>
            </select>
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
              <path d="M4 6l4 4 4-4" stroke="#8A7A68" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </label>
          <label className="select-field">
            <select value={periodo} onChange={(e) => setPeriodo(e.target.value as '30' | 'all')}>
              <option value="30">Últimos 30 dias</option>
              <option value="all">Todo o período</option>
            </select>
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
              <path d="M4 6l4 4 4-4" stroke="#8A7A68" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </label>
          <button
            type="button"
            className="secondary"
            style={{ marginLeft: 'auto' }}
            onClick={() => {
              setSearch('');
              setArea('');
              setPeriodo('30');
            }}
          >
            Limpar
          </button>
        </div>
      </section>

      <section className="section">
        <h2>Resumo</h2>
        {busy && !leads.length ? (
          <SkeletonTiles />
        ) : (
          <div className="tiles">
            <article className="tile">
              <small>Total de atendimentos</small>
              <strong style={{ color: 'var(--ink)' }}>{total}</strong>
            </article>
            <article className="tile">
              <small>Concluídos</small>
              <strong style={{ color: 'var(--success)' }}>{concluidos}</strong>
            </article>
            <article className="tile">
              <small>Em automação</small>
              <strong style={{ color: 'var(--accent)' }}>{automatico}</strong>
            </article>
            <article className="tile">
              <small>Com a equipe</small>
              <strong style={{ color: 'var(--danger)' }}>{humano}</strong>
            </article>
          </div>
        )}
      </section>

      <div className="section-divider" />

      <section className="section">
        <h2>Status e distribuição</h2>
        <div className="card-grid2">
          <article className="card">
            <h3>Status dos atendimentos</h3>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 28, alignItems: 'center', justifyContent: 'center' }}>
              <DonutChart
                segments={[
                  { label: 'Concluído', value: concluidos, color: 'var(--success)' },
                  { label: 'Em triagem automática', value: automatico, color: 'var(--accent)' },
                  { label: 'Atendimento humano', value: humano, color: 'var(--danger)' },
                ].filter((s) => s.value > 0)}
              />
              <ul className="legend">
                <li>
                  <span className="legend-dot" style={{ background: 'var(--success)' }} />
                  <span style={{ flex: 1 }}>Concluído</span>
                  <strong style={{ fontFamily: "'DM Mono',monospace" }}>
                    {concluidos}
                    {pct(concluidos)}
                  </strong>
                </li>
                <li>
                  <span className="legend-dot" style={{ background: 'var(--accent)' }} />
                  <span style={{ flex: 1 }}>Em triagem automática</span>
                  <strong style={{ fontFamily: "'DM Mono',monospace" }}>
                    {automatico}
                    {pct(automatico)}
                  </strong>
                </li>
                <li>
                  <span className="legend-dot" style={{ background: 'var(--danger)' }} />
                  <span style={{ flex: 1 }}>Atendimento humano</span>
                  <strong style={{ fontFamily: "'DM Mono',monospace" }}>
                    {humano}
                    {pct(humano)}
                  </strong>
                </li>
              </ul>
            </div>
          </article>

          <article className="card">
            <h3>Atendimentos por área</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {byArea.map(([name, count]) => (
                <div key={name} className="bar-row">
                  <div className="bar-labels">
                    <span>{name}</span>
                    <strong style={{ fontFamily: "'DM Mono',monospace", color: 'var(--ink)' }}>
                      {count}
                      {pct(count)}
                    </strong>
                  </div>
                  <div className="bar-track">
                    <div className="bar-fill" style={{ width: `${total ? Math.round((count / total) * 100) : 0}%` }} />
                  </div>
                </div>
              ))}
              {!byArea.length && <p style={{ fontSize: 13 }}>Sem dados para o período.</p>}
            </div>
            <p style={{ marginTop: 'auto', fontSize: 12, color: 'var(--muted)' }}>Área vem da especialidade classificada pelo agente — ainda sem área quer dizer que a triagem não chegou lá.</p>
          </article>
        </div>
      </section>

      <div className="section-divider" />

      <section className="section">
        <h2>Tendência</h2>
        <div className="card">
          <h3>Atendimentos por mês</h3>
          <div className="trend">
            {monthly.map(([label, value]) => (
              <div key={label} className="trend-col">
                {value === maxMonthly && <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 12.5, fontWeight: 500 }}>{value}</span>}
                <div className={`trend-bar ${value === maxMonthly ? 'active' : ''}`} style={{ height: Math.max(8, Math.round((value / maxMonthly) * 120)) }} />
                <small>{label}</small>
              </div>
            ))}
            {!monthly.length && <p style={{ fontSize: 13 }}>Sem dados para o período.</p>}
          </div>
        </div>
      </section>

      {role === 'empresa' && (
        <>
          <div className="section-divider" />
          <section className="section">
            <div className="section-head">
              <h2>Desempenho por atendente</h2>
              <label className="search-field" style={{ flex: '0 1 220px' }}>
                <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                  <circle cx="7" cy="7" r="5" stroke="#8A7A68" strokeWidth="1.5" />
                  <path d="M11 11l3.5 3.5" stroke="#8A7A68" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
                <input placeholder="Buscar atendente" aria-label="Buscar atendente" value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 220 }} />
              </label>
            </div>
            <div className="panel">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Atendente</th>
                      <th>Atendimentos</th>
                      <th>Concluídos</th>
                      <th>Taxa de conclusão</th>
                    </tr>
                  </thead>
                  <tbody>
                    {byOwner.map(([name, count]) => {
                      const done = filtered.filter((l) => (l.owner || 'Sem responsável') === name && l.bot_closed).length;
                      const rate = count ? Math.round((done / count) * 100) : 0;
                      return (
                        <tr key={name}>
                          <td style={{ fontWeight: 600 }}>{name}</td>
                          <td style={{ fontFamily: "'DM Mono',monospace" }}>{count}</td>
                          <td style={{ fontFamily: "'DM Mono',monospace" }}>{done}</td>
                          <td style={{ color: rate >= 50 ? 'var(--success)' : 'var(--warn)', fontWeight: 600 }}>{rate}%</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {!byOwner.length && <div className="empty">{busy ? 'Carregando…' : 'Sem dados de equipe para o período.'}</div>}
            </div>
          </section>
        </>
      )}
    </>
  );
}
