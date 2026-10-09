import { ObservacoesLead } from '../components/LeadDetalheDialog';
import { HistoricoConversaDialog } from '../components/HistoricoConversaDialog';
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { fetchTodasAsPaginas, type Api } from '../api';
import type { Company, Lead, LeadEvent, Me } from '../types';
import { SkeletonCards, Spinner } from '../components/Skeleton';
import { AreaSelect } from '../components/AreaSelect';
import { LeadNameField } from '../components/LeadNameField';

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

export const COLUMNS: { key: ColumnKey; label: string }[] = [
  { key: 'novos', label: 'Novos Leads' },
  { key: 'qualificados', label: 'Qualificados' },
  { key: 'espera', label: 'Atendimentos em espera' },
  { key: 'negociacao', label: 'Em negociação' },
  { key: 'despacho', label: 'Despacho' },
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

function Overlay({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  return createPortal(
    <div
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      style={{ position: 'fixed', inset: 0, background: 'rgba(20,14,9,0.6)', backdropFilter: 'blur(2px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: 20 }}
    >
      <div className="panel" style={{ position: 'relative', width: 520, maxWidth: '100%', padding: 24, borderRadius: 16, boxShadow: '0 32px 70px rgba(0,0,0,0.4)' }}>
        {children}
      </div>
    </div>,
    document.body,
  );
}

function TriagemResumo({ lead, api, onUpdated }: { lead: Lead; api?: Api; onUpdated?: (lead: Lead) => void }) {
  return (
    <div className="fields" style={{ marginBottom: 16 }}>
      {api && onUpdated ? <LeadNameField key={lead.id} lead={lead} api={api} onUpdated={onUpdated} /> : <label style={{ margin: 0 }}>
        Nome
        <input readOnly value={lead.name || 'Sem nome informado'} />
      </label>}
      <label style={{ margin: 0 }}>
        Contato
        <input readOnly value={lead.contact} />
      </label>
      <label style={{ margin: 0 }}>
        Área
        <input readOnly value={lead.especialidade || '—'} />
      </label>
      <label style={{ margin: 0 }}>
        Temperatura
        <input readOnly value={lead.temperature || '—'} />
      </label>
      <label style={{ margin: 0, gridColumn: '1 / -1' }}>
        Demanda
        <input readOnly value={lead.demand || '—'} />
      </label>
      {lead.notes && (
        <div style={{ gridColumn: '1 / -1', fontSize: 14 }}>
          <small style={{ display: 'block', color: 'var(--muted)', marginBottom: 2 }}>Observações</small>
          <ObservacoesLead notes={lead.notes} />
        </div>
      )}
    </div>
  );
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
            <th style={{ textAlign: 'left' }}>Pergunta</th>
            <th style={{ textAlign: 'right' }}>Peso</th>
            <th style={{ textAlign: 'right' }}>Nota</th>
          </tr>
        </thead>
        <tbody>
          {linhas.map(([qid, nota]) => (
            <tr key={qid}>
              <td style={{ fontFamily: "'DM Mono',monospace" }}>{qid}</td>
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
    if (!window.confirm('Soltar este atendimento? Ele volta para Qualificados e qualquer atendente poderá reivindicá-lo.')) return;
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
          <div className="leads-toolbar-controls">
            <label className="leads-visibility-toggle">
              <input type="checkbox" checked={mostrarNovasLeads} onChange={(e) => setMostrarNovasLeads(e.target.checked)} />
              Mostrar novas leads
            </label>
            <input placeholder="Buscar nome ou telefone" aria-label="Buscar leads" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
        </div>
        {busy && !visible.length ? (
          <div style={{ padding: '18px 24px' }}>
            <SkeletonCards count={visibleColumns.length} height={90} />
          </div>
        ) : (
          <div className="kanban">
            {visibleColumns.map((col) => {
              const items = orderedItems(col.key);
              return (
                <div
                  key={col.key}
                  className="kanban-col"
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
                  <div className="kanban-col-head">
                    <h3>{col.label}</h3>
                    <small>
                      {items.length} lead{items.length === 1 ? '' : 's'}
                    </small>
                  </div>
                  <div className="kanban-col-body">
                    {items.map((l) => {
                      const bloqueado = ehDeOutroOwner(l);
                      return (
                      <article
                        key={l.id}
                        className={`kanban-card${selected?.id === l.id ? ' selected' : ''}`}
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
                        style={{
                          opacity: dragId === l.id ? 0.5 : bloqueado ? 0.45 : 1,
                          cursor: bloqueado ? 'not-allowed' : podeArrastar(l) ? 'grab' : undefined,
                          filter: bloqueado ? 'grayscale(1)' : undefined,
                        }}
                      >
                        <span
                          className={`priority-dot${col.key === 'qualificados' || col.key === 'espera' || col.key === 'negociacao' || col.key === 'despacho' ? '' : ` priority-dot-${l.priority === 'Alta' ? 'alta' : l.priority === 'Média' ? 'media' : 'baixa'}`}`}
                          style={URGENCIA_COR[l.temperature] ? { background: URGENCIA_COR[l.temperature] } : undefined}
                        />
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <div style={{ fontWeight: 600, fontSize: 13.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {l.name || 'Sem nome informado'}
                          </div>
                          <small style={{ display: 'block', fontFamily: "'DM Mono',monospace" }}>{l.contact}</small>
                          {col.key === 'novos' && <small style={{ display: 'block', marginTop: 4, color: 'var(--accent)' }}>etapa: {l.state}</small>}
                          {l.demand && col.key !== 'novos' && (
                            <small style={{ display: 'block', marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {l.demand}
                            </small>
                          )}
                          {(col.key === 'qualificados' || col.key === 'espera' || col.key === 'negociacao' || col.key === 'despacho') && l.temperature && (
                            <small style={{ display: 'block', marginTop: 4, color: 'var(--muted)' }}>{l.temperature}</small>
                          )}
                          {l.owner && (col.key === 'negociacao' || col.key === 'despacho') && (
                            <small style={{ display: 'block', marginTop: 4, color: 'var(--muted)' }}>Responsável: {l.owner_nome}</small>
                          )}
                        </div>
                      </article>
                      );
                    })}
                    {!items.length && <p style={{ fontSize: 12.5, color: 'var(--muted-soft)', padding: '4px 2px' }}>Nenhum lead aqui.</p>}
                  </div>
                  {col.key === 'despacho' && minhasNoDespacho.length > 0 && (
                    <button
                      type="button"
                      onClick={enviarDespachos}
                      disabled={enviandoDespachos}
                      style={{ margin: '10px 14px 14px', background: 'var(--success)', borderColor: 'var(--success)' }}
                    >
                      {enviandoDespachos && <Spinner />}
                      Enviar Despachos
                    </button>
                  )}
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
          {desqualificadosCount > 0 && (
            <>{desqualificadosCount} lead{desqualificadosCount === 1 ? '' : 's'} desqualificado{desqualificadosCount === 1 ? '' : 's'}/desconfiado{desqualificadosCount === 1 ? '' : 's'} (fora do fluxo, ver Dashboard)</>
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
                <button type="button" style={{ background: '#25D366', borderColor: '#25D366' }}>
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
        <Overlay onClose={() => setNegociacaoModal(null)}>
          <h2 style={{ marginTop: 0 }}>Cadastro do atendimento</h2>
          <p style={{ color: 'var(--muted)', marginBottom: 16 }}>Dados coletados pelo agente durante a triagem.</p>
          <TriagemResumo lead={negociacaoModal} api={api} onUpdated={aplicarAtualizacao} />
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button type="button" onClick={() => confirmarNegociacao(negociacaoModal)} disabled={actionBusy} style={{ background: '#2563EB', borderColor: '#2563EB' }}>
              {actionBusy && <Spinner />}
              Acompanhar
            </button>
            <a href={`https://wa.me/${negociacaoModal.contact.replace(/\D/g, '')}`} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
              <button type="button" style={{ background: '#25D366', borderColor: '#25D366' }}>
                Contatar
              </button>
            </a>
            <button type="button" className="secondary" onClick={() => setNegociacaoModal(null)}>
              Cancelar
            </button>
          </div>
        </Overlay>
      )}

      {cadastroSemAtendimentoModal && (
        <Overlay onClose={() => setCadastroSemAtendimentoModal(null)}>
          <h2 style={{ marginTop: 0 }}>Cadastrar sem atendimento</h2>
          <p style={{ color: 'var(--muted)', marginBottom: 16 }}>Dados coletados pelo agente durante a triagem.</p>
          <TriagemResumo lead={cadastroSemAtendimentoModal} api={api} onUpdated={aplicarAtualizacao} />
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
