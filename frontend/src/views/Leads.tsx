import { HistoricoConversaDialog } from '../components/HistoricoConversaDialog';
import { useEffect, useState } from 'react';
import { fetchTodasAsPaginas, type Api } from '../api';
import type { Company, Lead, LeadEvent, Me } from '../types';
import { SkeletonCards, Spinner } from '../components/Skeleton';
import { AreaSelect } from '../components/AreaSelect';
import { ConfirmPessoa, useConfirmar } from '../components/ConfirmDialog';
import { IconeWhatsapp } from '../components/Icones';
import { CadastroAtendimentoDialog, Overlay, TriagemResumo } from '../components/CadastroAtendimento';
import { KanbanCardConteudo, KanbanColunaHead, TEMPERATURA_VISUAL } from '../components/KanbanVisual';

// Mesma ordem de services.FAIXAS_URGENCIA no backend (menos urgente -> mais urgente).
export const URGENCIA_RANK: Record<string, number> = { Desqualificado: 0, Desconfiado: 1, Frio: 2, Qualificado: 3, Quente: 4 };
export const URGENCIA_COR: Record<string, string> = { Frio: '#2563EB', Qualificado: '#D4A72C', Quente: '#E2574C' };
export const FORA_DO_KANBAN = new Set(['Desqualificado', 'Desconfiado']);

const DESFECHO_OPTIONS: { value: 'encerrado' | 'comprometido' | 'falha'; label: string; color: string; help: string }[] = [
  { value: 'encerrado', label: 'Encerrado', color: 'var(--success)', help: 'Sucesso de comunicação — o cliente conseguiu realizar o que desejava.' },
  { value: 'comprometido', label: 'Comprometido', color: 'var(--warn)', help: 'Algo não saiu conforme o planejado; o cliente pode voltar ou não dar continuidade.' },
  { value: 'falha', label: 'Falha durante o atendimento', color: 'var(--danger)', help: 'O cliente desistiu ou cessou o contato durante o atendimento humano.' },
];

export type ColumnKey = 'novos' | 'qualificados' | 'espera' | 'negociacao' | 'despacho';

export const COLUMNS: { key: ColumnKey; label: string; cor: string; regra: string }[] = [
  { key: 'novos', label: 'Novos Leads', cor: '#2563EB', regra: 'Triagem do agente em andamento' },
  { key: 'qualificados', label: 'Qualificados', cor: '#C88A1E', regra: 'Maior urgência primeiro' },
  { key: 'espera', label: 'Atendimentos em espera', cor: '#C88A1E', regra: 'Maior urgência primeiro' },
  { key: 'negociacao', label: 'Em negociação', cor: '#D9531A', regra: 'Ordem de chegada' },
  { key: 'despacho', label: 'Despacho', cor: '#2F7D5C', regra: 'Aguardando “Enviar Despachos”' },
];

export function columnOf(l: Lead): ColumnKey {
  // Escalado pra humano no meio da triagem (pedido humano, falha de entrega...) já vai
  // pra Qualificados -- senão ficava preso em "Novos" sem ninguém poder assumir.
  if (!l.bot_closed && l.mode !== 'HUMANO') return 'novos';
  if (l.etapa_atendimento === 'espera') return 'espera';
  if (l.etapa_atendimento === 'negociacao') return 'negociacao';
  if (l.etapa_atendimento === 'despacho') return 'despacho';
  return 'qualificados';
}

/** Leads visíveis no Kanban: desfecho já definitivo, cadastro manual e Desqualificado/Desconfiado nunca aparecem aqui. */
export function leadsVisiveisNoKanban(leads: Lead[]): Lead[] {
  return leads.filter((l) => !l.desfecho && !l.origem_manual && !FORA_DO_KANBAN.has(l.temperature));
}

