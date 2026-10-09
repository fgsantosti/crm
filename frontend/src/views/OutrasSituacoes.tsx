import { useCallback, useEffect, useState } from 'react';
import { fetchTodasAsPaginas, type Api } from '../api';
import type { Company, Lead, Me } from '../types';
import { LeadDetalheDialog, ObservacoesLead } from '../components/LeadDetalheDialog';
import { Spinner } from '../components/Skeleton';
import { AreaSelect } from '../components/AreaSelect';
import { ConfirmPessoa, useConfirmar } from '../components/ConfirmDialog';
import { IconeWhatsapp } from '../components/Icones';

const DESFECHO_OPTIONS: { value: 'encerrado' | 'comprometido' | 'falha'; label: string; color: string; help: string }[] = [
  { value: 'encerrado', label: 'Encerrado', color: 'var(--success)', help: 'Sucesso de comunicação — o cliente conseguiu realizar o que desejava.' },
  { value: 'comprometido', label: 'Comprometido', color: 'var(--warn)', help: 'Algo não saiu conforme o planejado; o cliente pode voltar ou não dar continuidade.' },
  { value: 'falha', label: 'Falha durante o atendimento', color: 'var(--danger)', help: 'O cliente desistiu ou cessou o contato durante o atendimento.' },
];

const ROTULOS: Record<string, string> = { acompanhamento: 'Acompanhamento de processo' };
export const rotuloSituacao = (valor: string) => ROTULOS[valor] ?? valor;

/**
 * "Outras situações" (item próprio da barra lateral, entre Todos os leads e Pendências): leads que não são leads novos -- hoje, clientes que já
 * têm processo no escritório e querem acompanhá-lo. Ficam fora das temperaturas e do Kanban.
 * Atendentes assumem e concluem; a conta Empresa vê e pode concluir.
 */
