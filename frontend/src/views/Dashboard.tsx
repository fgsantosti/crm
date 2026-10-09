import { useEffect, useMemo, useState } from 'react';
import { fetchTodasAsPaginas, type Api } from '../api';
import type { Area, Company, Lead, Paginated } from '../types';
import { DonutChart } from '../components/DonutChart';
import { SkeletonTiles } from '../components/Skeleton';
import { COLUMNS, URGENCIA_COR, columnOf, leadsVisiveisNoKanban, ordenarColuna } from './Leads';
import { DashboardAtendimentosDialog, type AtendimentoResumo } from '../components/DashboardAtendimentosDialog';
import { ConfirmPessoa, useConfirmar } from '../components/ConfirmDialog';

type Resumo = {
  total: number;
  /** Novas leads criadas pelo agente no período (inclui as apagadas); null com filtro de área/busca. */
  novas_leads: number | null;
  /** Triagens abandonadas apagadas pelo Celery no período; null com filtro de área/busca. */
  nao_prosseguiram: number | null;
  novas_hoje: number;
  triagem_concluida: number;
  desqualificados: number;
  status: { despachado: number; automatico: number; aguardando: number; equipe: number; desqualificado: number; especial: number; nao_prosseguiram: number };
  desfechos: Record<'encerrado' | 'comprometido' | 'falha' | 'bloqueado', number>;
  por_area: [string, number][];
  por_mes: [string, number][];
  por_owner: { owner_id: number; owner: string; atendimentos: number; concluidos: number; sucesso: number }[];
  sucesso: number;
  concluidos: LeadConcluido[];
  atendimentos: AtendimentoResumo[];
};

type LeadConcluido = {
  id: string;
  name: string;
  contact: string;
  temperature: string;
  priority: string;
  especialidade: string;
  desfecho: 'encerrado' | 'comprometido' | 'falha' | 'bloqueado';
  owner: string;
  concluido_em: string | null;
  created_at: string;
  origem_manual: boolean;
};

const RESUMO_VAZIO: Resumo = {
  total: 0, novas_leads: 0, nao_prosseguiram: 0, novas_hoje: 0, triagem_concluida: 0, desqualificados: 0,
  status: { despachado: 0, automatico: 0, aguardando: 0, equipe: 0, desqualificado: 0, especial: 0, nao_prosseguiram: 0 },
  desfechos: { encerrado: 0, comprometido: 0, falha: 0, bloqueado: 0 },
  por_area: [], por_mes: [], por_owner: [], sucesso: 0, concluidos: [], atendimentos: [],
};

function rotuloMes(chave: string) {
  const [ano, mes] = chave.split('-').map(Number);
  return new Date(ano, mes - 1, 1).toLocaleDateString('pt-BR', { month: 'short', year: '2-digit' });
}

const STATUS_DONUT: { key: keyof Resumo['status']; label: string; color: string }[] = [
  { key: 'despachado', label: 'Despachado', color: 'var(--success)' },
  { key: 'automatico', label: 'Em triagem', color: '#2563EB' },
  { key: 'aguardando', label: 'Triagem concluída', color: 'var(--warn)' },
  { key: 'equipe', label: 'Com a equipe', color: 'var(--accent)' },
  { key: 'desqualificado', label: 'Desqualificado/desconfiado', color: 'var(--muted)' },
  { key: 'especial', label: 'Outras situações', color: '#7C3AED' },
  { key: 'nao_prosseguiram', label: 'Não prosseguiram', color: 'var(--muted-soft)' },
];

const DESFECHO_LABELS: { value: LeadConcluido['desfecho']; label: string; color: string }[] = [
  { value: 'encerrado', label: 'Encerrado', color: 'var(--success)' },
  { value: 'comprometido', label: 'Comprometido', color: 'var(--warn)' },
  { value: 'falha', label: 'Falha durante o atendimento', color: 'var(--danger)' },
  { value: 'bloqueado', label: 'Bloqueado', color: '#111111' },
];

