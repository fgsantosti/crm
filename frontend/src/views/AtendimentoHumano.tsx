import { useEffect, useState } from 'react';
import { fetchTodasAsPaginas, type Api } from '../api';
import type { Company, Lead, Me } from '../types';
import { SkeletonCards, Spinner } from '../components/Skeleton';
import { AreaSelect } from '../components/AreaSelect';
import { ObservacoesLead } from '../components/LeadDetalheDialog';
import { IconeWhatsapp } from '../components/Icones';

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
  const [areaDespacho, setAreaDespacho] = useState('');
  const [enviando, setEnviando] = useState(false);

  function load() {
    setBusy(true);
    setError('');
    // Filtro no servidor (meus=1): dono pelo id do usuário, todas as páginas.
    fetchTodasAsPaginas<Lead>(api, `/leads/?company=${company.id}&meus=1`)
      .then((todos) => setLeads(todos.filter((l) => l.owner === me.id)))
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
      // Só reserva o desfecho (coluna "Despacho") -- vira definitivo no "Enviar Despachos".
      const updated: Lead = await api(`/leads/${lead.id}/preparar-despacho/?company=${company.id}`, {
        method: 'POST',
        body: JSON.stringify({ desfecho, especialidade: areaDespacho || undefined }),
      });
      setLeads((v) => v.map((l) => (l.id === updated.id ? updated : l)));
      setDespachandoId(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setActionBusy(null);
    }
  }

  async function enviarDespachos() {
    setEnviando(true);
    setError('');
    try {
      await api(`/leads/enviar-despachos/?company=${company.id}`, { method: 'POST' });
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setEnviando(false);
    }
  }

  async function despacharBloquear(lead: Lead) {
    setActionBusy(lead.id);
    setError('');
    try {
      await api(`/leads/${lead.id}/despachar-bloquear/?company=${company.id}`, { method: 'POST' });
      setLeads((v) => v.filter((l) => l.id !== lead.id));
      setDespachandoId(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setActionBusy(null);
    }
  }

  function botaoBloquear(lead: Lead) {
    return (
      <button type="button" className="block-button" onClick={() => despacharBloquear(lead)} disabled={actionBusy === lead.id || enviando}
        title="Conclui o atendimento e bloqueia o número. Remova-o da BlackList para liberar uma nova triagem.">
        {actionBusy === lead.id && <Spinner />}
        Despachar e bloquear
      </button>
    );
  }

  function abrirDespacho(l: Lead) {
    setAreaDespacho(l.especialidade || '');
    setDespachandoId((v) => (v === l.id ? null : l.id));
  }

  const busca = (l: Lead) => `${l.name} ${l.contact}`.toLowerCase().includes(search.toLowerCase());
  const visible = leads.filter((l) => l.etapa_atendimento !== 'despacho' && busca(l));
  const noDespacho = leads.filter((l) => l.etapa_atendimento === 'despacho' && busca(l));
  const rotuloDesfecho = (v: string) => DESFECHO_OPTIONS.find((o) => o.value === v)?.label || v;

  function painelDespacho(l: Lead) {
    return (
      <div className="panel" style={{ padding: 16, marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <h3 style={{ margin: 0, fontSize: 15 }}>Classificar desfecho</h3>
        <AreaSelect api={api} companyId={company.id} value={areaDespacho} onChange={setAreaDespacho} />
        {DESFECHO_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className="desfecho-option"
            onClick={() => despachar(l, opt.value)}
            disabled={actionBusy === l.id}
            style={{ '--cor': opt.color } as React.CSSProperties}
          >
            {actionBusy === l.id && <Spinner />}
            <strong style={{ display: 'block' }}>{opt.label}</strong>
            <small style={{ color: 'var(--muted)', fontWeight: 400 }}>{opt.help}</small>
          </button>
        ))}
      </div>
    );
  }

  return (
    <>
      <header className="page-header" style={{ alignItems: 'flex-end' }}>
        <div>
          <small className="eyebrow">Escalonamento</small>
          <h1>Meus Atendimentos</h1>
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
                <p style={{ color: 'var(--ink)', marginBottom: 4 }}>{l.demand || (l.notes ? '' : 'Sem detalhes registrados.')}</p>
                {l.notes && (
                  <div style={{ fontSize: 13, marginBottom: 6 }}>
                    <small style={{ display: 'block', color: 'var(--muted)' }}>Observações</small>
                    <ObservacoesLead notes={l.notes} />
                  </div>
                )}
                <p style={{ fontSize: 12.5 }}>
                  {l.last_contact ? `Último contato em ${new Date(l.last_contact).toLocaleString('pt-BR')}` : 'Sem contato registrado'} · em execução
                </p>
              </div>
              <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                {l.contact && (
                  <a href={`https://wa.me/${l.contact.replace(/\D/g, '')}`} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                    <button type="button" style={{ background: '#25D366', borderColor: '#25D366', display: 'inline-flex', alignItems: 'center', gap: 8 }}>
<IconeWhatsapp size={22} />
                      Conversar
                    </button>
                  </a>
                )}
                <button type="button" className="danger-outline" onClick={() => abrirDespacho(l)} disabled={actionBusy === l.id}>
                  Despachar
                </button>
                {botaoBloquear(l)}
              </div>
            </div>
            {despachandoId === l.id && painelDespacho(l)}
          </article>
        ))}
        {!busy && !visible.length && <div className="empty">Nenhum caso em andamento sob sua responsabilidade.</div>}
      </section>

      {noDespacho.length > 0 && (
        <section className="section">
          <div className="section-head">
            <h2>Prontos para envio (Despacho)</h2>
            <button type="button" onClick={enviarDespachos} disabled={enviando} style={{ background: 'var(--success)', borderColor: 'var(--success)' }}>
              {enviando && <Spinner />}
              Enviar Despachos ({noDespacho.length})
            </button>
          </div>
          <p style={{ fontSize: 12.5, color: 'var(--muted)', marginBottom: 12 }}>
            Ao enviar, o atendimento é concluído com o desfecho e a área escolhidos e sai da sua lista.
          </p>
          {noDespacho.map((l) => (
            <article key={l.id} className="queue-card" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
                <div style={{ flex: '1 1 320px', minWidth: 0 }}>
                  <div className="queue-meta">
                    <strong style={{ fontSize: 16 }}>{l.name || 'Sem nome informado'}</strong>
                    <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 12.5, color: 'var(--muted)' }}>{l.contact}</span>
                    {l.origem_manual && <span className="chip chip-neutral">cadastro manual</span>}
                  </div>
                  <p style={{ fontSize: 12.5 }}>
                    Desfecho: <strong style={{ color: 'var(--ink)' }}>{rotuloDesfecho(l.desfecho_pendente)}</strong> · Área:{' '}
                    <strong style={{ color: 'var(--ink)' }}>{l.especialidade || '—'}</strong>
                  </p>
                </div>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  <button type="button" className="secondary" onClick={() => abrirDespacho(l)} disabled={actionBusy === l.id || enviando}>
                    Alterar
                  </button>
                  {botaoBloquear(l)}
                </div>
              </div>
              {despachandoId === l.id && painelDespacho(l)}
            </article>
          ))}
        </section>
      )}
    </>
  );
}