export function OutrasSituacoes({ api, company, role, me, onChange }: { api: Api; company: Company; role: 'atendente' | 'empresa' | 'admin'; me: Me; onChange?: (abertos: number) => void }) {
  const confirmar = useConfirmar();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [busy, setBusy] = useState(true);
  const [acaoId, setAcaoId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [detalhe, setDetalhe] = useState<Lead | null>(null);
  const [novo, setNovo] = useState(false);
  const [despachandoId, setDespachandoId] = useState<string | null>(null);
  const [areaDespacho, setAreaDespacho] = useState('');
  const [busca, setBusca] = useState('');
  const [salvandoNovo, setSalvandoNovo] = useState(false);

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

  async function criarAcompanhamento(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSalvandoNovo(true);
    setError('');
    const form = new FormData(e.currentTarget);
    try {
      await api(`/leads/especial/?company=${company.id}`, {
        method: 'POST',
        body: JSON.stringify({ name: form.get('name'), contact: form.get('contact'), demand: form.get('demand'), observacoes: form.get('observacoes') }),
      });
      setNovo(false);
      await carregar(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSalvandoNovo(false);
    }
  }

  async function assumir(lead: Lead) {
    setAcaoId(lead.id);
    setError('');
    try {
      await api(`/leads/${lead.id}/especial/assumir/?company=${company.id}`, { method: 'POST' });
      await carregar(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAcaoId(null);
    }
  }

  // Mesma regra de despacho de Meus Atendimentos: classifica o desfecho (e a área); entra nas
  // contagens de concluídos/despachos do Dashboard e libera o número.
  async function despachar(lead: Lead, desfecho: 'encerrado' | 'comprometido' | 'falha' | 'bloqueado') {
    if (desfecho === 'bloqueado' && !(await confirmar({ titulo: 'Despachar e bloquear?', mensagem: 'O número vai para a BlackList até você removê-lo de lá.', detalhe: <ConfirmPessoa nome={lead.name || 'Sem nome informado'} sub={lead.contact} />, tom: 'perigo', icone: 'aviso', confirmar: 'Despachar e bloquear' }))) return;
    setAcaoId(lead.id);
    setError('');
    try {
      await api(`/leads/${lead.id}/especial/despachar/?company=${company.id}`, {
        method: 'POST',
        body: JSON.stringify({ desfecho, especialidade: desfecho === 'bloqueado' ? undefined : areaDespacho || undefined }),
      });
      setDespachandoId(null);
      await carregar(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAcaoId(null);
    }
  }

  function abrirDespacho(l: Lead) {
    setAreaDespacho(l.especialidade || '');
    setDespachandoId((v) => (v === l.id ? null : l.id));
  }

  function painelDespacho(l: Lead) {
    return (
      <div className="panel" style={{ padding: 16, marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <h3 style={{ margin: 0, fontSize: 15 }}>Classificar desfecho</h3>
        <AreaSelect api={api} companyId={company.id} value={areaDespacho} onChange={setAreaDespacho} />
        {DESFECHO_OPTIONS.map((opt) => (
          <button key={opt.value} type="button" className="desfecho-option" onClick={() => despachar(l, opt.value)} disabled={acaoId === l.id} style={{ '--cor': opt.color } as React.CSSProperties}>
            {acaoId === l.id && <Spinner />}
            <strong style={{ display: 'block' }}>{opt.label}</strong>
            <small style={{ color: 'var(--muted)', fontWeight: 400 }}>{opt.help}</small>
          </button>
        ))}
        <button type="button" className="block-button" onClick={() => despachar(l, 'bloqueado')} disabled={acaoId === l.id} title="Conclui o acompanhamento e bloqueia o número. Remova-o da BlackList para liberar uma nova triagem.">
          Despachar e bloquear
        </button>
      </div>
    );
  }

  const termo = busca.trim().toLowerCase();
  const visiveis = termo ? leads.filter((l) => `${l.name} ${l.contact} ${l.demand} ${l.notes}`.toLowerCase().includes(termo)) : leads;
  const podeAssumir = role === 'atendente';
  const podeDespachar = (l: Lead) => role === 'empresa' || !l.owner || l.owner === me.id;

  return (
    <>
      <header className="page-header" style={{ alignItems: 'flex-end' }}>
        <div>
          <small className="eyebrow">Fora do fluxo de leads novos</small>
          <h1>Outras situações</h1>
          <p>Clientes que já têm processo e querem acompanhá-lo. Não são leads novos e não têm temperatura.{leads.length ? ` ${leads.length} em aberto.` : ''}</p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <input
            placeholder="Buscar nome, telefone ou observação"
            aria-label="Buscar acompanhamentos"
            style={{ width: 260 }}
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
          />
          <button type="button" onClick={() => setNovo((v) => !v)}>
            + Novo acompanhamento
          </button>
        </div>
      </header>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {novo && (
        <form onSubmit={criarAcompanhamento} className="panel" style={{ padding: 16, marginBottom: 20, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>Novo acompanhamento</h3>
          <small style={{ color: 'var(--muted)' }}>
            Cadastra um cliente que já tem processo no escritório e contatou por outro canal. Não passa pela triagem do agente e não conta como lead nova.
          </small>
          <div className="fields">
            <label style={{ margin: 0 }}>
              Nome
              <input name="name" />
            </label>
            <label style={{ margin: 0 }}>
              Contato (telefone)
              <input name="contact" required />
            </label>
          </div>
          <label style={{ margin: 0 }}>
            Demanda (qual processo ou assunto)
            <input name="demand" maxLength={300} />
          </label>
          <label style={{ margin: 0 }}>
            Observações (separadas por “;”)
            <input name="observacoes" maxLength={1000} placeholder="Ex.: Filha envia os documentos; Prefere contato à tarde" />
          </label>
          <div style={{ display: 'flex', gap: 10 }}>
            <button disabled={salvandoNovo}>
              {salvandoNovo && <Spinner />}
              Cadastrar
            </button>
            <button type="button" className="secondary" onClick={() => setNovo(false)}>
              Cancelar
            </button>
          </div>
        </form>
      )}

      <section className="section">
        {busy && !leads.length && <p style={{ fontSize: 13 }}>Carregando…</p>}
        {!busy && !leads.length && <div className="empty">Nenhum acompanhamento em aberto.</div>}
        {!busy && leads.length > 0 && !visiveis.length && <div className="empty">Nenhum acompanhamento encontrado para “{busca.trim()}”.</div>}
        {visiveis.map((l) => (
          <article key={l.id} className="queue-card" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              <div style={{ flex: '1 1 320px', minWidth: 0, cursor: 'pointer' }} onClick={() => setDetalhe(l)}>
                <div className="queue-meta">
                  <strong style={{ fontSize: 16 }}>{l.name || 'Sem nome informado'}</strong>
                  {l.origem_manual && <span className="chip chip-neutral">cadastro manual</span>}
                  <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 12.5, color: 'var(--muted)' }}>{l.contact}</span>
                  <span className="chip chip-neutral">{rotuloSituacao(l.situacao_especial)}</span>
                </div>
                {l.demand && <p style={{ color: 'var(--ink)', marginBottom: 4 }}>{l.demand}</p>}
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
                  <a href={`https://wa.me/${l.contact.replace(/\D/g, '')}`} target="_blank" rel="noreferrer" style={{ textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  <IconeWhatsapp />
                    <button type="button" style={{ background: '#25D366', borderColor: '#25D366' }}>
                      Conversar
                    </button>
                  </a>
                )}
                {podeAssumir && !l.owner && (
                  <button type="button" onClick={() => assumir(l)} disabled={acaoId !== null}>
                    {acaoId === l.id && <Spinner />}
                    Assumir
                  </button>
                )}
                {podeDespachar(l) && (
                  <button type="button" className="danger-outline" onClick={() => abrirDespacho(l)} disabled={acaoId !== null}>
                    Despachar
                  </button>
                )}
              </div>
            </div>
            {despachandoId === l.id && painelDespacho(l)}
          </article>
        ))}
      {detalhe && <LeadDetalheDialog lead={detalhe} estagio={rotuloSituacao(detalhe.situacao_especial)} historico={company.coletar_historico_conversa ? { api, companyId: company.id } : undefined} onClose={() => setDetalhe(null)} />}
    </section>
    </>
  );
}
