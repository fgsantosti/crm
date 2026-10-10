import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchTodasAsPaginas, type Api } from '../api';
import type { Area, Company, Lead, Paginated } from '../types';
import { SkeletonTiles } from '../components/Skeleton';
import { COLUMNS, columnOf, foraDoKanban, leadsVisiveisNoKanban, ordenarColuna } from './Leads';
import { KanbanCardConteudo, KanbanColunaHead, TEMPERATURA_VISUAL } from '../components/KanbanVisual';
import { useFlipKanban } from '../useFlipKanban';
import { NumeroAnimado } from '../components/NumeroAnimado';
import { LeadDetalheDialog } from '../components/LeadDetalheDialog';
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
  /** Leads classificadas por temperatura (Desqualificado ... Quente). */
  por_temperatura: Record<string, number>;
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
  por_area: [], por_temperatura: {}, por_mes: [], por_owner: [], sucesso: 0, concluidos: [], atendimentos: [],
};

function rotuloMes(chave: string) {
  const [ano, mes] = chave.split('-').map(Number);
  return new Date(ano, mes - 1, 1).toLocaleDateString('pt-BR', { month: 'short', year: '2-digit' });
}

const STATUS_DONUT: { key: keyof Resumo['status']; label: string; color: string }[] = [
  { key: 'automatico', label: 'Em triagem', color: '#2563EB' },
  { key: 'aguardando', label: 'Triagem concluída', color: '#C88A1E' },
  { key: 'equipe', label: 'Com a equipe', color: '#D9531A' },
  { key: 'despachado', label: 'Despachos', color: '#2F7D5C' },
  { key: 'especial', label: 'Outras situações', color: '#7C3AED' },
  { key: 'desqualificado', label: 'Desqualificados', color: '#8C7B69' },
  { key: 'nao_prosseguiram', label: 'Não prosseguiram', color: '#D8CBBB' },
];

// Gráficos de barra: do maior para o menor, da esquerda para a direita; a cor é sempre a da própria categoria.
function ranquear<T extends { value: number }>(itens: T[]): (T & { posicao: number })[] {
  return [...itens].sort((a, b) => b.value - a.value).map((it, i) => ({ ...it, posicao: i + 1 }));
}

// Mesmas cores de classificação do Kanban (TEMPERATURA_VISUAL); as duas temperaturas de descarte em tons neutros.
const COR_TEMPERATURA: Record<string, string> = {
  Quente: TEMPERATURA_VISUAL.Quente.ponto,
  Qualificado: TEMPERATURA_VISUAL.Qualificado.ponto,
  Frio: TEMPERATURA_VISUAL.Frio.ponto,
  Desconfiado: '#8C7B69',
  Desqualificado: '#C9BBA9',
};

const ETAPA_VISUAL: Record<AtendimentoResumo['categoria_status'], { rotulo: string; fundo: string; cor: string }> = {
  automatico: { rotulo: 'Em triagem', fundo: '#E3ECFD', cor: '#1D4FBF' },
  aguardando: { rotulo: 'Triagem concluída', fundo: '#FBF0D8', cor: '#7A4F0E' },
  equipe: { rotulo: 'Com a equipe', fundo: '#FBE3D0', cor: '#A83E12' },
  despachado: { rotulo: 'Despachado', fundo: '#EEF7F1', cor: '#245F46' },
  desqualificado: { rotulo: 'Desqualificado', fundo: '#EDE6DC', cor: '#4E4136' },
  especial: { rotulo: 'Outras situações', fundo: '#EDE4FB', cor: '#5B21B6' },
};

const TEMPERATURAS = ['Quente', 'Qualificado', 'Frio', 'Desconfiado', 'Desqualificado'];