export function Dashboard({ api, company, role }: { api: Api; company: Company; role: 'atendente' | 'empresa' }) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [resumo, setResumo] = useState<Resumo>(RESUMO_VAZIO);
  const [areas, setAreas] = useState<Area[]>([]);
  const [search, setSearch] = useState('');
  const [buscaAtendente, setBuscaAtendente] = useState('');
  const [area, setArea] = useState('');
  const [periodo, setPeriodo] = useState<'30' | 'all' | 'custom'>('30');
  const [dataInicio, setDataInicio] = useState(() => new Date().toLocaleDateString('en-CA', { timeZone: 'America/Fortaleza' }));
  const [dataFim, setDataFim] = useState(() => new Date().toLocaleDateString('en-CA', { timeZone: 'America/Fortaleza' }));
  const confirmar = useConfirmar();
  const [popup, setPopup] = useState<{ title: string; description: string; atendimentos: AtendimentoResumo[]; desqualificacao?: boolean } | null>(null);
  const erroPeriodo = periodo === 'custom' ? (!dataInicio || !dataFim ? 'Selecione as datas de início e fim.' : dataInicio > dataFim ? 'A data de início deve ser anterior ou igual à data de fim.' : '') : '';
  const [busy, setBusy] = useState(false);
  const [carregou, setCarregou] = useState(false);
  const [excluindoId, setExcluindoId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [recarregar, setRecarregar] = useState(0);
  // "Concluído com sucesso" = desfecho Encerrado (ver services.DESFECHO_SUCESSO).
  const [filtroConcluidos, setFiltroConcluidos] = useState<'sucesso' | 'todos'>('sucesso');

  useEffect(() => {
    let active = true;
    api(`/areas/?company=${company.id}`)
      .then((d: Paginated<Area>) => active && setAreas(d.results))
      .catch(() => undefined);
    if (role === 'empresa') {
      fetchTodasAsPaginas<Lead>(api, `/leads/?company=${company.id}&ativos=1`)
        .then((todos) => active && setLeads(todos))
        .catch((e) => active && setError(e.message));
    }
    return () => {
      active = false;
    };
  }, [company.id, role, recarregar]);

  useEffect(() => {
    let active = true;
    setPopup(null);
    if (erroPeriodo) {
      setResumo(RESUMO_VAZIO);
      setBusy(false);
      return;
    }
    setBusy(true);
    setError('');
    const params = new URLSearchParams({ company: String(company.id), dias: periodo === '30' ? '30' : 'all' });
    if (periodo === 'custom') {
      params.set('data_inicio', dataInicio);
      params.set('data_fim', dataFim);
    }
    if (area) params.set('area', area);
    if (search.trim()) params.set('q', search.trim());
    const timer = setTimeout(() => {
      api(`/leads/resumo/?${params.toString()}`)
        .then((d: Resumo) => {
          if (active) setResumo({ ...RESUMO_VAZIO, ...d });
        })
        .catch((e) => {
          if (active) setError(e.message);
        })
        .finally(() => {
          if (active) {
            setBusy(false);
            setCarregou(true);
          }
        });
    }, search ? 250 : 0);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [company.id, area, periodo, dataInicio, dataFim, erroPeriodo, search, recarregar]);

  const total = resumo.total;
  const desqualificados = resumo.desqualificados;
  const concluidos = resumo.triagem_concluida;
  const automatico = resumo.status.automatico;
  const humano = resumo.status.equipe;
  const concluidosPorDesfecho = DESFECHO_LABELS.map((d) => ({ ...d, count: resumo.desfechos[d.value] }));
  const totalDespachados = concluidosPorDesfecho.reduce((sum, d) => sum + d.count, 0);
  const listaConcluidos = filtroConcluidos === 'sucesso' ? resumo.concluidos.filter((c) => c.desfecho === 'encerrado') : resumo.concluidos;
  const corDesfecho = (v: string) => DESFECHO_LABELS.find((d) => d.value === v);

  const monthly = resumo.por_mes.map(([k, v]) => [rotuloMes(k), v] as [string, number]);
  const maxMonthly = Math.max(1, ...monthly.map(([, v]) => v));
  const byArea = resumo.por_area;
  const byOwner = resumo.por_owner.filter((o) => o.owner.toLowerCase().includes(buscaAtendente.toLowerCase()));

  const pct = (n: number) => (total ? ` · ${Math.round((n / total) * 100)}%` : '');

  const kanbanLeads = useMemo(() => {
    const ids = new Set(resumo.atendimentos.map((lead) => lead.id));
    return leadsVisiveisNoKanban(leads).filter((lead) => ids.has(lead.id));
  }, [leads, resumo.atendimentos]);

  function abrirPopup(title: string, description: string, matches: (lead: AtendimentoResumo) => boolean, desqualificacao = false) {
    setPopup({ title, description, atendimentos: resumo.atendimentos.filter(matches), desqualificacao });
  }

  const cardsResumo = [
    { title: 'Total de atendimentos', count: total, color: 'var(--ink)', description: 'Todos os atendimentos do período selecionado.', matches: (_lead: AtendimentoResumo) => true },
    { title: 'Triagem concluída', count: concluidos, color: 'var(--warn)', description: 'Leads classificadas que aguardam a equipe: Qualificados e Atendimentos em espera.', matches: (lead: AtendimentoResumo) => lead.triagem_concluida },
    { title: 'Em triagem', count: automatico, color: '#2563EB', description: 'Atendimentos aguardando a conclusão da triagem automática.', matches: (lead: AtendimentoResumo) => lead.categoria_status === 'automatico' },
    { title: 'Com a equipe', count: humano, color: 'var(--accent)', description: 'Atendimentos em negociação com um atendente (incluindo os que estão em despacho) e os cadastrados manualmente pelos atendentes.', matches: (lead: AtendimentoResumo) => lead.categoria_status === 'equipe' },
    { title: 'Despachos', count: resumo.status.despachado, color: 'var(--success)', description: 'Atendimentos concluídos e despachados pela equipe (encerrado, comprometido, falha ou bloqueado) no período selecionado, incluindo os acompanhamentos de Outras situações.', matches: (lead: AtendimentoResumo) => lead.categoria_status === 'despachado' },
    { title: 'Desqualificados', count: desqualificados, color: 'var(--muted)', description: 'Leads classificados como desqualificados ou desconfiados.', matches: (lead: AtendimentoResumo) => lead.categoria_status === 'desqualificado', desqualificacao: true },
    { title: 'Outras situações', count: resumo.status.especial, color: '#7C3AED', description: 'Acompanhamentos em aberto: clientes que já têm processo e querem acompanhá-lo (não são leads novos). Depois de despachados, passam a contar em Despachos.', matches: (lead: AtendimentoResumo) => lead.categoria_status === 'especial' },
    { title: 'Não prosseguiram', count: resumo.nao_prosseguiram, color: 'var(--muted)', description: 'Triagens abandonadas que o sistema apagou automaticamente (sem resposta por 24h).', matches: (_lead: AtendimentoResumo) => false, semLista: true, detalhe: resumo.nao_prosseguiram === null ? 'indisponível com filtro de área/busca' : 'apagadas automaticamente' },
  ];

  // "Fechar lead": apaga o lead (e o histórico dele) no CRM. A próxima mensagem desse número
  // abre um lead novo e o agente recomeça a triagem do zero.
  async function removerLead(lead: Lead) {
    const ok = await confirmar({
      titulo: `Fechar o lead "${lead.name || lead.contact}"?`,
      mensagem: 'O lead e o histórico dele serão apagados. Se esse número mandar mensagem de novo, o agente recomeça a triagem do zero.',
      detalhe: <ConfirmPessoa nome={lead.name || lead.contact} sub={lead.contact} selo="Irreversível" />,
      tom: 'perigo',
      icone: 'lixeira',
      confirmar: 'Fechar lead',
    });
    if (!ok) return;
    setExcluindoId(lead.id);
    setError('');
    try {
      await api(`/leads/${lead.id}/?company=${company.id}`, { method: 'DELETE' });
      setLeads((v) => v.filter((l) => l.id !== lead.id));
      setRecarregar((n) => n + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setExcluindoId(null);
    }
  }

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
              {areas.map((a) => (
                <option key={a.id} value={a.name}>
                  {a.name}
                </option>
              ))}
            </select>
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
              <path d="M4 6l4 4 4-4" stroke="#8A7A68" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </label>
          <label className="select-field">
            <select aria-label="Período" value={periodo} onChange={(e) => setPeriodo(e.target.value as '30' | 'all' | 'custom')}>
              <option value="30">Últimos 30 dias</option>
              <option value="all">Todo o período</option>
              <option value="custom">Período específico</option>
            </select>
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
              <path d="M4 6l4 4 4-4" stroke="#8A7A68" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </label>
          {periodo === 'custom' && (
            <>
              <label className="dashboard-date">Data de início<input type="date" value={dataInicio} max={dataFim || undefined} onChange={(e) => setDataInicio(e.target.value)} /></label>
              <label className="dashboard-date">Data de fim<input type="date" value={dataFim} min={dataInicio || undefined} onChange={(e) => setDataFim(e.target.value)} /></label>
            </>
          )}
          <button
            type="button"
            className="secondary"
            style={{ marginLeft: 'auto' }}
            onClick={() => {
              setSearch('');
              setArea('');
              setPeriodo('30');
              const hoje = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Fortaleza' });
              setDataInicio(hoje);
              setDataFim(hoje);
            }}
          >
            Limpar
          </button>
        </div>
        {erroPeriodo && <p role="alert" className="error" style={{ marginTop: 12 }}>{erroPeriodo}</p>}
      </section>

      <section className="section">
        <h2>Resumo</h2>
        {busy && !carregou ? (
          <SkeletonTiles />
        ) : (
          <div className="tiles">
            {cardsResumo.map((card) =>
              card.semLista ? (
                <div key={card.title} className="tile" title={card.description}>
                  <small>{card.title}</small>
                  <strong style={{ color: card.color }}>{card.count ?? '—'}</strong>
                  {card.detalhe && <small style={{ display: 'block', marginTop: 4, color: 'var(--muted)' }}>{card.detalhe}</small>}
                </div>
              ) : (
                <button key={card.title} type="button" className="tile tile-button" disabled={busy || !!erroPeriodo} aria-haspopup="dialog" onClick={() => abrirPopup(card.title, card.description, card.matches, 'desqualificacao' in card && card.desqualificacao === true)}>
                  <small>{card.title}</small>
                  <strong style={{ color: card.color }}>{card.count}</strong>
                  {card.detalhe && <small style={{ display: 'block', marginTop: 4, color: 'var(--muted)' }}>{card.detalhe}</small>}
                </button>
              ),
            )}
          </div>
        )}
        {!busy && desqualificados > 0 && (
          <p style={{ marginTop: 10, fontSize: 12, color: 'var(--muted)' }}>
            Leads desqualificados/desconfiados são classificados diretamente pelo agente e nunca entram no Kanban de atendimento humano.
          </p>
        )}
      </section>

      {role === 'empresa' && (
        <>
          <div className="section-divider" />
          <section className="section">
            <div className="section-head">
              <h2>Kanban de atendimento</h2>
              <span style={{ fontSize: 12, color: 'var(--muted)' }}>Somente visualização — a empresa não assume nem contata leads.</span>
            </div>
            {!carregou ? (
              <SkeletonTiles />
            ) : (
              <div className="kanban">
                {COLUMNS.map((col) => {
                  const items = ordenarColuna(col.key, kanbanLeads.filter((l) => columnOf(l) === col.key));
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
                          <article key={l.id} className="kanban-card" style={{ cursor: 'default', position: 'relative' }}>
                            <button
                              type="button"
                              aria-label={`Fechar lead ${l.name || l.contact} (apaga e reinicia a triagem)`}
                              title="Fechar lead (apaga e reinicia a triagem)"
                              onClick={() => removerLead(l)}
                              disabled={excluindoId === l.id}
                              style={{
                                position: 'absolute', top: 6, right: 6, width: 22, height: 22, padding: 0,
                                borderRadius: '50%', background: 'var(--panel-muted)', color: 'var(--danger)',
                                fontSize: 13, lineHeight: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
                              }}
                            >
                              ×
                            </button>
                            <span
                              className="priority-dot"
                              style={URGENCIA_COR[l.temperature] ? { background: URGENCIA_COR[l.temperature] } : undefined}
                            />
                            <div style={{ minWidth: 0, flex: 1 }}>
                              <div style={{ fontWeight: 600, fontSize: 13.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {l.name || 'Sem nome informado'}
                              </div>
                              <small style={{ display: 'block', fontFamily: "'DM Mono',monospace" }}>{l.contact}</small>
                              {col.key === 'novos' && <small style={{ display: 'block', marginTop: 4, color: 'var(--accent)' }}>etapa: {l.state}</small>}
                              {l.temperature && col.key !== 'novos' && (
                                <small style={{ display: 'block', marginTop: 4, color: 'var(--muted)' }}>{l.temperature}</small>
                              )}
                              {l.owner && col.key !== 'qualificados' && (
                                <small style={{ display: 'block', marginTop: 4, color: 'var(--muted)' }}>owner: {l.owner_nome}</small>
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
          </section>
        </>
      )}

      <div className="section-divider" />

      <section className="section">
        <div className="section-head">
          <h2>Concluído</h2>
          <span style={{ fontSize: 12, color: 'var(--muted)' }}>
            {totalDespachados} lead{totalDespachados === 1 ? '' : 's'} despachado{totalDespachados === 1 ? '' : 's'} pela equipe
          </span>
        </div>
        {busy && !carregou ? (
          <SkeletonTiles />
        ) : (
          <div className="tiles">
            {concluidosPorDesfecho.map((d) => (
              <button key={d.value} type="button" className="tile tile-button" disabled={busy || !!erroPeriodo} aria-haspopup="dialog" onClick={() => abrirPopup(d.label, 'Atendimentos com este desfecho no período selecionado.', (lead) => lead.desfecho === d.value)}>
                <small>{d.label}</small>
                <strong style={{ color: d.color }}>{d.count}</strong>
              </button>
            ))}
          </div>
        )}
        {!busy && !totalDespachados && <p style={{ marginTop: 10, fontSize: 12, color: 'var(--muted)' }}>Nenhum atendimento despachado no período selecionado.</p>}
        {totalDespachados > 0 && (
          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-toolbar">
              <h2>Atendimentos concluídos</h2>
              <div style={{ display: 'flex', gap: 8 }}>
                <button type="button" className={filtroConcluidos === 'sucesso' ? undefined : 'secondary'} onClick={() => setFiltroConcluidos('sucesso')}>
                  Com sucesso ({resumo.sucesso})
                </button>
                <button type="button" className={filtroConcluidos === 'todos' ? undefined : 'secondary'} onClick={() => setFiltroConcluidos('todos')}>
                  Todos ({resumo.concluidos.length})
                </button>
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Lead</th>
                    <th>Área</th>
                    <th>Temperatura</th>
                    <th>Prioridade</th>
                    <th>Desfecho</th>
                    <th>Atendente</th>
                    <th>Concluído em</th>
                  </tr>
                </thead>
                <tbody>
                  {listaConcluidos.map((c) => {
                    const d = corDesfecho(c.desfecho);
                    return (
                      <tr key={c.id}>
                        <td>
                          <strong style={{ display: 'block' }}>{c.name || 'Sem nome informado'}</strong>
                          <small style={{ fontFamily: "'DM Mono',monospace", color: 'var(--muted)' }}>
                            {c.contact}
                            {c.origem_manual ? ' · cadastro manual' : ''}
                          </small>
                        </td>
                        <td>{c.especialidade || '—'}</td>
                        <td>{c.temperature || '—'}</td>
                        <td>{c.priority || '—'}</td>
                        <td style={{ color: d?.color, fontWeight: 600 }}>{d?.label || c.desfecho}</td>
                        <td>{c.owner || '—'}</td>
                        <td style={{ fontFamily: "'DM Mono',monospace" }}>{c.concluido_em ? new Date(c.concluido_em).toLocaleString('pt-BR') : '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {!listaConcluidos.length && <div className="empty">Nenhum atendimento concluído com sucesso no período selecionado.</div>}
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
                  ...STATUS_DONUT.map((st) => ({ label: st.label, value: resumo.status[st.key], color: st.color })),
                ].filter((s) => s.value > 0)}
              />
              <ul className="legend">
                {STATUS_DONUT.map((st) => (
                  <li key={st.key}>
                    <span className="legend-dot" style={{ background: st.color }} />
                    <span style={{ flex: 1 }}>{st.label}</span>
                    <strong style={{ fontFamily: "'DM Mono',monospace" }}>
                      {resumo.status[st.key]}
                      {pct(resumo.status[st.key])}
                    </strong>
                  </li>
                ))}
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
                <input placeholder="Buscar atendente" aria-label="Buscar atendente" value={buscaAtendente} onChange={(e) => setBuscaAtendente(e.target.value)} style={{ width: 220 }} />
              </label>
            </div>
            <div className="panel">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Atendente</th>
                      <th>Atendimentos</th>
                      <th>Despachados</th>
                      <th>Com sucesso</th>
                      <th>Taxa de conclusão</th>
                    </tr>
                  </thead>
                  <tbody>
                    {byOwner.map((o) => {
                      const rate = o.atendimentos ? Math.round((o.concluidos / o.atendimentos) * 100) : 0;
                      return (
                        <tr key={o.owner_id}>
                          <td style={{ fontWeight: 600 }}>{o.owner}</td>
                          <td style={{ fontFamily: "'DM Mono',monospace" }}>{o.atendimentos}</td>
                          <td style={{ fontFamily: "'DM Mono',monospace" }}>{o.concluidos}</td>
                          <td style={{ fontFamily: "'DM Mono',monospace" }}>{o.sucesso}</td>
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
      {popup && <DashboardAtendimentosDialog {...popup} historico={company.coletar_historico_conversa ? { api, companyId: company.id } : undefined} onClose={() => setPopup(null)} />}
    </>
  );
}
