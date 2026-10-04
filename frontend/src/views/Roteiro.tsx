import { useEffect, useState } from 'react';
import type { Api } from '../api';
import type { Area, Company, Question, Paginated, Variavel, VariavelRoteiro } from '../types';
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
function destacarTexto(text: string, variaveisRoteiro: VariavelRoteiro[] = []): React.ReactNode[] {
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
      const custom = variaveisRoteiro.find((v) => v.slug === name && !v.builtin);
      if (custom) {
        parts.push(
          <span
            key={key++}
            className="token-tag"
            style={{ background: `${custom.cor}22`, borderColor: custom.cor, color: custom.cor }}
            title={`Variável de roteiro: ${custom.name}`}
          >
            {token}
          </span>,
        );
      } else {
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
    }
    lastIndex = index + token.length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts;
}

function Legenda({ areas, variaveis, variaveisRoteiro }: { areas: Area[]; variaveis: Variavel[]; variaveisRoteiro: VariavelRoteiro[] }) {
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
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
        <small style={{ fontWeight: 600 }}>Variáveis de roteiro:</small>
        {variaveisRoteiro.map((v) => (
          <span key={v.id} className="tag-pill" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span aria-hidden style={{ width: 10, height: 10, borderRadius: '50%', background: v.cor, display: 'inline-block' }} />
            {'{'}
            {v.slug}
            {'}'} · {v.name}
            {v.builtin && <small style={{ color: 'var(--muted)' }}> (fixa)</small>}
          </span>
        ))}
        {!variaveisRoteiro.length && <small style={{ color: 'var(--muted)' }}>Nenhuma variável de roteiro cadastrada ainda.</small>}
      </div>
    </section>
  );
}

// Textarea com preview colorido ao vivo embaixo -- é aqui que o pedido de "marcador
// e cor da variável para confirmação visual" se aplica de fato: o admin vê o token
// {slug} destacado na cor da variável enquanto ainda está digitando, antes de salvar.
function TextoComPreview({ value, rows, onSave, variaveisRoteiro, disabled }: { value: string; rows: number; onSave: (v: string) => void; variaveisRoteiro: VariavelRoteiro[]; disabled?: boolean }) {
  const [draft, setDraft] = useState(value);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <textarea
        value={draft}
        rows={rows}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          if (draft !== value) onSave(draft);
        }}
      />
      {draft && (
        <p style={{ fontSize: 13, color: 'var(--muted)', margin: 0 }}>
          Pré-visualização: “{destacarTexto(draft, variaveisRoteiro)}”
        </p>
      )}
    </div>
  );
}