const DESFECHO_LABELS: { value: LeadConcluido['desfecho']; label: string; color: string; fundo: string; borda: string }[] = [
  { value: 'encerrado', label: 'Encerrado', color: '#245F46', fundo: '#EEF7F1', borda: '#CFE5D8' },
  { value: 'comprometido', label: 'Comprometido', color: '#7A4F0E', fundo: '#FCF4E4', borda: '#F1DDB8' },
  { value: 'falha', label: 'Falha durante o atendimento', color: '#93251B', fundo: '#FBEDEA', borda: '#F0CFC9' },
  { value: 'bloqueado', label: 'Bloqueado', color: '#241A12', fundo: '#F3EFEA', borda: '#DDD5CB' },
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
  const [detalhe, setDetalhe] = useState<Lead | null>(null);
  const quadroRef = useRef<HTMLDivElement>(null);
  useFlipKanban(quadroRef);
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
    }, 0);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [company.id, area, periodo, dataInicio, dataFim, erroPeriodo, recarregar]);

  // Busca: lista os leads que combinam (nome, telefone ou responsável) em todo o histórico, sem filtrar o dashboard.
  const termo = search.trim();
  const buscaAtiva = termo.length >= 2;
  const [resultados, setResultados] = useState<AtendimentoResumo[]>([]);
  const [buscando, setBuscando] = useState(false);
  useEffect(() => {
    if (!buscaAtiva) {
      setResultados([]);
      setBuscando(false);
      return;
    }
    let active = true;
    setBuscando(true);
    const timer = setTimeout(() => {
      api(`/leads/resumo/?company=${company.id}&dias=all&q=${encodeURIComponent(termo)}`)
        .then((d: Resumo) => active && setResultados(d.atendimentos ?? []))
        .catch((e) => active && setError(e.message))
        .finally(() => active && setBuscando(false));
    }, 300);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [company.id, termo, buscaAtiva, recarregar]);

  async function detalharResultado(r: AtendimentoResumo) {
    try {
      setDetalhe(await api(`/leads/${r.id}/?company=${company.id}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }

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


  const kanbanLeads = useMemo(() => {
    const ids = new Set(resumo.atendimentos.map((lead) => lead.id));
    return leadsVisiveisNoKanban(leads, foraDoKanban(company)).filter((lead) => ids.has(lead.id));
  }, [leads, resumo.atendimentos]);

  function abrirPopup(title: string, description: string, matches: (lead: AtendimentoResumo) => boolean, desqualificacao = false) {
    setPopup({ title, description, atendimentos: resumo.atendimentos.filter(matches), desqualificacao });
  }

  // Fluxo do atendimento: as 4 etapas em ordem (cada uma abre a lista) e as saídas do fluxo.
  const etapasFluxo = [
    { passo: 1, title: 'Em triagem', count: automatico, cor: '#2563EB', texto: 'O agente ainda está conduzindo a conversa.', description: 'Atendimentos aguardando a conclusão da triagem automática.', matches: (lead: AtendimentoResumo) => lead.categoria_status === 'automatico' },
    { passo: 2, title: 'Triagem concluída', count: concluidos, cor: '#9A6614', texto: 'Classificadas, aguardando a equipe: Qualificados e Em espera.', description: 'Leads classificadas que aguardam a equipe: Qualificados e Atendimentos em espera.', matches: (lead: AtendimentoResumo) => lead.triagem_concluida },
    { passo: 3, title: 'Com a equipe', count: humano, cor: '#C2461A', texto: 'Em negociação ou em despacho com um atendente.', description: 'Atendimentos em negociação com um atendente (incluindo os que estão em despacho) e os cadastrados manualmente pelos atendentes.', matches: (lead: AtendimentoResumo) => lead.categoria_status === 'equipe' },
    { passo: 4, title: 'Despachos', count: resumo.status.despachado, cor: '#2F7D5C', texto: 'Concluídos pela equipe, com desfecho definido.', description: 'Atendimentos concluídos e despachados pela equipe (encerrado, comprometido, falha ou bloqueado) no período selecionado, incluindo os acompanhamentos de Outras situações.', matches: (lead: AtendimentoResumo) => lead.categoria_status === 'despachado' },
  ];
  const saidasFluxo = [
    { title: 'Desqualificados', count: desqualificados, cor: '#8C7B69', description: 'Leads classificados como desqualificados ou desconfiados.', matches: (lead: AtendimentoResumo) => lead.categoria_status === 'desqualificado', desqualificacao: true },
    { title: 'Outras situações', count: resumo.status.especial, cor: '#7C3AED', description: 'Acompanhamentos em aberto: clientes que já têm processo e querem acompanhá-lo (não são leads novos). Depois de despachados, passam a contar em Despachos.', matches: (lead: AtendimentoResumo) => lead.categoria_status === 'especial', desqualificacao: false },
  ];
  const ordenados = ranquear(STATUS_DONUT.map((st) => ({ ...st, cor: st.color, value: resumo.status[st.key] })));
  const segmentos = ordenados.filter((st) => st.value > 0);
  const temperaturas = ranquear(TEMPERATURAS.map((t) => ({ nome: t, cor: COR_TEMPERATURA[t], value: resumo.por_temperatura[t] ?? 0 })));
  const totalTemperaturas = temperaturas.reduce((t, x) => t + x.value, 0);
  const descricaoBarra = `Distribuição dos ${total} atendimentos: ${segmentos.map((st) => `${st.value} ${st.label.toLowerCase()}`).join(', ')}`;
  const pctNum = (n: number) => (total ? `${Math.round((n / total) * 100)}%` : '0%');
  const maxArea = Math.max(1, ...byArea.map(([, v]) => v));
  const bloqueado = busy || !!erroPeriodo;

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

  const chevron = (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );

  return (
    <>
      <header className="dash-head">
        <div className="dash-head-top">
          <div>
            <small className="eyebrow">{role === 'empresa' ? 'Visão consolidada' : 'Visão geral'}</small>
            <h1>{role === 'empresa' ? 'Dashboard da empresa' : 'Dashboard de atendimentos'}</h1>
            <p>{role === 'empresa' ? 'Volume, status e desempenho de toda a equipe.' : 'Volume e status de qualificação da sua empresa.'}</p>
          </div>
          <div className="segmentado" role="group" aria-label="Período">
            {([['30', 'Últimos 30 dias'], ['all', 'Todo o período'], ['custom', 'Período específico']] as const).map(([valor, rotulo]) => (
              <button key={valor} type="button" aria-pressed={periodo === valor} onClick={() => setPeriodo(valor)}>
                {rotulo}
              </button>
            ))}
          </div>
        </div>
        <div className="dash-filtros">
          <label className="search-field">
            <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="7" cy="7" r="5" stroke="#6E5F4F" strokeWidth="1.5" />
              <path d="M11 11l3.5 3.5" stroke="#6E5F4F" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <input placeholder="Buscar lead, contato ou responsável" aria-label="Buscar atendimentos" value={search} onChange={(e) => setSearch(e.target.value)} />
          </label>
          <label className="select-field">
            <select aria-label="Área" value={area} onChange={(e) => setArea(e.target.value)}>
              <option value="">Todas as áreas</option>
              {areas.map((a) => (
                <option key={a.id} value={a.name}>
                  {a.name}
                </option>
              ))}
            </select>
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M4 6l4 4 4-4" stroke="#6E5F4F" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
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
            className="dash-link"
            onClick={() => {
              setSearch('');
              setArea('');
              setPeriodo('30');
              const hoje = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Fortaleza' });
              setDataInicio(hoje);
              setDataFim(hoje);
            }}
          >
            Limpar filtros
          </button>
        </div>
        {erroPeriodo && <p role="alert" className="error" style={{ margin: 0 }}>{erroPeriodo}</p>}
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {buscaAtiva ? (
        <section className="dash-card dash-card-tabela" aria-labelledby="dash-busca-t">
          <div className="dash-card-topo">
            <div className="dash-card-cab">
              <div>
                <h2 id="dash-busca-t">
                  {buscando ? 'Buscando…' : `${resultados.length} lead${resultados.length === 1 ? ' encontrado' : 's encontrados'} para “${termo}”`}
                </h2>
                <small>Nome, telefone ou responsável, em todo o histórico. Clique em Detalhar para abrir os dados do lead.</small>
              </div>
              <button type="button" className="dash-botao-claro" onClick={() => setSearch('')}>
                Voltar ao dashboard
              </button>
            </div>
          </div>
          {!buscando && !resultados.length ? (
            <div className="empty">Nenhum lead encontrado para esta busca.</div>
          ) : (
            <ul className="dash-resultados">
              {resultados.map((r) => {
                const tv = TEMPERATURA_VISUAL[r.temperature];
                const etapa = ETAPA_VISUAL[r.categoria_status];
                return (
                  <li key={r.id}>
                    <div className="dash-resultado-id">
                      <span className="kb-dot" style={{ background: tv?.ponto ?? '#B9A893' }} aria-hidden="true" />
                      <div>
                        <strong>{r.name || 'Sem nome informado'}</strong>
                        <small>{r.contact}</small>
                      </div>
                    </div>
                    <span>{r.especialidade || '—'}</span>
                    <span className="dash-selo" style={{ background: etapa.fundo, color: etapa.cor }}>{etapa.rotulo}</span>
                    <span className="dash-resultado-resp">{r.owner || '—'}</span>
                    <button type="button" className="kb-detalhar" aria-haspopup="dialog" aria-label={`Detalhar ${r.name || r.contact}`} onClick={() => detalharResultado(r)}>
                      Detalhar
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      ) : (
        <>
      {busy && !carregou ? (
        <SkeletonTiles />
      ) : (
        <>
          <section className="dash-panorama" aria-labelledby="dash-panorama-t">
            <div className="dash-panorama-top">
              <div>
                <h2 id="dash-panorama-t">Atendimentos no período</h2>
                <div className="dash-total">
                  <strong><NumeroAnimado valor={total} /></strong>
                  {periodo !== 'custom' && resumo.novas_hoje > 0 && <span>{resumo.novas_hoje} novo{resumo.novas_hoje === 1 ? '' : 's'} hoje</span>}
                </div>
              </div>
              <button type="button" className="dash-botao-claro" aria-haspopup="dialog" disabled={bloqueado} onClick={() => abrirPopup('Total de atendimentos', 'Todos os atendimentos do período selecionado.', () => true)}>
                Ver todos
                {chevron}
              </button>
            </div>
            {total > 0 && (
              <div className="dash-barra" role="img" aria-label={descricaoBarra}>
                {segmentos.map((st) => (
                  <span key={st.key} style={{ flexGrow: st.value, background: st.cor }} title={`${st.label}: ${st.value} (${pctNum(st.value)})`} />
                ))}
              </div>
            )}
            <ul className="dash-legenda">
              {ordenados.map((st) => (
                <li key={st.key}>
                  <span className="dash-quadrado" style={{ background: st.cor }} aria-hidden="true" />
                  {st.label}
                  <strong><NumeroAnimado valor={st.value} /></strong>
                  <span className="dash-legenda-pct">{pctNum(st.value)}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="section" aria-labelledby="dash-fluxo-t">
            <div className="section-head">
              <h2 id="dash-fluxo-t">Fluxo do atendimento</h2>
              <span className="dash-nota">Clique em uma etapa para ver a lista</span>
            </div>
            <div className="dash-etapas">
              {etapasFluxo.map((e) => (
                <button key={e.title} type="button" className="dash-etapa" aria-haspopup="dialog" disabled={bloqueado} onClick={() => abrirPopup(e.title, e.description, e.matches)}>
                  <span className="dash-etapa-titulo">
                    <span className="dash-passo">{e.passo}</span>
                    {e.title}
                  </span>
                  <span className="dash-etapa-valor">
                    <strong style={{ color: e.cor }}><NumeroAnimado valor={e.count} /></strong>
                    <span>{pctNum(e.count)}</span>
                  </span>
                  <span className="dash-etapa-texto">{e.texto}</span>
                  <span className="dash-etapa-seta">{chevron}</span>
                </button>
              ))}
            </div>
            <div className="dash-saidas">
              <span className="dash-saidas-rotulo">Saíram do fluxo</span>
              {saidasFluxo.map((sd) => (
                <button key={sd.title} type="button" className="dash-saida" aria-haspopup="dialog" disabled={bloqueado} onClick={() => abrirPopup(sd.title, sd.description, sd.matches, sd.desqualificacao)}>
                  <span className="dash-quadrado" style={{ background: sd.cor }} aria-hidden="true" />
                  {sd.title}
                  <strong>{sd.count === null ? '—' : <NumeroAnimado valor={sd.count} />}</strong>
                </button>
              ))}
              <span className="dash-saida dash-saida-fixa" title="Triagens abandonadas que o sistema apagou automaticamente (sem resposta).">
                <span className="dash-quadrado" style={{ background: '#D8CBBB' }} aria-hidden="true" />
                Não prosseguiram
                <strong>{resumo.nao_prosseguiram ?? '—'}</strong>
                <small>{resumo.nao_prosseguiram === null ? 'indisponível com filtro de área/busca' : 'apagadas automaticamente'}</small>
              </span>
            </div>
            {desqualificados > 0 && (
              <p className="dash-nota" style={{ margin: 0 }}>
                Leads desqualificados/desconfiados são classificados diretamente pelo agente e nunca entram no Kanban de atendimento humano.
              </p>
            )}
          </section>
        </>
      )}

      {role === 'empresa' && (
        <section className="section" aria-labelledby="dash-kanban-t">
          <div className="section-head">
            <h2 id="dash-kanban-t">Kanban de atendimento</h2>
            <span className="dash-nota">Somente visualização — a empresa não assume nem contata leads.</span>
          </div>
          {!carregou ? (
            <SkeletonTiles />
          ) : (
            <div className="kb-container-dash">
            <div className="kb-board kb-board-compacto" ref={quadroRef}>
              {COLUMNS.map((col) => {
                const items = ordenarColuna(col.key, kanbanLeads.filter((l) => columnOf(l) === col.key));
                return (
                  <section key={col.key} className="kb-col" aria-label={col.label}>
                    <KanbanColunaHead coluna={col} total={items.length} />
                    <div className="kb-col-body">
                      {items.map((l) => (
                        <article key={l.id} data-flip-id={l.id} className="kb-card kb-card-estatico">
                          <button
                            type="button"
                            className="kb-fechar"
                            aria-label={`Fechar lead ${l.name || l.contact} (apaga e reinicia a triagem)`}
                            title="Fechar lead (apaga e reinicia a triagem)"
                            onClick={() => removerLead(l)}
                            disabled={excluindoId === l.id}
                          >
                            ×
                          </button>
                          <KanbanCardConteudo lead={l} coluna={col.key} compacto onDetalhar={setDetalhe} />
                        </article>
                      ))}
                      {!items.length && <div className="kb-vazio">Nenhum lead aqui</div>}
                    </div>
                  </section>
                );
              })}
            </div>
            </div>
          )}
        </section>
      )}

      <div className="dash-duas">
        <article className="dash-card" aria-labelledby="dash-area-t">
          <div>
            <h2 id="dash-area-t">Atendimentos por área</h2>
            <small>Especialidade classificada pelo agente</small>
          </div>
          <div className="dash-areas">
            {byArea.map(([name, count]) => (
              <div key={name} className="dash-area">
                <span>{name}</span>
                <span className="dash-trilho">
                  <span style={{ width: `${Math.round((count / maxArea) * 100)}%`, background: name === 'Sem área' ? '#B9A893' : 'var(--accent)' }} />
                </span>
                <span className="dash-area-valor">
                  <strong>{count}</strong> {pctNum(count)}
                </span>
              </div>
            ))}
            {!byArea.length && <p className="dash-nota">Sem dados para o período.</p>}
          </div>
          <p className="dash-nota" style={{ marginTop: 'auto' }}>Sem área: a triagem ainda não chegou à classificação.</p>
        </article>

        <article className="dash-card" aria-labelledby="dash-mes-t">
          <div>
            <h2 id="dash-mes-t">Tendência</h2>
            <small>Atendimentos por mês</small>
          </div>
          {monthly.length ? (
            <div className="dash-meses" role="img" aria-label={`Atendimentos por mês: ${monthly.map(([m, v]) => `${m} ${v}`).join(', ')}`}>
              {monthly.map(([label, value], i) => {
                const atual = i === monthly.length - 1;
                return (
                  <div key={label} className="dash-mes">
                    <span className={atual ? 'dash-mes-valor atual' : 'dash-mes-valor'}>{value}</span>
                    <span className={atual ? 'dash-mes-barra atual' : 'dash-mes-barra'} style={{ height: Math.max(6, Math.round((value / maxMonthly) * 150)) }} />
                    <small>{label}</small>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="dash-nota">Sem dados para o período.</p>
          )}
        </article>
      </div>

      <section className="dash-card" aria-labelledby="dash-temp-t">
        <div className="dash-card-cab">
          <div>
            <h2 id="dash-temp-t">Temperatura dos qualificados</h2>
            <small>Leads classificadas no período, da temperatura mais frequente para a menos frequente</small>
          </div>
          <div className="dash-total-pequeno">
            <strong><NumeroAnimado valor={totalTemperaturas} /></strong>
            <span>classificadas</span>
          </div>
        </div>
        {totalTemperaturas > 0 ? (
          <>
            <div className="dash-barra" role="img" aria-label={`Temperatura das leads classificadas: ${temperaturas.map((t) => `${t.value} ${t.nome.toLowerCase()}`).join(', ')}`}>
              {temperaturas.filter((t) => t.value > 0).map((t) => (
                <span key={t.nome} style={{ flexGrow: t.value, background: t.cor }} title={`${t.nome}: ${t.value}`} />
              ))}
            </div>
            <ul className="dash-temps">
              {temperaturas.map((t) => (
                <li key={t.nome}>
                  <span className="dash-passo">{t.posicao}º</span>
                  <span className="dash-quadrado" style={{ background: t.cor }} aria-hidden="true" />
                  <span style={{ flex: 1 }}>{t.nome}</span>
                  <strong><NumeroAnimado valor={t.value} /></strong>
                  <span className="dash-legenda-pct">{Math.round((t.value / totalTemperaturas) * 100)}%</span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="dash-nota">Nenhuma lead classificada no período selecionado.</p>
        )}
      </section>

      <section className="dash-card dash-card-tabela" aria-labelledby="dash-conc-t">
        <div className="dash-card-topo">
          <div className="dash-card-cab">
            <div>
              <h2 id="dash-conc-t">Concluído</h2>
              <small>
                {totalDespachados} lead{totalDespachados === 1 ? '' : 's'} despachado{totalDespachados === 1 ? '' : 's'} pela equipe
              </small>
            </div>
            {totalDespachados > 0 && (
              <div className="segmentado" role="group" aria-label="Filtrar concluídos">
                <button type="button" aria-pressed={filtroConcluidos === 'sucesso'} onClick={() => setFiltroConcluidos('sucesso')}>
                  Com sucesso · {resumo.sucesso}
                </button>
                <button type="button" aria-pressed={filtroConcluidos === 'todos'} onClick={() => setFiltroConcluidos('todos')}>
                  Todos · {resumo.concluidos.length}
                </button>
              </div>
            )}
          </div>
          <div className="dash-desfechos">
            {concluidosPorDesfecho.map((d) => (
              <button
                key={d.value}
                type="button"
                className="dash-desfecho"
                style={{ background: d.fundo, borderColor: d.borda, color: d.color }}
                disabled={bloqueado}
                aria-haspopup="dialog"
                onClick={() => abrirPopup(d.label, 'Atendimentos com este desfecho no período selecionado.', (lead) => lead.desfecho === d.value)}
              >
                <small>{d.label}</small>
                <strong><NumeroAnimado valor={d.count} /></strong>
              </button>
            ))}
          </div>
        </div>
        {totalDespachados > 0 ? (
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
                      <td>
                        {c.temperature ? (
                          <span className="dash-temp">
                            <span className="kb-dot" style={{ background: TEMPERATURA_VISUAL[c.temperature]?.ponto ?? '#B9A893' }} aria-hidden="true" />
                            {c.temperature}
                          </span>
                        ) : '—'}
                      </td>
                      <td>{c.priority || '—'}</td>
                      <td>{d ? <span className="dash-selo" style={{ background: d.fundo, color: d.color }}>{d.label}</span> : c.desfecho}</td>
                      <td>{c.owner || '—'}</td>
                      <td style={{ fontFamily: "'DM Mono',monospace", fontSize: 12.5 }}>{c.concluido_em ? new Date(c.concluido_em).toLocaleString('pt-BR') : '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {!listaConcluidos.length && <div className="empty">Nenhum atendimento concluído com sucesso no período selecionado.</div>}
          </div>
        ) : (
          !busy && <p className="dash-nota" style={{ padding: '0 26px 22px', margin: 0 }}>Nenhum atendimento despachado no período selecionado.</p>
        )}
      </section>

      {role === 'empresa' && (
        <section className="dash-card dash-card-tabela" aria-labelledby="dash-desemp-t">
          <div className="dash-card-topo">
            <div className="dash-card-cab">
              <h2 id="dash-desemp-t">Desempenho por atendente</h2>
              <label className="search-field dash-busca-atendente">
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <circle cx="7" cy="7" r="5" stroke="#6E5F4F" strokeWidth="1.5" />
                  <path d="M11 11l3.5 3.5" stroke="#6E5F4F" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
                <input placeholder="Buscar atendente" aria-label="Buscar atendente" value={buscaAtendente} onChange={(e) => setBuscaAtendente(e.target.value)} />
              </label>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Atendente</th>
                  <th style={{ textAlign: 'right' }}>Atendimentos</th>
                  <th style={{ textAlign: 'right' }}>Despachados</th>
                  <th style={{ textAlign: 'right' }}>Com sucesso</th>
                  <th style={{ width: 260 }}>Taxa de conclusão</th>
                </tr>
              </thead>
              <tbody>
                {byOwner.map((o) => {
                  const rate = o.atendimentos ? Math.round((o.concluidos / o.atendimentos) * 100) : 0;
                  const bom = rate >= 50;
                  return (
                    <tr key={o.owner_id}>
                      <td>
                        <span className="dash-pessoa">
                          <span className="kb-avatar" aria-hidden="true">{o.owner.trim().split(/\s+/).map((p) => p[0]).slice(0, 2).join('').toUpperCase()}</span>
                          <strong>{o.owner}</strong>
                        </span>
                      </td>
                      <td className="dash-num">{o.atendimentos}</td>
                      <td className="dash-num">{o.concluidos}</td>
                      <td className="dash-num">{o.sucesso}</td>
                      <td>
                        <span className="dash-taxa">
                          <span className="dash-trilho">
                            <span style={{ width: `${rate}%`, background: bom ? 'var(--success)' : '#C88A1E' }} />
                          </span>
                          <strong style={{ color: bom ? '#245F46' : '#7A4F0E' }}>{rate}%</strong>
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {!byOwner.length && <div className="empty">{busy ? 'Carregando…' : 'Sem dados de equipe para o período.'}</div>}
          </div>
        </section>
      )}
        </>
      )}
      {popup && <DashboardAtendimentosDialog {...popup} historico={company.coletar_historico_conversa ? { api, companyId: company.id } : undefined} onClose={() => setPopup(null)} />}
      {detalhe && <LeadDetalheDialog lead={detalhe} estagio={detalhe.desfecho ? 'Despachado' : (COLUMNS.find((c) => c.key === columnOf(detalhe))?.label ?? '')} historico={company.coletar_historico_conversa ? { api, companyId: company.id } : undefined} onClose={() => setDetalhe(null)} />}
    </>
  );
}
