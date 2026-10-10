import { useEffect, useState } from 'react';
import { fetchTodasAsPaginas, type Api } from '../api';
import type { Area, Company, CompanyInfoEntry, Paginated, Question } from '../types';
import { SkeletonCards, Spinner } from '../components/Skeleton';
import { useConfirmar } from '../components/ConfirmDialog';

export function DadosEmpresa({ api, company }: { api: Api; company: Company }) {
  const confirmar = useConfirmar();
  const [entries, setEntries] = useState<CompanyInfoEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [savingId, setSavingId] = useState<number | 'new' | null>(null);
  const [error, setError] = useState('');
  const [aba, setAba] = useState<'areas' | 'informacoes'>('areas');
  const [areas, setAreas] = useState<Area[]>([]);
  const [perguntasPorArea, setPerguntasPorArea] = useState<Record<number, number>>({});
  const [novaArea, setNovaArea] = useState<string | null>(null);
  const [savingArea, setSavingArea] = useState<number | 'new' | null>(null);
  const [aberta, setAberta] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([fetchTodasAsPaginas<Area>(api, `/areas/?company=${company.id}`), fetchTodasAsPaginas<Question>(api, `/questions/?company=${company.id}`)])
      .then(([a, q]) => {
        if (!active) return;
        setAreas(a);
        const contagem: Record<number, number> = {};
        q.forEach((x) => {
          if (x.area && x.text.trim()) contagem[x.area] = (contagem[x.area] ?? 0) + 1;
        });
        setPerguntasPorArea(contagem);
      })
      .catch((e) => active && setError(e.message));
    return () => {
      active = false;
    };
  }, [company.id]);

  useEffect(() => {
    let active = true;
    setBusy(true);
    api(`/company-info/?company=${company.id}`)
      .then((d: Paginated<CompanyInfoEntry>) => {
        if (active) setEntries(d.results);
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

  async function addArea(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!novaArea?.trim()) return;
    setSavingArea('new');
    setError('');
    try {
      const created: Area = await api(`/areas/?company=${company.id}`, { method: 'POST', body: JSON.stringify({ name: novaArea.trim() }) });
      setAreas((v) => [...v, created]);
      setNovaArea(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingArea(null);
    }
  }

  async function removeArea(area: Area) {
    if (!(await confirmar({ titulo: `Remover a área "${area.name}"?`, mensagem: 'Leads já classificados com ela mantêm o registro. As perguntas dela no Roteiro precisam ser movidas ou excluídas antes.', tom: 'atencao', icone: 'lixeira', confirmar: 'Remover área' }))) return;
    setSavingArea(area.id);
    setError('');
    try {
      await api(`/areas/${area.id}/?company=${company.id}`, { method: 'DELETE' });
      setAreas((v) => v.filter((a) => a.id !== area.id));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingArea(null);
    }
  }

  async function addEntry() {
    setSavingId('new');
    setError('');
    try {
      const created = await api(`/company-info/?company=${company.id}`, {
        method: 'POST',
        body: JSON.stringify({ title: 'Novo título', content: '' }),
      });
      setEntries((v) => [created, ...v]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingId(null);
    }
  }

  async function save(entry: CompanyInfoEntry, e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSavingId(entry.id);
    setError('');
    const form = new FormData(e.currentTarget);
    try {
      const updated = await api(`/company-info/${entry.id}/?company=${company.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ title: form.get('title'), content: form.get('content') }),
      });
      setEntries((v) => v.map((x) => (x.id === updated.id ? updated : x)));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingId(null);
    }
  }

  async function remove(entry: CompanyInfoEntry) {
    if (!(await confirmar({ titulo: `Excluir "${entry.title}"?`, mensagem: 'Essa ação não pode ser desfeita.', tom: 'perigo', icone: 'lixeira', confirmar: 'Excluir' }))) return;
    setSavingId(entry.id);
    setError('');
    try {
      await api(`/company-info/${entry.id}/?company=${company.id}`, { method: 'DELETE' });
      setEntries((v) => v.filter((x) => x.id !== entry.id));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingId(null);
    }
  }

  const fora = areas.find((a) => a.fixa);
  const comuns = areas.filter((a) => !a.fixa);

  return (
    <>
      <header className="page-header">
        <div>
          <small className="eyebrow">Base de conhecimento</small>
          <h1>Dados da empresa</h1>
          <p>O que o agente sabe sobre a empresa: as áreas em que ela atua e as informações que ele pode repassar ao cliente.</p>
        </div>
        {aba === 'informacoes' && (
          <button type="button" onClick={async () => { await addEntry(); setAberta(null); }} disabled={savingId === 'new'}>
            {savingId === 'new' && <Spinner />}+ Nova entrada
          </button>
        )}
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <div className="rot-tabs" role="tablist" aria-label="Seções dos dados da empresa">
        <button type="button" role="tab" aria-selected={aba === 'areas'} className={aba === 'areas' ? 'ativa' : ''} onClick={() => setAba('areas')}>
          Áreas de atendimento <span className="rot-contagem">{areas.length}</span>
        </button>
        <button type="button" role="tab" aria-selected={aba === 'informacoes'} className={aba === 'informacoes' ? 'ativa' : ''} onClick={() => setAba('informacoes')}>
          Informações da empresa <span className="rot-contagem">{entries.length}</span>
        </button>
      </div>

      <div key={aba} className="rot-aba">
        {aba === 'areas' && (
          <>
            <section className="dados-como" aria-label="Como o agente usa as áreas">
              <h2>Como o agente usa as áreas</h2>
              <ol>
                <li>
                  <strong>Escolhe uma só.</strong>
                  <span>Pela conversa (ou pela primeira mensagem, com Etapa Inicial), o agente classifica o assunto em UMA área desta lista e escreve o nome exatamente como está aqui. Ele nunca inventa uma área.</span>
                </li>
                <li>
                  <strong>Segue o roteiro da área.</strong>
                  <span>Cada área tem as próprias perguntas no Roteiro (aba Perguntas). Depois de classificar, o agente faz só as perguntas dela.</span>
                </li>
                <li>
                  <strong>O assunto que não cabe vira Fora de escopo.</strong>
                  <span>Se nenhuma área corresponde, o lead é concluído como Desqualificado e o número fica livre. É por isso que Fora de escopo é fixa.</span>
                </li>
              </ol>
            </section>

            <section className="dados-areas" aria-label="Áreas cadastradas">
              {comuns.map((a) => (
                <article key={a.id} className="step-card dados-area">
                  <div>
                    <strong>{a.name}</strong>
                    <small>
                      {perguntasPorArea[a.id] ? `${perguntasPorArea[a.id]} pergunta${perguntasPorArea[a.id] === 1 ? '' : 's'} no Roteiro` : 'sem perguntas no Roteiro ainda'}
                      {a.palavras_chave.trim() ? ' · com palavras-chave' : ''}
                    </small>
                  </div>
                  <button type="button" className="danger-outline" aria-label={`Remover área ${a.name}`} onClick={() => removeArea(a)} disabled={savingArea === a.id}>
                    {savingArea === a.id && <Spinner />}
                    Remover
                  </button>
                </article>
              ))}
              {fora && (
                <article className="step-card dados-area dados-area-fixa">
                  <div>
                    <strong>
                      {fora.name}
                      <span className="chip chip-neutral" style={{ marginLeft: 8 }}>fixa</span>
                    </strong>
                    <small>Sempre presente, sem perguntas: o lead é desqualificado e o número é liberado.</small>
                  </div>
                  <span className="dados-cadeado" title="Não pode ser removida" aria-label="Não pode ser removida">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
                      <rect x="3" y="7" width="10" height="7" rx="2" />
                      <path d="M5.5 7V5a2.5 2.5 0 015 0v2" strokeLinecap="round" />
                    </svg>
                  </span>
                </article>
              )}
            </section>

            {novaArea === null ? (
              <button type="button" className="rot-adicionar" onClick={() => setNovaArea('')}>
                + Nova área de atendimento
              </button>
            ) : (
              <form onSubmit={addArea} className="step-card rot-nova dados-nova">
                <label style={{ margin: 0, flex: '1 1 240px' }}>
                  Nome da área
                  <input autoFocus placeholder="ex.: Família" value={novaArea} onChange={(e) => setNovaArea(e.target.value)} required />
                </label>
                <button disabled={savingArea === 'new' || !novaArea.trim()}>
                  {savingArea === 'new' && <Spinner />}+ Adicionar
                </button>
                <button type="button" className="secondary" onClick={() => setNovaArea(null)}>
                  Cancelar
                </button>
              </form>
            )}
            <p className="dash-nota" style={{ marginTop: 12 }}>
              O nome não pode ser alterado depois (ele fica gravado nos leads e no Roteiro). Perguntas, palavras-chave e a escolha de áreas na Etapa Inicial ficam em Roteiro do agente.
            </p>
          </>
        )}

        {aba === 'informacoes' && (
          <>
            <section className="dados-como" aria-label="Como o agente usa as informações">
              <h2>Como o agente usa estas informações</h2>
              <ol>
                <li>
                  <strong>Só responde com o que está escrito aqui.</strong>
                  <span>Com o Agente conversacional ligado, o agente consulta estas entradas para responder dúvidas do cliente (horário, endereço, serviços, pagamento). Ele não inventa: se o dado não existe, diz que não tem essa informação agora.</span>
                </li>
                <li>
                  <strong>Sempre volta ao atendimento.</strong>
                  <span>Toda resposta termina convidando o cliente a seguir com a triagem. Depois que o fluxo de perguntas começa, o agente não responde mais dúvidas livres.</span>
                </li>
                <li>
                  <strong>Texto curto e direto rende mais.</strong>
                  <span>Escreva cada entrada como o cliente a leria: uma informação por título, sem rodeios. As três primeiras são obrigatórias.</span>
                </li>
              </ol>
            </section>

            <section className="section">
              {busy && !entries.length && <SkeletonCards count={3} height={70} />}
              {entries.map((entry) => {
                const aberto = aberta === entry.id;
                return (
                  <article key={entry.id} className={`step-card rot-card${aberto ? ' aberta' : ''}`}>
                    <div
                      className="rot-linha"
                      role="button"
                      tabIndex={0}
                      aria-expanded={aberto}
                      onClick={() => setAberta(aberto ? null : entry.id)}
                      onKeyDown={(e) => {
                        if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
                          e.preventDefault();
                          setAberta(aberto ? null : entry.id);
                        }
                      }}
                    >
                      <span className="step-tag">{entry.title}</span>
                      <span className={`rot-previa${entry.content.trim() ? '' : ' vazio'}`}>{entry.content.trim() ? entry.content.replace(/\s+/g, ' ').slice(0, 140) : 'Sem texto cadastrado'}</span>
                      {entry.obrigatorio && <span className="chip chip-neutral">obrigatória</span>}
                      <svg className={`rot-chevron${aberto ? ' aberto' : ''}`} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
                        <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </div>
                    {aberto && (
                      <form className="rot-corpo" onSubmit={(e) => save(entry, e)} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                        <label style={{ margin: 0 }}>
                          Título
                          <input name="title" defaultValue={entry.title} required readOnly={entry.obrigatorio} style={{ fontWeight: 600 }} />
                        </label>
                        {entry.obrigatorio && <small style={{ color: 'var(--muted)' }}>Campo obrigatório — o agente precisa dele pronto para responder clientes que perguntarem sobre a empresa.</small>}
                        <label style={{ margin: 0 }}>
                          Texto
                          <textarea name="content" defaultValue={entry.content} rows={4} />
                        </label>
                        <div style={{ display: 'flex', gap: 10 }}>
                          <button disabled={savingId === entry.id}>
                            {savingId === entry.id && <Spinner />}
                            Salvar
                          </button>
                          {!entry.obrigatorio && (
                            <button type="button" className="danger-outline" onClick={() => remove(entry)} disabled={savingId === entry.id}>
                              Excluir
                            </button>
                          )}
                        </div>
                      </form>
                    )}
                  </article>
                );
              })}
              {!busy && !entries.length && <div className="empty">Nenhuma entrada cadastrada ainda. Clique em "+ Nova entrada" para começar.</div>}
            </section>
          </>
        )}
      </div>
    </>
  );
}
