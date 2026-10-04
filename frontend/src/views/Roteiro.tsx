import { useEffect, useState } from 'react';
import type { Api } from '../api';
import type { Area, Company, Question, Paginated, Variavel } from '../types';
import { SkeletonCards, Spinner } from '../components/Skeleton';

const PLACEHOLDER_LABELS: Record<string, string> = {
  empresa: 'Nome da empresa',
  nome: 'Nome do lead',
  especialidade: 'Área/especialidade classificada',
  tema: 'Resumo da demanda',
  impacto: 'Impacto relatado',
  interesse: 'Interesse em seguir',
  temperatura: 'Classificação comercial',
  prioridade: 'Prioridade de atendimento',
};

const MANDATORY_LABELS: Record<string, string> = {
  nome: 'Nome completo',
  situacao: 'Situação (área)',
  demanda: 'Demanda',
};

// Fora do fluxo de triagem: o cliente vê "apresentacao" antes de entrar em qualquer
// etapa, "empresa" é o fallback usado enquanto ele ainda não entrou no fluxo (só
// vendo o que o agente responde sobre a empresa), e "validar"/"encerramento" fecham
// a triagem. Nenhum dos 4 é classificável, então não tem Variável (ver backend).
const OFFFLOW_IDS = ['apresentacao', 'empresa', 'validar', 'encerramento'] as const;
const OFFFLOW_LABELS: Record<string, { title: string; help: string }> = {
  apresentacao: { title: 'Texto de apresentação', help: 'Primeira mensagem enviada quando o cliente entra em contato.' },
  empresa: { title: 'Resposta sobre a empresa', help: 'Usado enquanto o cliente ainda não entrou no fluxo de perguntas — só o que o agente responde sobre a empresa.' },
  validar: { title: 'Confirmação dos dados', help: 'Resumo enviado para o cliente confirmar antes de encerrar a triagem.' },
  encerramento: { title: 'Encerramento', help: 'Mensagem final, enviada quando a triagem é concluída e classificada.' },
};

const TOKEN_RE = /(<br\s*\/?>)|(\{[a-zA-Z_]+\})/g;

