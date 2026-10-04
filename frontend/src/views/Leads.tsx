import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Api } from '../api';
import type { Company, Lead, LeadEvent, Me, Paginated } from '../types';
import { SkeletonCards, Spinner } from '../components/Skeleton';

// Mesma ordem de services.URGENCIA_POR_FAIXA no backend (menos urgente -> mais urgente).
const URGENCIA_RANK: Record<string, number> = { Desqualificado: 0, Desconfiado: 1, Remarketing: 2, Qualificado: 3, Quente: 4 };
const URGENCIA_COR: Record<string, string> = { Remarketing: '#2563EB', Qualificado: '#D4A72C', Quente: '#E2574C' };
const FORA_DO_KANBAN = new Set(['Desqualificado', 'Desconfiado']);

const DESFECHO_OPTIONS: { value: 'encerrado' | 'comprometido' | 'falha'; label: string; color: string; help: string }[] = [
  { value: 'encerrado', label: 'Encerrado', color: 'var(--success)', help: 'Sucesso de comunicação — o cliente conseguiu realizar o que desejava.' },
  { value: 'comprometido', label: 'Comprometido', color: 'var(--warn)', help: 'Algo não saiu conforme o planejado; o cliente pode voltar ou não dar continuidade.' },
  { value: 'falha', label: 'Falha durante o atendimento', color: 'var(--danger)', help: 'O cliente desistiu ou cessou o contato durante o atendimento humano.' },
];

type ColumnKey = 'novos' | 'qualificados' | 'espera' | 'negociacao' | 'despacho';

const COLUMNS: { key: ColumnKey; label: string }[] = [
  { key: 'novos', label: 'Novos Leads' },
  { key: 'qualificados', label: 'Qualificados' },
  { key: 'espera', label: 'Atendimentos em espera' },
  { key: 'negociacao', label: 'Em negociação' },
  { key: 'despacho', label: 'Despacho' },
];