export function ordenarColuna(key: ColumnKey, items: Lead[]): Lead[] {
  const chegada = (a: Lead, b: Lead) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
  if (key === 'negociacao') {
    // Ordem de chegada: mais antigo primeiro, recém-chegado aparece por último.
    return [...items].sort(chegada);
  }
  if (key === 'qualificados' || key === 'espera' || key === 'despacho') {
    // Maior urgência primeiro; empate segue a ordem de chegada.
    return [...items].sort((a, b) => (b.urgencia_rank ?? URGENCIA_RANK[b.temperature] ?? -1)
      - (a.urgencia_rank ?? URGENCIA_RANK[a.temperature] ?? -1) || chegada(a, b));
  }
  return items;
}

/** Como o CRM chegou à temperatura: nota do agente × peso da variável de cada pergunta. */
function UrgenciaDetalhe({ lead }: { lead: Lead }) {
  const d = lead.urgencia_detalhe;
  if (!d || d.score === undefined || !d.notas) return null;
  const linhas = Object.entries(d.notas);
  return (
    <div style={{ marginBottom: 16 }}>
      <h3 style={{ margin: '0 0 8px' }}>Cálculo de urgência</h3>
      <p style={{ fontSize: 13, color: 'var(--muted)', margin: '0 0 8px' }}>
        Score <strong style={{ color: 'var(--ink)' }}>{d.score.toFixed(2)}</strong> de 10 → {d.temperatura_calculada} · Prioridade {lead.priority}
      </p>
      <table style={{ width: '100%', fontSize: 13 }}>
        <thead>
          <tr>
            <th style={{ textAlign: 'left' }}>Variável</th>
            <th style={{ textAlign: 'right' }}>Peso</th>
            <th style={{ textAlign: 'right' }}>Nota</th>
          </tr>
        </thead>
        <tbody>
          {linhas.map(([qid, nota]) => (
            <tr key={qid}>
              <td title={qid}>{d.nomes?.[qid] || (qid === '_detalhamento' ? 'Detalhamento' : qid)}</td>
              <td style={{ textAlign: 'right' }}>{d.pesos?.[qid] ?? '—'}</td>
              <td style={{ textAlign: 'right' }}>{nota}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Leads({ api, company, role, me }: { api: Api; company: Company; role: 'atendente' | 'empresa' | 'admin'; me: Me }) {
  const confirmar = useConfirmar();
  const historicoDe = company.coletar_historico_conversa ? { api, companyId: company.id } : undefined;
  const [leads, setLeads] = useState<Lead[]>([]);
  const [search, setSearch] = useState('');
  const [mostrarNovasLeads, setMostrarNovasLeads] = useState(true);
  const [selected, setSelected] = useState<Lead | null>(null);
  const [events, setEvents] = useState<LeadEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [error, setError] = useState('');
  const [dragId, setDragId] = useState<string | null>(null);
  const [negociacaoModal, setNegociacaoModal] = useState<Lead | null>(null);
  const [cadastroSemAtendimentoModal, setCadastroSemAtendimentoModal] = useState<Lead | null>(null);
  const [despachoClassificarModal, setDespachoClassificarModal] = useState<Lead | null>(null);
  const [enviandoDespachos, setEnviandoDespachos] = useState(false);
  // Área escolhida no Despacho ('' = manter a atual do lead).
  const [areaDespacho, setAreaDespacho] = useState('');
  const [desqualificadosCount, setDesqualificadosCount] = useState(0);
  const [historicoAberto, setHistoricoAberto] = useState(false);

  const podeAtender = role === 'atendente';

  function load(silent = false) {
    if (!silent) setBusy(true);
    if (!silent) setError('');
    // Só os ativos, todas as páginas: concluídos nunca são apagados e, sem o filtro,
    // empurravam os ativos mais antigos pra fora da 1ª página.
    // Desqualificados/desconfiados ficam fora do filtro de ativos -- a contagem vem do resumo.
    if (!silent) {
      api(`/leads/resumo/?company=${company.id}&dias=all`)
        .then((r: { desqualificados: number }) => setDesqualificadosCount(r.desqualificados))
        .catch(() => {});
    }
    fetchTodasAsPaginas<Lead>(api, `/leads/?company=${company.id}&ativos=1`)
      .then((todos) => {
        setLeads(todos);
        setSelected((s) => (s ? todos.find((l) => l.id === s.id) || s : s));
      })
      .catch((e) => {
        if (!silent) setError(e.message);
      })
      .finally(() => {
        if (!silent) setBusy(false);
      });
  }

  useEffect(() => {
    setHistoricoAberto(false);
  }, [selected?.id]);

  useEffect(() => {
    load();
    setSelected(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [company.id]);

  // Central de leads precisa pegar leads novos (criados pelo agente via WhatsApp)
  // sem precisar recarregar a página -- silencioso (sem spinner/erro visível) pra
  // não interromper quem está arrastando um card ou com um modal aberto.
  useEffect(() => {
    const id = setInterval(() => load(true), 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  function aplicarAtualizacao(updated: Lead) {
    setLeads((v) => v.map((l) => (l.id === updated.id ? updated : l)));
    setSelected((s) => (s && s.id === updated.id ? updated : s));
    setNegociacaoModal((s) => (s?.id === updated.id ? updated : s));
    setCadastroSemAtendimentoModal((s) => (s?.id === updated.id ? updated : s));
  }

  async function chamarAcao(path: string, lead: Lead, body?: Record<string, unknown>) {
    setActionBusy(true);
    setError('');
    try {
      const updated = await api(`/leads/${lead.id}/${path}/?company=${company.id}`, { method: 'POST', body: body ? JSON.stringify(body) : undefined });
      aplicarAtualizacao(updated);
      return updated as Lead;
    } catch (err) {
      setError((err as Error).message);
      return null;
    } finally {
      setActionBusy(false);
    }
  }

  async function reivindicar(lead: Lead) {
    await chamarAcao('reivindicar', lead);
  }

  async function acompanhar(lead: Lead) {
    await chamarAcao('acompanhar', lead);
  }

  async function confirmarNegociacao(lead: Lead) {
    const updated = await chamarAcao('negociar', lead);
    if (updated) setNegociacaoModal(null);
  }

  async function confirmarCadastroSemAtendimento(lead: Lead) {
    const updated = await chamarAcao('preparar-despacho', lead, { auto_falha: true, especialidade: areaDespacho || undefined });
    if (updated) setCadastroSemAtendimentoModal(null);
  }

  async function confirmarDespacho(lead: Lead, desfecho: 'encerrado' | 'comprometido' | 'falha') {
    const updated = await chamarAcao('preparar-despacho', lead, { desfecho, especialidade: areaDespacho || undefined });
    if (updated) setDespachoClassificarModal(null);
  }

  async function liberar(lead: Lead) {
    if (!(await confirmar({ titulo: 'Soltar este atendimento?', mensagem: 'Ele volta para Qualificados e qualquer atendente poderá reivindicá-lo.', detalhe: <ConfirmPessoa nome={lead.name || 'Sem nome informado'} sub={lead.contact} />, tom: 'atencao', icone: 'pessoa', confirmar: 'Soltar atendimento' }))) return;
    await chamarAcao('liberar', lead);
  }

  async function enviarDespachos() {
    setEnviandoDespachos(true);
    setError('');
    try {
      await api(`/leads/enviar-despachos/?company=${company.id}`, { method: 'POST' });
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setEnviandoDespachos(false);
    }
  }


  const visible = leadsVisiveisNoKanban(leads).filter((l) => `${l.name} ${l.contact}`.toLowerCase().includes(search.toLowerCase()));
  const visibleColumns = COLUMNS.filter((col) => mostrarNovasLeads || col.key !== 'novos');

  function orderedItems(key: ColumnKey) {
    return ordenarColuna(key, visible.filter((l) => columnOf(l) === key));
  }

  function podeArrastar(l: Lead): boolean {
    if (!podeAtender) return false;
    const col = columnOf(l);
    if (col === 'novos') return false;
    if (col === 'qualificados' || col === 'espera') return true;
    return l.owner === me.id;
  }

  // Card em negociação/despacho por outro atendente:
  // fica cinza, não clicável e não arrastável -- só o owner mexe nele.
  function ehDeOutroOwner(l: Lead): boolean {
    const col = columnOf(l);
    return (col === 'negociacao' || col === 'despacho') && l.owner !== null && l.owner !== me.id;
  }

  function onDropEm(target: ColumnKey, lead: Lead | null) {
    setDragId(null);
    if (!lead) return;
    const source = columnOf(lead);
    if (source === target) return;
    if (!podeArrastar(lead)) {
      setError('Você não pode mover este atendimento.');
      return;
    }
    setError('');
    if (target === 'novos') {
      setError('Não é possível mover um card para "Novos Leads".');
      return;
    }
    if (target === 'espera') {
      if (source !== 'qualificados') {
        setError('Só é possível mover para "Atendimentos em espera" a partir de Qualificados.');
        return;
      }
      reivindicar(lead);
      return;
    }
    if (target === 'negociacao') {
      if (source !== 'qualificados' && source !== 'espera') {
        setError('Só é possível mover para "Em negociação" a partir de Qualificados ou Atendimentos em espera.');
        return;
      }
      setNegociacaoModal(lead);
      return;
    }
    if (target === 'despacho') {
      setAreaDespacho(lead.especialidade || '');
      if (source === 'qualificados') {
        setCadastroSemAtendimentoModal(lead);
        return;
      }
      if (source === 'espera' || source === 'negociacao') {
        setDespachoClassificarModal(lead);
        return;
      }
      setError('Transição inválida para Despacho.');
      return;
    }
    if (target === 'qualificados') {
      if (source === 'novos') {
        setError('Não é possível devolver um lead ainda em triagem.');
        return;
      }
      liberar(lead);
    }
  }

  const minhasNoDespacho = leads.filter((l) => columnOf(l) === 'despacho' && l.owner === me.id && !l.desfecho);

  return (
    <>
      <header className="page-header">
        <div>
          <small className="eyebrow">Fluxo de atendimento</small>
          <h1>Central de leads</h1>
          <p>{podeAtender ? 'Arraste o card para a próxima etapa. Leads de outro atendente ficam travados.' : 'Acompanhe a qualificação de cada contato, etapa por etapa.'}</p>
        </div>
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <div className="kb-controles">
          <label className="kb-toggle">
            <input type="checkbox" checked={mostrarNovasLeads} onChange={(e) => setMostrarNovasLeads(e.target.checked)} />
            Mostrar novas leads
          </label>
          <label className="search-field kb-busca">
            <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="7" cy="7" r="5" stroke="#6E5F4F" strokeWidth="1.5" />
              <path d="M11 11l3.5 3.5" stroke="#6E5F4F" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <input placeholder="Buscar nome ou telefone" aria-label="Buscar leads" value={search} onChange={(e) => setSearch(e.target.value)} />
          </label>
        </div>

      <ol className="kb-trilha" aria-label="Etapas do fluxo">
        {visibleColumns.map((col, i) => (
          <li key={col.key}>
            <span className="kb-trilha-etapa">
              <span className="kb-dot" style={{ background: col.cor }} aria-hidden="true" />
              {col.label}
              <strong>{orderedItems(col.key).length}</strong>
            </span>
            {i < visibleColumns.length - 1 && (
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path d="M6 4l4 4-4 4" stroke="#A8957F" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
          </li>
        ))}
        <li className="kb-legenda" aria-label="Temperatura">
          {Object.entries(TEMPERATURA_VISUAL).map(([nome, v]) => (
            <span key={nome}>
              <span className="kb-dot" style={{ background: v.ponto }} aria-hidden="true" />
              {nome}
            </span>
          ))}
        </li>
      </ol>

      {busy && !visible.length ? (
        <SkeletonCards count={visibleColumns.length} height={90} />
      ) : (
        <div className="kb-board">
          {visibleColumns.map((col) => {
            const items = orderedItems(col.key);
            return (
              <section
                key={col.key}
                className={`kb-col${dragId ? ' kb-col-alvo' : ''}`}
                aria-label={col.label}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  // Lê o id direto do dataTransfer (sessão nativa de drag), não do state
                  // dragId por closure -- mais robusto contra timing entre o React re-renderizar
                  // e o navegador disparar o evento.
                  const sourceId = e.dataTransfer.getData('text/plain');
                  const lead = leads.find((l) => l.id === sourceId) || null;
                  onDropEm(col.key, lead);
                }}
              >
                <KanbanColunaHead coluna={col} total={items.length} />
                <div className="kb-col-body">
                  {items.map((l) => {
                    const bloqueado = ehDeOutroOwner(l);
                    return (
                      <article
                        key={l.id}
                        className={`kb-card${selected?.id === l.id ? ' selected' : ''}${bloqueado ? ' kb-card-bloqueado' : ''}${dragId === l.id ? ' kb-card-arrastando' : ''}`}
                        draggable={podeArrastar(l)}
                        onDragStart={(e) => {
                          e.dataTransfer.effectAllowed = 'move';
                          e.dataTransfer.setData('text/plain', l.id);
                          setDragId(l.id);
                        }}
                        onDragEnd={() => setDragId(null)}
                        onClick={() => !bloqueado && setSelected(l)}
                        tabIndex={bloqueado ? -1 : 0}
                        role="button"
                        aria-disabled={bloqueado}
                        aria-label={bloqueado ? `${l.name || l.contact} — em atendimento com ${l.owner_nome}` : `Ver detalhes de ${l.name || l.contact}`}
                        onKeyDown={(e) => {
                          if (!bloqueado && (e.key === 'Enter' || e.key === ' ')) {
                            e.preventDefault();
                            setSelected(l);
                          }
                        }}
                        style={{ cursor: bloqueado ? 'not-allowed' : podeArrastar(l) ? 'grab' : undefined }}
                      >
                        <KanbanCardConteudo lead={l} coluna={col.key} meId={me.id} />
                      </article>
                    );
                  })}
                  {!items.length && <div className="kb-vazio">{podeAtender && col.key !== 'novos' ? 'Arraste um card para cá' : 'Nenhum lead aqui'}</div>}
                </div>
                {col.key === 'despacho' && minhasNoDespacho.length > 0 && (
                  <button type="button" className="kb-enviar" onClick={enviarDespachos} disabled={enviandoDespachos}>
                    {enviandoDespachos ? (
                      <Spinner />
                    ) : (
                      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                        <path d="M2.5 8.5l3.5 3.5 7.5-8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    )}
                    Enviar Despachos ({minhasNoDespacho.length})
                  </button>
                )}
              </section>
            );
          })}
        </div>
      )}
      {!busy && !visible.length && <div className="empty">Nenhum lead nesta visão. Os contatos aparecerão ao receber mensagens pela integração.</div>}
      {desqualificadosCount > 0 && (
        <p className="table-note" style={{ padding: 0 }}>
          {desqualificadosCount} lead{desqualificadosCount === 1 ? '' : 's'} desqualificado{desqualificadosCount === 1 ? '' : 's'}/desconfiado{desqualificadosCount === 1 ? '' : 's'} fora do fluxo — veja no Dashboard.
        </p>
      )}

      {selected && (
        <section className="panel detail">
          <div className="detail-head">
            <h2>{selected.name || selected.contact}</h2>
            <button className="secondary" onClick={() => setSelected(null)}>
              Fechar
            </button>
          </div>
          <p style={{ marginBottom: 16 }}>
            Etapa: <strong style={{ color: 'var(--ink)' }}>{selected.state}</strong> · Bot {selected.bot_closed ? 'encerrado' : selected.mode === 'HUMANO' ? 'pausado para atendimento humano' : 'ativo'}
            {selected.temperature && (
              <>
                {' '}
                · Temperatura: <strong style={{ color: 'var(--ink)' }}>{selected.temperature}</strong>
              </>
            )}
            {selected.owner && (
              <>
                {' '}
                · Responsável: <strong style={{ color: 'var(--ink)' }}>{selected.owner_nome}</strong>
              </>
            )}
          </p>

          {selected.contact && (
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 20 }}>
              <a href={`https://wa.me/${selected.contact.replace(/\D/g, '')}`} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                <button type="button" style={{ background: '#25D366', borderColor: '#25D366', display: 'inline-flex', alignItems: 'center', gap: 8 }}>
<IconeWhatsapp size={22} />
                  Conversar
                </button>
              </a>
              {company.coletar_historico_conversa && (
                <button type="button" className="secondary" onClick={() => setHistoricoAberto(true)}>
                  Histórico de conversa
                </button>
              )}
              {podeAtender && columnOf(selected) === 'novos' && (
                <button
                  type="button" onClick={() => acompanhar(selected)} disabled={actionBusy}
                  title="Assumir o atendimento e interromper a triagem automática"
                >
                  {actionBusy && <Spinner />}
                  Acompanhar lead
                </button>
              )}
            </div>
          )}

          <TriagemResumo lead={selected} api={api} onUpdated={aplicarAtualizacao} />
          <UrgenciaDetalhe lead={selected} />
          <p style={{ fontSize: 12.5, color: 'var(--muted)', marginBottom: 20 }}>
            O nome pode ser corrigido aqui. Os demais dados vêm do agente durante a triagem.
            Arraste o card para colocar em espera, iniciar a negociação ou despachar.
          </p>

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
          {historicoAberto && <HistoricoConversaDialog api={api} companyId={company.id} lead={selected} onClose={() => setHistoricoAberto(false)} />}
        </section>
      )}

      {negociacaoModal && (
        <CadastroAtendimentoDialog
          lead={negociacaoModal}
          api={api}
          historico={historicoDe}
          busy={actionBusy}
          onUpdated={aplicarAtualizacao}
          onConfirm={confirmarNegociacao}
          onClose={() => setNegociacaoModal(null)}
        />
      )}

      {cadastroSemAtendimentoModal && (
        <Overlay onClose={() => setCadastroSemAtendimentoModal(null)}>
          <h2 style={{ marginTop: 0 }}>Cadastrar sem atendimento</h2>
          <p style={{ color: 'var(--muted)', marginBottom: 16 }}>Dados coletados pelo agente durante a triagem.</p>
          <TriagemResumo lead={cadastroSemAtendimentoModal} api={api} onUpdated={aplicarAtualizacao} historico={historicoDe} />
          <p style={{ fontSize: 13, color: 'var(--danger)', marginBottom: 16 }}>
            Este lead será marcado automaticamente como <strong>Falha durante o atendimento</strong> — ele vai para a coluna
            Despacho, pendente do botão "Enviar Despachos".
          </p>
          <div style={{ marginBottom: 16 }}>
            <AreaSelect api={api} companyId={company.id} value={areaDespacho} onChange={setAreaDespacho} />
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button type="button" className="danger-outline" onClick={() => confirmarCadastroSemAtendimento(cadastroSemAtendimentoModal)} disabled={actionBusy}>
              {actionBusy && <Spinner />}
              Confirmar
            </button>
            <button type="button" className="secondary" onClick={() => setCadastroSemAtendimentoModal(null)}>
              Cancelar
            </button>
          </div>
        </Overlay>
      )}

      {despachoClassificarModal && (
        <Overlay onClose={() => setDespachoClassificarModal(null)}>
          <h2 style={{ marginTop: 0 }}>Classificar desfecho</h2>
          <p style={{ color: 'var(--muted)', marginBottom: 16 }}>
            Fica reservado na coluna Despacho — só é enviado como Concluído quando você clicar em "Enviar Despachos".
          </p>
          <div style={{ marginBottom: 16 }}>
            <AreaSelect api={api} companyId={company.id} value={areaDespacho} onChange={setAreaDespacho} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {DESFECHO_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className="desfecho-option"
                onClick={() => confirmarDespacho(despachoClassificarModal, opt.value)}
                disabled={actionBusy}
                style={{ '--cor': opt.color } as React.CSSProperties}
              >
                <strong style={{ display: 'block' }}>{opt.label}</strong>
                <small style={{ color: 'var(--muted)', fontWeight: 400 }}>{opt.help}</small>
              </button>
            ))}
            <button type="button" className="secondary" onClick={() => setDespachoClassificarModal(null)}>
              Cancelar
            </button>
          </div>
        </Overlay>
      )}
    </>
  );
}