// Quem edita o roteiro (na tela ou direto no Django Admin) não precisa saber HTML
// nem a sintaxe de placeholder de cor: {empresa}/{nome}/etc. e <br> ficam marcados
// com cor e borda, igual a legenda logo abaixo, pra reconhecer de relance.
function destacarTexto(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;
  for (const match of text.matchAll(TOKEN_RE)) {
    const index = match.index ?? 0;
    if (index > lastIndex) parts.push(text.slice(lastIndex, index));
    const token = match[0];
    if (token.startsWith('<')) {
      parts.push(
        <span key={key++} className="token-tag token-tag-html" title="Tag HTML — controla a formatação da mensagem">
          {token}
        </span>,
      );
    } else {
      const name = token.slice(1, -1);
      const isEmpresa = name === 'empresa';
      parts.push(
        <span
          key={key++}
          className={`token-tag ${isEmpresa ? 'token-tag-empresa' : 'token-tag-dado'}`}
          title={PLACEHOLDER_LABELS[name] || 'Placeholder preenchido automaticamente'}
        >
          {token}
        </span>,
      );
    }
    lastIndex = index + token.length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts;
}

function Legenda({ areas, variaveis }: { areas: Area[]; variaveis: Variavel[] }) {
  return (
    <section className="panel" style={{ padding: '16px 24px', marginBottom: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '14px 28px', alignItems: 'center' }}>
        <strong style={{ fontSize: 13 }}>Legenda:</strong>
        <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
          <span className="token-tag token-tag-empresa">{'{empresa}'}</span> nome da empresa
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
          <span className="token-tag token-tag-dado">{'{nome}'}</span> dado já coletado do lead
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
          <span className="token-tag token-tag-html">{'<br>'}</span> quebra de linha (HTML)
        </span>
      </div>
      <small style={{ color: 'var(--muted)' }}>Esses marcadores são resolvidos automaticamente pelo CRM antes de enviar — nunca edite o texto dentro das chaves.</small>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
        <small style={{ fontWeight: 600 }}>Áreas de atendimento:</small>
        {areas.map((a) => (
          <span key={a.id} className="tag-pill">
            {a.name}
          </span>
        ))}
        {!areas.length && <small style={{ color: 'var(--muted)' }}>Nenhuma área cadastrada ainda (tela Equipe).</small>}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
        <small style={{ fontWeight: 600 }}>Variáveis do agente:</small>
        {variaveis.map((v) => (
          <span key={v.id} className="tag-pill">
            {v.name} · peso {v.peso}
          </span>
        ))}
        {!variaveis.length && <small style={{ color: 'var(--muted)' }}>Nenhuma variável cadastrada ainda.</small>}
      </div>
    </section>
  );
}

export function Roteiro({ api, company, canEdit }: { api: Api; company: Company; canEdit: boolean }) {
  const [tab, setTab] = useState<'perguntas' | 'fora-do-fluxo' | 'variaveis'>('perguntas');
  const [questions, setQuestions] = useState<Question[]>([]);
  const [variaveis, setVariaveis] = useState<Variavel[]>([]);
  const [areas, setAreas] = useState<Area[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [savingQ, setSavingQ] = useState<number | 'new' | null>(null);
  const [savingV, setSavingV] = useState<number | 'new' | null>(null);
  const [newQ, setNewQ] = useState({ question_id: '', text: '', variavel: '' });
  const [newV, setNewV] = useState({ name: '', peso: '5' });
  const [dragId, setDragId] = useState<number | null>(null);

  const isOffflow = (q: Question) => (OFFFLOW_IDS as readonly string[]).includes(q.question_id);
  const flowQuestions = questions.filter((q) => !isOffflow(q));
  const offflowQuestions = questions.filter(isOffflow);

  function load() {
    setBusy(true);
    setError('');
    Promise.all([
      api(`/questions/?company=${company.id}`),
      api(`/variaveis/?company=${company.id}`),
      api(`/areas/?company=${company.id}`),
    ])
      .then(([q, v, a]: [Paginated<Question> | Question[], Paginated<Variavel> | Variavel[], Paginated<Area> | Area[]]) => {
        setQuestions(Array.isArray(q) ? q : q.results);
        setVariaveis(Array.isArray(v) ? v : v.results);
        setAreas(Array.isArray(a) ? a : a.results);
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [company.id]);

  async function saveQuestion(q: Question, patch: Partial<Pick<Question, 'text' | 'variavel' | 'question_id'>>) {
    setSavingQ(q.id);
    setError('');
    try {
      const updated = await api(`/questions/${q.id}/?company=${company.id}`, { method: 'PATCH', body: JSON.stringify(patch) });
      setQuestions((v) => v.map((x) => (x.id === updated.id ? updated : x)));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingQ(null);
    }
  }

  async function reorder(sourceId: number, targetId: number) {
    if (sourceId === targetId) return;
    const current = flowQuestions;
    const sourceIndex = current.findIndex((q) => q.id === sourceId);
    const targetIndex = current.findIndex((q) => q.id === targetId);
    if (sourceIndex === -1 || targetIndex === -1) return;
    const reordered = [...current];
    const [moved] = reordered.splice(sourceIndex, 1);
    reordered.splice(targetIndex, 0, moved);
    const withOrdem = reordered.map((q, i) => ({ ...q, ordem: i }));
    setQuestions((v) => v.map((q) => withOrdem.find((w) => w.id === q.id) || q));
    try {
      await Promise.all(
        withOrdem.map((q) => api(`/questions/${q.id}/?company=${company.id}`, { method: 'PATCH', body: JSON.stringify({ ordem: q.ordem }) })),
      );
    } catch (err) {
      setError((err as Error).message);
      load();
    }
  }

  async function createQuestion(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!newQ.question_id.trim() || !newQ.variavel) return;
    setSavingQ('new');
    setError('');
    try {
      const created = await api(`/questions/?company=${company.id}`, {
        method: 'POST',
        body: JSON.stringify({ question_id: newQ.question_id.trim(), text: newQ.text, variavel: Number(newQ.variavel) }),
      });
      setQuestions((v) => [...v, created]);
      setNewQ({ question_id: '', text: '', variavel: '' });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingQ(null);
    }
  }

  async function removeQuestion(q: Question) {
    if (!window.confirm(`Remover a pergunta "${q.question_id}"? As respostas já coletadas de leads continuam no histórico.`)) return;
    setSavingQ(q.id);
    setError('');
    try {
      await api(`/questions/${q.id}/?company=${company.id}`, { method: 'DELETE' });
      setQuestions((v) => v.filter((x) => x.id !== q.id));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingQ(null);
    }
  }

  async function createVariavel(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!newV.name.trim()) return;
    setSavingV('new');
    setError('');
    try {
      const created = await api(`/variaveis/?company=${company.id}`, {
        method: 'POST',
        body: JSON.stringify({ name: newV.name.trim(), peso: Number(newV.peso) }),
      });
      setVariaveis((v) => [...v, created].sort((a, b) => a.name.localeCompare(b.name)));
      setNewV({ name: '', peso: '5' });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingV(null);
    }
  }

  async function saveVariavel(variavel: Variavel, patch: Partial<Pick<Variavel, 'name' | 'peso'>>) {
    setSavingV(variavel.id);
    setError('');
    try {
      const updated = await api(`/variaveis/${variavel.id}/?company=${company.id}`, { method: 'PATCH', body: JSON.stringify(patch) });
      setVariaveis((v) => v.map((x) => (x.id === updated.id ? updated : x)));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingV(null);
    }
  }

  async function removeVariavel(variavel: Variavel) {
    if (!window.confirm(`Remover a variável "${variavel.name}"?`)) return;
    setSavingV(variavel.id);
    setError('');
    try {
      await api(`/variaveis/${variavel.id}/?company=${company.id}`, { method: 'DELETE' });
      setVariaveis((v) => v.filter((x) => x.id !== variavel.id));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingV(null);
    }
  }

  return (
    <>
      <header className="page-header">
        <div>
          <small className="eyebrow">Configuração</small>
          <h1>Roteiro aprovado</h1>
          <p>
            O agente Axioma decide a próxima pergunta e a classificação sozinho; aqui você define o texto de cada pergunta
            e a variável (com peso) que ela alimenta na classificação de urgência. {canEdit ? 'Você edita este conteúdo.' : 'Somente a empresa edita.'}
          </p>
        </div>
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <Legenda areas={areas} variaveis={variaveis} />

      <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap' }}>
        <button type="button" className={tab === 'perguntas' ? '' : 'secondary'} onClick={() => setTab('perguntas')}>
          Perguntas do roteiro
        </button>
        <button type="button" className={tab === 'fora-do-fluxo' ? '' : 'secondary'} onClick={() => setTab('fora-do-fluxo')}>
          Textos fora do fluxo
        </button>
        <button type="button" className={tab === 'variaveis' ? '' : 'secondary'} onClick={() => setTab('variaveis')}>
          Variáveis do agente
        </button>
      </div>

      {busy && !questions.length && !variaveis.length && <SkeletonCards count={4} height={92} />}

      {tab === 'perguntas' && (
        <section className="section">
          {canEdit && flowQuestions.length > 1 && (
            <p style={{ fontSize: 12.5, color: 'var(--muted)', marginBottom: 4 }}>Arraste os cartões pelo ⠿ para reordenar o fluxo.</p>
          )}
          {flowQuestions.map((q) => (
            <article
              key={q.id}
              className="step-card"
              draggable={canEdit}
              onDragStart={() => setDragId(q.id)}
              onDragOver={(e) => canEdit && e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                if (dragId != null) reorder(dragId, q.id);
                setDragId(null);
              }}
              style={{ opacity: dragId === q.id ? 0.5 : 1, cursor: canEdit ? 'grab' : undefined }}
            >
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginBottom: 10 }}>
                {canEdit && <span aria-hidden style={{ color: 'var(--muted)', cursor: 'grab' }}>⠿</span>}
                <span className="step-tag">{MANDATORY_LABELS[q.question_id] || q.question_id}</span>
                {q.obrigatoria && <span className="chip chip-neutral">obrigatória</span>}
                {q.audio_asset && <span className="chip chip-neutral">áudio: {q.audio_asset}</span>}
              </div>
              {canEdit ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <label style={{ margin: 0 }}>
                    Texto
                    <textarea
                      defaultValue={q.text}
                      rows={2}
                      onBlur={(e) => {
                        if (e.target.value !== q.text) saveQuestion(q, { text: e.target.value });
                      }}
                    />
                  </label>
                  <label style={{ margin: 0 }}>
                    Variável
                    <select
                      defaultValue={q.variavel}
                      onChange={(e) => saveQuestion(q, { variavel: Number(e.target.value) })}
                      disabled={savingQ === q.id}
                    >
                      {variaveis.map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.name} (peso {v.peso})
                        </option>
                      ))}
                    </select>
                  </label>
                  {!q.obrigatoria && (
                    <button type="button" className="danger-outline" onClick={() => removeQuestion(q)} disabled={savingQ === q.id} style={{ alignSelf: 'flex-start' }}>
                      {savingQ === q.id && <Spinner />}
                      Remover
                    </button>
                  )}
                </div>
              ) : (
                <p style={{ color: 'var(--ink)', fontSize: 15 }}>“{q.text ? destacarTexto(q.text) : 'Sem texto cadastrado'}”</p>
              )}
            </article>
          ))}
          {!busy && !flowQuestions.length && <div className="empty">Nenhuma pergunta cadastrada para esta empresa ainda.</div>}

          {canEdit && (
            <form onSubmit={createQuestion} className="step-card" style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 10 }}>
              <strong style={{ fontSize: 14 }}>Nova pergunta</strong>
              <small style={{ color: 'var(--muted)' }}>
                Perguntas além das 3 obrigatórias (nome, situação, demanda) entram no campo de observação do lead.
              </small>
              <label style={{ margin: 0 }}>
                Identificador (question_id)
                <input
                  placeholder="ex.: equipe_avaliar_situacao"
                  value={newQ.question_id}
                  onChange={(e) => setNewQ((v) => ({ ...v, question_id: e.target.value }))}
                  required
                />
              </label>
              <label style={{ margin: 0 }}>
                Texto
                <textarea rows={2} value={newQ.text} onChange={(e) => setNewQ((v) => ({ ...v, text: e.target.value }))} />
              </label>
              <label style={{ margin: 0 }}>
                Variável
                <select value={newQ.variavel} onChange={(e) => setNewQ((v) => ({ ...v, variavel: e.target.value }))} required>
                  <option value="" disabled>
                    Selecione uma variável…
                  </option>
                  {variaveis.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name} (peso {v.peso})
                    </option>
                  ))}
                </select>
              </label>
              {!variaveis.length && (
                <small style={{ color: 'var(--warn)' }}>Cadastre uma variável na aba "Variáveis do agente" antes de criar uma pergunta nova.</small>
              )}
              <button disabled={savingQ === 'new' || !variaveis.length} style={{ alignSelf: 'flex-start' }}>
                {savingQ === 'new' && <Spinner />}+ Adicionar pergunta
              </button>
            </form>
          )}
        </section>
      )}

      {tab === 'fora-do-fluxo' && (
        <section className="section">
          <p style={{ marginBottom: 16 }}>
            Enquanto o cliente ainda não está no fluxo de perguntas, ele só vê o que o agente responde com base nestes
            4 textos — nenhum deles entra na classificação de urgência, por isso não têm variável.
          </p>
          {OFFFLOW_IDS.map((id) => {
            const q = offflowQuestions.find((x) => x.question_id === id);
            const label = OFFFLOW_LABELS[id];
            return (
              <article key={id} className="step-card">
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginBottom: 6 }}>
                  <span className="step-tag">{label.title}</span>
                  <span className="chip chip-neutral">obrigatória</span>
                </div>
                <small style={{ display: 'block', color: 'var(--muted)', marginBottom: 10 }}>{label.help}</small>
                {!q ? (
                  <p style={{ fontSize: 13, color: 'var(--warn)' }}>Carregando…</p>
                ) : canEdit ? (
                  <textarea
                    defaultValue={q.text}
                    rows={2}
                    onBlur={(e) => {
                      if (e.target.value !== q.text) saveQuestion(q, { text: e.target.value });
                    }}
                  />
                ) : (
                  <p style={{ color: 'var(--ink)', fontSize: 15 }}>“{q.text ? destacarTexto(q.text) : 'Sem texto cadastrado'}”</p>
                )}
              </article>
            );
          })}
        </section>
      )}

      {tab === 'variaveis' && (
        <section className="section">
          <p style={{ marginBottom: 16 }}>
            Cada pergunta do roteiro fica atrelada a uma destas variáveis, com peso de 1 a 10. O agente calcula a média
            ponderada dos pesos respondidos e sugere a urgência do lead a partir dela.
          </p>
          {variaveis.map((v) => (
            <article key={v.id} className="step-card" style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
              {canEdit ? (
                <>
                  <input
                    defaultValue={v.name}
                    style={{ flex: 1 }}
                    onBlur={(e) => {
                      if (e.target.value.trim() && e.target.value !== v.name) saveVariavel(v, { name: e.target.value.trim() });
                    }}
                  />
                  <select
                    defaultValue={v.peso}
                    onChange={(e) => saveVariavel(v, { peso: Number(e.target.value) })}
                    disabled={savingV === v.id}
                    style={{ width: 160 }}
                  >
                    {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
                      <option key={n} value={n}>
                        Peso {n}
                      </option>
                    ))}
                  </select>
                  <button type="button" className="danger-outline" onClick={() => removeVariavel(v)} disabled={savingV === v.id}>
                    {savingV === v.id && <Spinner />}
                    Remover
                  </button>
                </>
              ) : (
                <>
                  <strong style={{ flex: 1 }}>{v.name}</strong>
                  <span>peso {v.peso}</span>
                </>
              )}
            </article>
          ))}
          {!busy && !variaveis.length && <div className="empty">Nenhuma variável cadastrada ainda.</div>}

          {canEdit && (
            <form onSubmit={createVariavel} style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'flex-end' }}>
              <label style={{ margin: 0, flex: 1 }}>
                Nova variável
                <input placeholder="ex.: Urgência relatada" value={newV.name} onChange={(e) => setNewV((v) => ({ ...v, name: e.target.value }))} required />
              </label>
              <label style={{ margin: 0, width: 140 }}>
                Peso
                <select value={newV.peso} onChange={(e) => setNewV((v) => ({ ...v, peso: e.target.value }))}>
                  {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <button disabled={savingV === 'new'}>
                {savingV === 'new' && <Spinner />}+ Adicionar
              </button>
            </form>
          )}
        </section>
      )}
    </>
  );
}