function columnOf(l: Lead): ColumnKey {
  if (!l.bot_closed) return 'novos';
  if (l.etapa_atendimento === 'espera') return 'espera';
  if (l.etapa_atendimento === 'negociacao') return 'negociacao';
  if (l.etapa_atendimento === 'despacho') return 'despacho';
  return 'qualificados';
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

function TriagemResumo({ lead }: { lead: Lead }) {
  return (
    <div className="fields" style={{ marginBottom: 16 }}>
      <label style={{ margin: 0 }}>
        Nome
        <input readOnly value={lead.name || 'Sem nome informado'} />
      </label>
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
    </div>
  );
}

export function Leads({ api, company, role, me }: { api: Api; company: Company; role: 'atendente' | 'empresa' | 'admin'; me: Me }) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [search, setSearch] = useState('');
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

  const podeAtender = role === 'atendente';
  const minhaIdentidade = me.display_name || me.username;

  function load(silent = false) {
    if (!silent) setBusy(true);
    if (!silent) setError('');
    api(`/leads/?company=${company.id}`)
      .then((d: Paginated<Lead>) => {
        setLeads(d.results);
        setSelected((s) => (s ? d.results.find((l) => l.id === s.id) || s : s));
      })
      .catch((e) => {
        if (!silent) setError(e.message);
      })
      .finally(() => {
        if (!silent) setBusy(false);
      });
  }

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

  async function confirmarNegociacao(lead: Lead) {
    const updated = await chamarAcao('negociar', lead);
    if (updated) setNegociacaoModal(null);
  }

  async function confirmarCadastroSemAtendimento(lead: Lead) {
    const updated = await chamarAcao('preparar-despacho', lead, { auto_falha: true });
    if (updated) setCadastroSemAtendimentoModal(null);
  }

  async function confirmarDespacho(lead: Lead, desfecho: 'encerrado' | 'comprometido' | 'falha') {
    const updated = await chamarAcao('preparar-despacho', lead, { desfecho });
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

  const desqualificados = leads.filter((l) => FORA_DO_KANBAN.has(l.temperature));

  const visible = leads
    .filter((l) => !l.desfecho)
    .filter((l) => !l.origem_manual)
    .filter((l) => !FORA_DO_KANBAN.has(l.temperature))
    .filter((l) => `${l.name} ${l.contact}`.toLowerCase().includes(search.toLowerCase()));

  function orderedItems(key: ColumnKey) {
    const items = visible.filter((l) => columnOf(l) === key);
    if (key === 'qualificados') {
      // Mais fria primeiro, mais quente por último (azul -> vermelho).
      return [...items].sort((a, b) => (URGENCIA_RANK[a.temperature] ?? 9) - (URGENCIA_RANK[b.temperature] ?? 9));
    }
    if (key === 'espera' || key === 'negociacao' || key === 'despacho') {
      return [...items].sort((a, b) => (URGENCIA_RANK[b.temperature] ?? -1) - (URGENCIA_RANK[a.temperature] ?? -1));
    }
    return items;
  }

  function podeArrastar(l: Lead): boolean {
    if (!podeAtender) return false;
    const col = columnOf(l);
    if (col === 'novos') return false;
    if (col === 'qualificados') return true;
    return l.owner === minhaIdentidade;
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

  const minhasNoDespacho = leads.filter((l) => columnOf(l) === 'despacho' && l.owner === minhaIdentidade && !l.desfecho);

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
            <SkeletonCards count={5} height={90} />
          </div>
        ) : (
          <div className="kanban">
            {COLUMNS.map((col) => {
              const items = orderedItems(col.key);
              return (
                <div
                  key={col.key}
                  className="kanban-col"
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault();
                    const lead = leads.find((l) => l.id === dragId) || null;
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
                    {items.map((l) => (
                      <article
                        key={l.id}
                        className={`kanban-card${selected?.id === l.id ? ' selected' : ''}`}
                        draggable={podeArrastar(l)}
                        onDragStart={() => setDragId(l.id)}
                        onDragEnd={() => setDragId(null)}
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
                        style={{ opacity: dragId === l.id ? 0.5 : 1, cursor: podeArrastar(l) ? 'grab' : undefined }}
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
                          {l.owner && col.key !== 'qualificados' && (
                            <small style={{ display: 'block', marginTop: 4, color: 'var(--muted)' }}>owner: {l.owner}</small>
                          )}
                        </div>
                      </article>
                    ))}
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
            Etapa: <strong style={{ color: 'var(--ink)' }}>{selected.state}</strong> · Bot {selected.bot_closed ? 'encerrado' : 'ativo'}
            {selected.temperature && (
              <>
                {' '}
                · Temperatura: <strong style={{ color: 'var(--ink)' }}>{selected.temperature}</strong>
              </>
            )}
            {selected.owner && (
              <>
                {' '}
                · Responsável: <strong style={{ color: 'var(--ink)' }}>{selected.owner}</strong>
              </>
            )}
          </p>

          {selected.contact && (
            <div style={{ marginBottom: 20 }}>
              <a href={`https://wa.me/${selected.contact.replace(/\D/g, '')}`} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                <button type="button" style={{ background: '#25D366', borderColor: '#25D366' }}>
                  Conversar
                </button>
              </a>
            </div>
          )}

          <TriagemResumo lead={selected} />
          <p style={{ fontSize: 12.5, color: 'var(--muted)', marginBottom: 20 }}>
            Esses dados vêm do agente durante a triagem — não são editáveis aqui. As transições de atendimento (reivindicar,
            negociar, despachar) acontecem arrastando o card entre as colunas do Kanban.
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
        </section>
      )}

      {negociacaoModal && (
        <Overlay onClose={() => setNegociacaoModal(null)}>
          <h2 style={{ marginTop: 0 }}>Cadastro do atendimento</h2>
          <p style={{ color: 'var(--muted)', marginBottom: 16 }}>Dados coletados pelo agente durante a triagem.</p>
          <TriagemResumo lead={negociacaoModal} />
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
          <TriagemResumo lead={cadastroSemAtendimentoModal} />
          <p style={{ fontSize: 13, color: 'var(--danger)', marginBottom: 16 }}>
            Este lead será marcado automaticamente como <strong>Falha durante o atendimento</strong> — ele vai para a coluna
            Despacho, pendente do botão "Enviar Despachos".
          </p>
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