export function Roteiro({ api, company, canEdit }: { api: Api; company: Company; canEdit: boolean }) {
  const [tab, setTab] = useState<'perguntas' | 'fora-do-fluxo' | 'variaveis' | 'opcoes-agente'>('perguntas');
  const [conversacional, setConversacional] = useState(company.agente_conversacional);
  const [savingOpcoes, setSavingOpcoes] = useState(false);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [variaveis, setVariaveis] = useState<Variavel[]>([]);
  const [variaveisRoteiro, setVariaveisRoteiro] = useState<VariavelRoteiro[]>([]);
  const [areas, setAreas] = useState<Area[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [savingQ, setSavingQ] = useState<number | 'new' | null>(null);
  const [savingV, setSavingV] = useState<number | 'new' | null>(null);
  const [savingVR, setSavingVR] = useState<number | 'new' | null>(null);
  const [newQ, setNewQ] = useState({ question_id: '', text: '', variavel: '' });
  const [newV, setNewV] = useState({ name: '', peso: '5' });
  const [newVR, setNewVR] = useState('');
  const [dragId, setDragId] = useState<number | null>(null);
  const [vrCheckboxOverride, setVrCheckboxOverride] = useState<Record<number, boolean>>({});

  const isOffflow = (q: Question) => (OFFFLOW_IDS as readonly string[]).includes(q.question_id);
  const flowQuestions = questions.filter((q) => !isOffflow(q));
  const offflowQuestions = questions.filter(isOffflow);

  function load() {
    setBusy(true);
    setError('');
    Promise.all([
      api(`/questions/?company=${company.id}`),
      api(`/variaveis/?company=${company.id}`),
      api(`/variaveis-roteiro/?company=${company.id}`),
      api(`/areas/?company=${company.id}`),
    ])
      .then(
        ([q, v, vr, a]: [
          Paginated<Question> | Question[],
          Paginated<Variavel> | Variavel[],
          Paginated<VariavelRoteiro> | VariavelRoteiro[],
          Paginated<Area> | Area[],
        ]) => {
          setQuestions(Array.isArray(q) ? q : q.results);
          setVariaveis(Array.isArray(v) ? v : v.results);
          setVariaveisRoteiro(Array.isArray(vr) ? vr : vr.results);
          setAreas(Array.isArray(a) ? a : a.results);
        },
      )
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }

  useEffect(() => {
    load();
    setConversacional(company.agente_conversacional);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [company.id]);

  async function salvarConversacional(valor: boolean) {
    setSavingOpcoes(true);
    setError('');
    try {
      await api(`/companies/${company.id}/`, { method: 'PATCH', body: JSON.stringify({ agente_conversacional: valor }) });
      setConversacional(valor);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingOpcoes(false);
    }
  }

  async function saveQuestion(q: Question, patch: Partial<Pick<Question, 'text' | 'variavel' | 'question_id' | 'ordem' | 'variavel_roteiro'>>) {
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

  async function createVariavelRoteiro(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!newVR.trim()) return;
    setSavingVR('new');
    setError('');
    try {
      const created = await api(`/variaveis-roteiro/?company=${company.id}`, { method: 'POST', body: JSON.stringify({ name: newVR.trim() }) });
      setVariaveisRoteiro((v) => [...v, created].sort((a, b) => a.name.localeCompare(b.name)));
      setNewVR('');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingVR(null);
    }
  }

  async function removeVariavelRoteiro(variavel: VariavelRoteiro) {
    if (!window.confirm(`Remover a variável de roteiro "${variavel.name}"?`)) return;
    setSavingVR(variavel.id);
    setError('');
    try {
      await api(`/variaveis-roteiro/${variavel.id}/?company=${company.id}`, { method: 'DELETE' });
      setVariaveisRoteiro((v) => v.filter((x) => x.id !== variavel.id));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingVR(null);
    }
  }

  // Checkbox "armazenar resposta numa variável de roteiro" numa pergunta adicional:
  // acha uma variável de roteiro já existente com esse nome ou cria uma nova, depois
  // liga/desliga a pergunta a ela (name=null desmarca o checkbox).
  async function setVariavelRoteiroDaPergunta(q: Question, name: string | null) {
    setSavingQ(q.id);
    setError('');
    try {
      let variavelRoteiroId: number | null = null;
      if (name) {
        const existente = variaveisRoteiro.find((v) => v.name.toLowerCase() === name.toLowerCase());
        if (existente) {
          variavelRoteiroId = existente.id;
        } else {
          const criada = await api(`/variaveis-roteiro/?company=${company.id}`, { method: 'POST', body: JSON.stringify({ name }) });
          setVariaveisRoteiro((v) => [...v, criada].sort((a, b) => a.name.localeCompare(b.name)));
          variavelRoteiroId = criada.id;
        }
      }
      const updated = await api(`/questions/${q.id}/?company=${company.id}`, { method: 'PATCH', body: JSON.stringify({ variavel_roteiro: variavelRoteiroId }) });
      setQuestions((v) => v.map((x) => (x.id === updated.id ? updated : x)));
      setVrCheckboxOverride((v) => {
        const next = { ...v };
        delete next[q.id];
        return next;
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingQ(null);
    }
  }

  return (
    <>
      <header className="page-header">
        <div>
          <small className="eyebrow">Configuração</small>
          <h1>Roteiro aprovado</h1>
          <p>
            O agente Axioma decide a próxima pergunta e a classificação sozinho; aqui você define o texto de cada pergunta,
            a variável do agente (com peso) que ela alimenta na classificação de urgência e, opcionalmente, uma variável de
            roteiro pra reusar a resposta em outro texto. {canEdit ? 'Você edita este conteúdo.' : 'Somente a empresa edita.'}
          </p>
        </div>
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <Legenda areas={areas} variaveis={variaveis} variaveisRoteiro={variaveisRoteiro} />

      <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap' }}>
        <button type="button" className={tab === 'perguntas' ? '' : 'secondary'} onClick={() => setTab('perguntas')}>
          Perguntas do roteiro
        </button>
        <button type="button" className={tab === 'fora-do-fluxo' ? '' : 'secondary'} onClick={() => setTab('fora-do-fluxo')}>
          Textos fora do fluxo
        </button>
        <button type="button" className={tab === 'variaveis' ? '' : 'secondary'} onClick={() => setTab('variaveis')}>
          Variáveis
        </button>
        <button type="button" className={tab === 'opcoes-agente' ? '' : 'secondary'} onClick={() => setTab('opcoes-agente')}>
          Opções do Agente
        </button>
      </div>

      {busy && !questions.length && !variaveis.length && <SkeletonCards count={4} height={92} />}

      {tab === 'perguntas' && (
        <section className="section">
          {canEdit && flowQuestions.length > 1 && (
            <p style={{ fontSize: 12.5, color: 'var(--muted)', marginBottom: 4 }}>Arraste os cartões pelo ⠿ para reordenar o fluxo.</p>
          )}
          {/* Container único com as etapas numeradas: deixa claro a ordem real do fluxo
              e dá uma faixa maior (o número) pra soltar o card, sem depender só do ⠿. */}
          <div className="step-list">
          {flowQuestions.map((q, index) => (
            <article
              key={q.id}
              className="step-card"
              onDragOver={(e) => canEdit && e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                if (dragId != null) reorder(dragId, q.id);
                setDragId(null);
              }}
              style={{ opacity: dragId === q.id ? 0.5 : 1 }}
            >
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginBottom: 10 }}>
                {canEdit && (
                  // Só o "pegador" é draggable (não o card inteiro): o card tem textarea/select por
                  // dentro, e arrastar a partir deles nunca inicia o drag nativo do navegador --
                  // precisa de uma área não-interativa dedicada pra isso funcionar de verdade.
                  // setData é obrigatório pro Firefox considerar o drag válido (Chrome tolera sem,
                  // mas sem isso o drag simplesmente não inicia lá).
                  <span
                    aria-hidden
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.effectAllowed = 'move';
                      e.dataTransfer.setData('text/plain', String(q.id));
                      setDragId(q.id);
                    }}
                    onDragEnd={() => setDragId(null)}
                    className="step-handle"
                    title="Arraste para reordenar"
                  >
                    <span className="step-number">{index + 1}</span>
                    <span aria-hidden>⠿</span>
                  </span>
                )}
                <span className="step-tag">{MANDATORY_LABELS[q.question_id] || q.question_id}</span>
                {q.obrigatoria && <span className="chip chip-neutral">obrigatória</span>}
                {q.audio_asset && <span className="chip chip-neutral">áudio: {q.audio_asset}</span>}
              </div>
              {canEdit ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <label style={{ margin: 0 }}>
                    Texto
                    <TextoComPreview
                      value={q.text}
                      rows={2}
                      disabled={savingQ === q.id}
                      variaveisRoteiro={variaveisRoteiro}
                      onSave={(text) => saveQuestion(q, { text })}
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
                  {q.obrigatoria ? (
                    <small style={{ color: 'var(--muted)' }}>
                      Variável de roteiro fixa: <strong>{variaveisRoteiro.find((v) => v.id === q.variavel_roteiro)?.name || '—'}</strong>
                    </small>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      <label style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8, fontWeight: 400 }}>
                        <input
                          type="checkbox"
                          style={{ width: 'auto' }}
                          checked={vrCheckboxOverride[q.id] ?? !!q.variavel_roteiro}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setVrCheckboxOverride((v) => ({ ...v, [q.id]: true }));
                            } else {
                              setVrCheckboxOverride((v) => ({ ...v, [q.id]: false }));
                              setVariavelRoteiroDaPergunta(q, null);
                            }
                          }}
                          disabled={savingQ === q.id}
                        />
                        Armazenar resposta em uma variável de roteiro
                      </label>
                      {(vrCheckboxOverride[q.id] ?? !!q.variavel_roteiro) && (
                        <input
                          placeholder="Nome da variável (ex.: Idade)"
                          defaultValue={variaveisRoteiro.find((v) => v.id === q.variavel_roteiro)?.name || ''}
                          disabled={savingQ === q.id}
                          onBlur={(e) => {
                            const name = e.target.value.trim();
                            if (name) setVariavelRoteiroDaPergunta(q, name);
                            else setVrCheckboxOverride((v) => ({ ...v, [q.id]: false }));
                          }}
                        />
                      )}
                    </div>
                  )}
                  {!q.obrigatoria && (
                    <button type="button" className="danger-outline" onClick={() => removeQuestion(q)} disabled={savingQ === q.id} style={{ alignSelf: 'flex-start' }}>
                      {savingQ === q.id && <Spinner />}
                      Remover
                    </button>
                  )}
                </div>
              ) : (
                <p style={{ color: 'var(--ink)', fontSize: 15 }}>“{q.text ? destacarTexto(q.text, variaveisRoteiro) : 'Sem texto cadastrado'}”</p>
              )}
            </article>
          ))}
          </div>
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
                  <TextoComPreview value={q.text} rows={2} disabled={savingQ === q.id} variaveisRoteiro={variaveisRoteiro} onSave={(text) => saveQuestion(q, { text })} />
                ) : (
                  <p style={{ color: 'var(--ink)', fontSize: 15 }}>“{q.text ? destacarTexto(q.text, variaveisRoteiro) : 'Sem texto cadastrado'}”</p>
                )}
              </article>
            );
          })}
        </section>
      )}

      {tab === 'variaveis' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 20 }}>
          <section className="section">
            <h3 style={{ marginTop: 0 }}>Variáveis do agente</h3>
            <p style={{ marginBottom: 16, fontSize: 13.5 }}>
              Cada pergunta do roteiro fica atrelada a uma destas, com peso de 1 a 10. O agente calcula a média ponderada
              dos pesos respondidos e sugere a urgência do lead a partir dela.
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
                      style={{ width: 140 }}
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
              <form onSubmit={createVariavel} style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                <label style={{ margin: 0, flex: '1 1 160px' }}>
                  Nova variável
                  <input placeholder="ex.: Urgência relatada" value={newV.name} onChange={(e) => setNewV((v) => ({ ...v, name: e.target.value }))} required />
                </label>
                <label style={{ margin: 0, width: 120 }}>
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

          <section className="section">
            <h3 style={{ marginTop: 0 }}>Variáveis de roteiro</h3>
            <p style={{ marginBottom: 16, fontSize: 13.5 }}>
              Sem peso — só guardam o texto coletado numa pergunta pra reusar como placeholder ({'{slug}'}) em outro texto
              do roteiro, se quem escreve o fluxo quiser. Nome/Área da Lead/Demanda são fixas em toda empresa.
            </p>
            {variaveisRoteiro.map((v) => (
              <article key={v.id} className="step-card" style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                <span aria-hidden style={{ width: 14, height: 14, borderRadius: '50%', background: v.cor, flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <strong>{v.name}</strong>
                  <small style={{ display: 'block', color: 'var(--muted)', fontFamily: "'DM Mono',monospace" }}>{'{' + v.slug + '}'}</small>
                </div>
                {v.builtin ? (
                  <span className="chip chip-neutral">fixa</span>
                ) : (
                  canEdit && (
                    <button type="button" className="danger-outline" onClick={() => removeVariavelRoteiro(v)} disabled={savingVR === v.id}>
                      {savingVR === v.id && <Spinner />}
                      Remover
                    </button>
                  )
                )}
              </article>
            ))}
            {!busy && !variaveisRoteiro.length && <div className="empty">Nenhuma variável de roteiro cadastrada ainda.</div>}

            {canEdit && (
              <form onSubmit={createVariavelRoteiro} style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'flex-end' }}>
                <label style={{ margin: 0, flex: 1 }}>
                  Nova variável de roteiro
                  <input placeholder="ex.: Idade" value={newVR} onChange={(e) => setNewVR(e.target.value)} required />
                </label>
                <button disabled={savingVR === 'new'}>
                  {savingVR === 'new' && <Spinner />}+ Adicionar
                </button>
              </form>
            )}
          </section>
        </div>
      )}

      {tab === 'opcoes-agente' && (
        <section className="section">
          <article className="step-card" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <label style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 10, fontWeight: 600 }}>
              <input
                type="checkbox"
                style={{ width: 'auto' }}
                checked={conversacional}
                disabled={!canEdit || savingOpcoes}
                onChange={(e) => salvarConversacional(e.target.checked)}
              />
              Agente conversacional?
            </label>
            {conversacional ? (
              <p style={{ fontSize: 13.5, color: 'var(--muted)', margin: 0 }}>
                <strong>Marcado:</strong> o agente envia o texto de "Texto de apresentação" (aba "Textos fora do fluxo") e
                pode conversar livremente sobre a empresa — respondendo com base em "Dados da empresa" — enquanto aguarda
                o lead entrar no funil de triagem.
              </p>
            ) : (
              <p style={{ fontSize: 13.5, color: 'var(--muted)', margin: 0 }}>
                <strong>Desmarcado:</strong> o agente vai direto para o funil de triagem. Escreva, no "Texto de
                apresentação" (aba "Textos fora do fluxo"), um texto inicial explicativo que peça para o lead responder
                qualquer coisa confirmando que está pronto para seguir — sem conversa livre sobre a empresa nesse
                meio-tempo.
              </p>
            )}
            {savingOpcoes && <Spinner />}
          </article>
        </section>
      )}
    </>
  );
}
