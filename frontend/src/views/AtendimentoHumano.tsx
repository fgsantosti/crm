import { useEffect, useState } from 'react';
import type { Api } from '../api';
import type { Company, Lead, Me, Paginated } from '../types';
import { SkeletonCards, Spinner } from '../components/Skeleton';

const DESFECHO_OPTIONS: { value: 'encerrado' | 'comprometido' | 'falha'; label: string; color: string; help: string }[] = [
  { value: 'encerrado', label: 'Encerrado', color: 'var(--success)', help: 'Sucesso de comunicação — o cliente conseguiu realizar o que desejava.' },
  { value: 'comprometido', label: 'Comprometido', color: 'var(--warn)', help: 'Algo não saiu conforme o planejado; o cliente pode voltar ou não dar continuidade.' },
  { value: 'falha', label: 'Falha durante o atendimento', color: 'var(--danger)', help: 'O cliente desistiu ou cessou o contato durante o atendimento humano.' },
];

export function AtendimentoHumano({ api, company, me }: { api: Api; company: Company; me: Me }) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [despachandoId, setDespachandoId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [novo, setNovo] = useState(false);
  const [salvandoNovo, setSalvandoNovo] = useState(false);

  const minhaIdentidade = me.display_name || me.username;

  function load() {
    setBusy(true);
    setError('');
    api(`/leads/?company=${company.id}`)
      .then((d: Paginated<Lead>) =>
        setLeads(d.results.filter((l) => !l.desfecho && l.owner === minhaIdentidade && (l.etapa_atendimento === 'negociacao' || l.origem_manual))),
      )
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [company.id]);

  async function criarManual(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSalvandoNovo(true);
    setError('');
    const form = new FormData(e.currentTarget);
    try {
      const created = await api(`/leads/manual/?company=${company.id}`, {
        method: 'POST',
        body: JSON.stringify({ name: form.get('name'), contact: form.get('contact'), demand: form.get('demand') }),
      });
      setLeads((v) => [created, ...v]);
      setNovo(false);
      (e.currentTarget as HTMLFormElement).reset();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSalvandoNovo(false);
    }
  }

  async function despachar(lead: Lead, desfecho: 'encerrado' | 'comprometido' | 'falha') {
    setActionBusy(lead.id);
    setError('');
    try {
      // Só reserva o desfecho e move pra coluna "Despacho" do Kanban -- o envio
      // definitivo (Lead.desfecho) acontece pelo botão "Enviar Despachos" em Leads.
      await api(`/leads/${lead.id}/preparar-despacho/?company=${company.id}`, { method: 'POST', body: JSON.stringify({ desfecho }) });
      setLeads((v) => v.filter((l) => l.id !== lead.id));
      setDespachandoId(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setActionBusy(null);
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
            {leads.length} caso{leads.length === 1 ? '' : 's'} sob sua responsabilidade.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <input
            placeholder="Buscar nome ou telefone"
            aria-label="Buscar atendimentos humanos"
            style={{ width: 260 }}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button type="button" onClick={() => setNovo((v) => !v)}>
            + Novo atendimento
          </button>
        </div>
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {novo && (
        <form onSubmit={criarManual} className="panel" style={{ padding: 16, marginBottom: 20, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>Novo atendimento (fora do WhatsApp)</h3>
          <small style={{ color: 'var(--muted)' }}>
            Cadastra um contato que você está atendendo por outro canal — não passa pela triagem do agente nem aparece no
            Kanban de Leads, só entra nas contagens do Dashboard.
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
            Demanda
            <input name="demand" />
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
        {busy && !visible.length && <SkeletonCards count={3} height={96} />}
        {visible.map((l) => (
          <article key={l.id} className="queue-card" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              <div style={{ flex: '1 1 320px', minWidth: 0 }}>
                <div className="queue-meta">
                  <strong style={{ fontSize: 16 }}>{l.name || 'Sem nome informado'}</strong>
                  <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 12.5, color: 'var(--muted)' }}>{l.contact}</span>
                  {l.origem_manual && <span className="chip chip-neutral">cadastro manual</span>}
                </div>
                <p style={{ color: 'var(--ink)', marginBottom: 4 }}>{l.demand || l.notes || 'Sem detalhes registrados.'}</p>
                <p style={{ fontSize: 12.5 }}>
                  {l.last_contact ? `Último contato em ${new Date(l.last_contact).toLocaleString('pt-BR')}` : 'Sem contato registrado'} · em execução
                </p>
              </div>
              <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                {l.contact && (
                  <a href={`https://wa.me/${l.contact.replace(/\D/g, '')}`} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                    <button type="button" style={{ background: '#25D366', borderColor: '#25D366' }}>
                      Conversar
                    </button>
                  </a>
                )}
                <button type="button" className="danger-outline" onClick={() => setDespachandoId((v) => (v === l.id ? null : l.id))}>
                  Despachar
                </button>
              </div>
            </div>
            {despachandoId === l.id && (
              <div className="panel" style={{ padding: 16, marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
                <h3 style={{ margin: 0, fontSize: 15 }}>Classificar desfecho</h3>
                {DESFECHO_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => despachar(l, opt.value)}
                    disabled={actionBusy === l.id}
                    style={{ textAlign: 'left', borderColor: opt.color, color: opt.color, background: '#fff' }}
                  >
                    {actionBusy === l.id && <Spinner />}
                    <strong style={{ display: 'block' }}>{opt.label}</strong>
                    <small style={{ color: 'var(--muted)', fontWeight: 400 }}>{opt.help}</small>
                  </button>
                ))}
              </div>
            )}
          </article>
        ))}
        {!busy && !visible.length && <div className="empty">Nenhum caso sob sua responsabilidade no momento.</div>}
      </section>
    </>
  );
}
