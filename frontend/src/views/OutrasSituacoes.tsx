import { useCallback, useEffect, useState } from 'react';
import { fetchTodasAsPaginas, type Api } from '../api';
import type { Company, Lead, Me } from '../types';
import { LeadDetalheDialog, ObservacoesLead } from '../components/LeadDetalheDialog';
import { Spinner } from '../components/Skeleton';

export const COR_ESPECIAL = '#7C3AED';

const ROTULOS: Record<string, string> = { acompanhamento: 'Acompanhamento de processo' };
export const rotuloSituacao = (valor: string) => ROTULOS[valor] ?? valor;

/**
 * "Outras situações" (item próprio da barra lateral, entre Todos os leads e Pendências): leads que não são leads novos -- hoje, clientes que já
 * têm processo no escritório e querem acompanhá-lo. Ficam fora das temperaturas e do Kanban.
 * Atendentes assumem e concluem; a conta Empresa vê e pode concluir.
 */
export function OutrasSituacoes({ api, company, role, me, onChange }: { api: Api; company: Company; role: 'atendente' | 'empresa' | 'admin'; me: Me; onChange?: (abertos: number) => void }) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [busy, setBusy] = useState(true);
  const [acaoId, setAcaoId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [detalhe, setDetalhe] = useState<Lead | null>(null);

  const carregar = useCallback(
    (silent = false) => {
      if (!silent) setBusy(true);
      return fetchTodasAsPaginas<Lead>(api, `/leads/?company=${company.id}&especial=1`)
        .then((todos) => {
          setLeads(todos);
          onChange?.(todos.length);
          setDetalhe((d) => (d ? todos.find((l) => l.id === d.id) ?? null : d));
        })
        .catch((e) => {
          if (!silent) setError(e.message);
        })
        .finally(() => {
          if (!silent) setBusy(false);
        });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [api, company.id],
  );

  useEffect(() => {
    setError('');
    setDetalhe(null);
    carregar();
    const id = setInterval(() => carregar(true), 15000);
    return () => clearInterval(id);
  }, [carregar]);

  async function acao(lead: Lead, caminho: 'assumir' | 'concluir') {
    if (caminho === 'concluir' && !window.confirm(`Concluir o acompanhamento de "${lead.name || lead.contact}"? O número é liberado e sai desta lista.`)) return;
    setAcaoId(lead.id);
    setError('');
    try {
      await api(`/leads/${lead.id}/especial/${caminho}/?company=${company.id}`, { method: 'POST' });
      await carregar(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAcaoId(null);
    }
  }

  const podeAssumir = role === 'atendente';
  const podeConcluir = (l: Lead) => role === 'empresa' || !l.owner || l.owner === me.id;

  return (
    <>
      <header className="page-header" style={{ alignItems: 'flex-end' }}>
        <div>
          <small className="eyebrow" style={{ color: COR_ESPECIAL }}>Fora do fluxo de leads novos</small>
          <h1 style={{ color: COR_ESPECIAL }}>Outras situações</h1>
          <p>Clientes que já têm processo e querem acompanhá-lo. Não são leads novos e não têm temperatura.{leads.length ? ` ${leads.length} em aberto.` : ''}</p>
        </div>
      </header>
    <section className="panel" style={{ borderTop: `3px solid ${COR_ESPECIAL}` }} aria-label="Outras situações em aberto">
      {error && (
        <p role="alert" className="error" style={{ margin: '0 20px' }}>
          {error}
        </p>
      )}
      <div style={{ padding: '4px 20px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {busy && !leads.length && <p style={{ fontSize: 13 }}>Carregando…</p>}
        {!busy && !leads.length && <div className="empty">Nenhum acompanhamento em aberto.</div>}
        {leads.map((l) => (
          <article key={l.id} className="queue-card" style={{ borderLeft: `4px solid ${COR_ESPECIAL}`, flexDirection: 'column', alignItems: 'stretch' }}>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              <div style={{ flex: '1 1 320px', minWidth: 0, cursor: 'pointer' }} onClick={() => setDetalhe(l)}>
                <div className="queue-meta">
                  <strong style={{ fontSize: 16 }}>{l.name || 'Sem nome informado'}</strong>
                  <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 12.5, color: 'var(--muted)' }}>{l.contact}</span>
                  <span className="chip" style={{ background: 'rgba(124,58,237,.12)', color: COR_ESPECIAL }}>
                    {rotuloSituacao(l.situacao_especial)}
                  </span>
                </div>
                <div style={{ fontSize: 13, margin: '4px 0' }}>
                  <ObservacoesLead notes={l.notes} vazio="Sem observações." />
                </div>
                <p style={{ fontSize: 12.5 }}>
                  {l.owner_nome ? `Responsável: ${l.owner_nome} · ` : 'Sem responsável · '}
                  {l.last_contact ? `Último contato em ${new Date(l.last_contact).toLocaleString('pt-BR')}` : `Entrou em ${new Date(l.created_at).toLocaleString('pt-BR')}`}
                </p>
              </div>
              <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                <button type="button" className="secondary" onClick={() => setDetalhe(l)}>
                  Ver dados
                </button>
                {l.contact && (
                  <a href={`https://wa.me/${l.contact.replace(/\D/g, '')}`} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                    <button type="button" style={{ background: '#25D366', borderColor: '#25D366' }}>
                      Conversar
                    </button>
                  </a>
                )}
                {podeAssumir && !l.owner && (
                  <button type="button" onClick={() => acao(l, 'assumir')} disabled={acaoId !== null}>
                    {acaoId === l.id && <Spinner />}
                    Assumir
                  </button>
                )}
                {podeConcluir(l) && (
                  <button type="button" className="danger-outline" onClick={() => acao(l, 'concluir')} disabled={acaoId !== null}>
                    Concluir
                  </button>
                )}
              </div>
            </div>
          </article>
        ))}
      </div>
      {detalhe && <LeadDetalheDialog lead={detalhe} estagio={rotuloSituacao(detalhe.situacao_especial)} onClose={() => setDetalhe(null)} />}
    </section>
    </>
  );
}
