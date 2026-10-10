import { useEffect, useState } from 'react';
import type { Api } from '../api';
import type { Area, Company, Question, Paginated, Variavel, VariavelRoteiro } from '../types';
import { SkeletonCards, Spinner } from '../components/Skeleton';
import { AudioDaPergunta } from '../components/AudioDaPergunta';
import { useConfirmar } from '../components/ConfirmDialog';
import { ClassificacoesTab } from '../components/ClassificacoesTab';
import { PalavrasChaveDialog, listaDePalavras } from '../components/PalavrasChaveDialog';

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
// a triagem. "necessidade_humana" confirma o encaminhamento solicitado pelo cliente.
// Esses textos não têm Variável de classificação (ver backend).
const OFFFLOW_IDS = ['apresentacao', 'empresa', 'validar', 'encerramento', 'necessidade_humana', 'lembrete', 'especial_acompanhamento'] as const;
// Obrigatórias que ficam sempre nas perguntas fixas: a área só é conhecida depois delas.
const SEMPRE_FIXAS = ['nome', 'situacao'];
const ETAPAS_SPIN: { value: Question['etapa_spin']; label: string }[] = [
  { value: '', label: 'Sem etapa' },
  { value: 'situacao', label: 'Situação' },
  { value: 'problema', label: 'Problema' },
  { value: 'implicacao', label: 'Implicação' },
  { value: 'necessidade', label: 'Necessidade' },
];
const OFFFLOW_LABELS: Record<string, { title: string; help: string }> = {
  apresentacao: { title: 'Texto de apresentação', help: 'Primeira mensagem enviada quando o cliente entra em contato.' },
  empresa: { title: 'Resposta sobre a empresa', help: 'Usado enquanto o cliente ainda não entrou no fluxo de perguntas — só o que o agente responde sobre a empresa.' },
  validar: { title: 'Confirmação dos dados', help: 'Resumo enviado para o cliente confirmar antes de encerrar a triagem.' },
  encerramento: { title: 'Encerramento', help: 'Mensagem final, enviada quando a triagem é concluída e classificada.' },
  necessidade_humana: { title: 'Necessidade humana', help: 'Mensagem enviada ao cliente caso ele peça atendimento humano' },
  lembrete: { title: 'Lembrete de continuidade', help: 'Enviada ao cliente que ficou 24 horas sem responder; logo depois o agente reenvia a pergunta em que ele parou. Se não houver retorno em mais 24 horas, a triagem é apagada. Funciona também com “Etapa Inicial?” marcada.' },
  especial_acompanhamento: { title: 'Outras situações — acompanhamento de processo', help: 'Resposta enviada ao cliente que já tem processo no escritório e quer acompanhá-lo (o lead vai para “Outras situações”). Em silêncio quando “Etapa Inicial?” está marcada.' },
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
          <span className="token-tag token-tag-html">{'<br>'}</span> quebra de linha
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
  useEffect(() => setDraft(value), [value]);
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

/** Texto como o contato verá, com dados de exemplo no lugar dos marcadores (só para a pré-visualização em conversa). */
function textoDeExemplo(text: string, empresa: string, area?: string): string {
  const exemplos: Record<string, string> = { empresa, nome: 'Maria', tema: 'cobrança indevida no benefício', especialidade: area || 'Previdenciário', impacto: 'ficou sem renda', interesse: 'sim' };
  return text
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/\{([a-zA-Z_]+)\}/g, (_m, k: string) => exemplos[k] ?? `[${k}]`)
    .trim();
}

function resumo(text: string, max = 110): string {
  const limpo = text.replace(/<br\s*\/?>/gi, ' ').replace(/\s+/g, ' ').trim();
  return limpo.length > max ? `${limpo.slice(0, max - 1)}…` : limpo;
}

function Chevron({ aberto }: { aberto: boolean }) {
  return (
    <svg className={`rot-chevron${aberto ? ' aberto' : ''}`} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const COR_VAR = ['#D9531A', '#C88A1E', '#2F7D5C', '#2563EB', '#7C3AED', '#E2574C', '#8C7B69', '#0F8B8D'];

const VOZES_TTS = [
  { id: 'pt-BR-FranciscaNeural', label: 'Francisca (feminina)' },
  { id: 'pt-BR-AntonioNeural', label: 'Antonio (masculina)' },
  { id: 'pt-BR-ThalitaMultilingualNeural', label: 'Thalita (feminina, multilíngue)' },
];

export function Roteiro({ api, company, canEdit, onCompanyChange }: { api: Api; company: Company; canEdit: boolean; onCompanyChange?: (c: Company) => void }) {
  const confirmar = useConfirmar();
  const [tab, setTab] = useState<'perguntas' | 'fora-do-fluxo' | 'variaveis' | 'opcoes-agente' | 'classificacoes'>('perguntas');
  const [conversacional, setConversacional] = useState(company.agente_conversacional);
  const [etapaInicial, setEtapaInicial] = useState(company.etapa_inicial);
  const [spinsIniciais, setSpinsIniciais] = useState<number[]>(company.spins_iniciais ?? (company.spin_inicial ? [company.spin_inicial] : []));
  const [mensagensAudio, setMensagensAudio] = useState(company.mensagens_audio);
  const [voz, setVoz] = useState(company.voz_tts);
  const [erroOpcoes, setErroOpcoes] = useState('');
  const [savingOpcoes, setSavingOpcoes] = useState(false);
  const [palavrasArea, setPalavrasArea] = useState<Area | null>(null);
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
  // Lista de perguntas exibida: 'fixas' ou o id de uma Área (lista da Área).
  const [lista, setLista] = useState<'fixas' | 'fora' | number>('fixas');
  // Cartões em acordeão: um aberto por vez, o resto fica numa linha só (texto resumido + etiquetas).
  const [abertaQ, setAbertaQ] = useState<number | null>(null);
  const [abertaF, setAbertaF] = useState<string | null>(null);
  const [novaAberta, setNovaAberta] = useState(false);
  const [novaVarAberta, setNovaVarAberta] = useState(false);
  const [copiado, setCopiado] = useState('');

  const isOffflow = (q: Question) => (OFFFLOW_IDS as readonly string[]).includes(q.question_id);
  // Ordena por `ordem` (não pela posição no array): o reorder só atualiza o campo, então sem isso
  // a nova ordem era salva no backend mas a tela continuava igual até recarregar.
  // "Fora de escopo" está sempre presente, no fim dos chips: se a empresa já tem uma Área com esse nome, é ela; senão é um chip virtual.
  const ehForaDeEscopo = (a: Area) => a.name.trim().toLowerCase() === 'fora de escopo';
  const areaFora = areas.find(ehForaDeEscopo) ?? null;
  const areasDoFluxo = areas.filter((a) => !ehForaDeEscopo(a));
  const listaFora = lista === 'fora' || (areaFora !== null && lista === areaFora.id);
  const areaDaLista = lista === 'fixas' ? null : lista === 'fora' ? -1 : lista;
  const areaSelecionada = areas.find((a) => a.id === areaDaLista);
  const flowQuestions = questions
    .filter((q) => !isOffflow(q) && (q.area ?? null) === areaDaLista)
    .sort((a, b) => a.ordem - b.ordem || a.id - b.id);
  const offflowQuestions = questions.filter(isOffflow);
  // Detalhamento (do sistema) sempre no topo; as demais seguem a ordem de cadastro.
  const variaveisOrdenadas = [...variaveis].sort((a, b) => Number(!!b.builtin) - Number(!!a.builtin));
  const pesoTotal = variaveis.reduce((t, v) => t + v.peso, 0) || 1;

  function load() {
    setBusy(true);
    setError('');
    Promise.all([
      api(`/questions/?company=${company.id}`),
      api(`/variaveis/?company=${company.id}`),
      api(`/variaveis-roteiro/?company=${company.id}`),
      api(`/areas/?company=${company.id}`),
      api(`/companies/${company.id}/`),
    ])
      .then(
        ([q, v, vr, a, c]: [
          Paginated<Question> | Question[],
          Paginated<Variavel> | Variavel[],
          Paginated<VariavelRoteiro> | VariavelRoteiro[],
          Paginated<Area> | Area[],
          Company,
        ]) => {
          setQuestions(Array.isArray(q) ? q : q.results);
          setVariaveis(Array.isArray(v) ? v : v.results);
          setVariaveisRoteiro(Array.isArray(vr) ? vr : vr.results);
          setAreas(Array.isArray(a) ? a : a.results);
          setConversacional(c.agente_conversacional);
          setEtapaInicial(c.etapa_inicial);
          setSpinsIniciais(c.spins_iniciais ?? (c.spin_inicial ? [c.spin_inicial] : []));
          setMensagensAudio(c.mensagens_audio);
          setVoz(c.voz_tts);
        },
      )
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }

  useEffect(() => {
    load();
    setConversacional(company.agente_conversacional);
    setMensagensAudio(company.mensagens_audio);
    setVoz(company.voz_tts);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [company.id]);

  function atualizarPergunta(nq: Question) {
    setQuestions((v) => v.map((x) => (x.id === nq.id ? nq : x)));
  }

  async function salvarOpcaoAudio(patch: { mensagens_audio?: boolean; voz_tts?: string }) {
    setSavingOpcoes(true);
    setErroOpcoes('');
    try {
      const c = await api(`/companies/${company.id}/`, { method: 'PATCH', body: JSON.stringify(patch) });
      setMensagensAudio(c.mensagens_audio);
      setVoz(c.voz_tts);
    } catch (err) {
      setErroOpcoes((err as Error).message);
    } finally {
      setSavingOpcoes(false);
    }
  }

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

  async function salvarInicioSpin(patch: { etapa_inicial?: boolean; spins_iniciais?: number[] }) {
    setSavingOpcoes(true);
    setError('');
    try {
      const c: Company = await api(`/companies/${company.id}/`, { method: 'PATCH', body: JSON.stringify(patch) });
      setEtapaInicial(c.etapa_inicial);
      setSpinsIniciais(c.spins_iniciais ?? (c.spin_inicial ? [c.spin_inicial] : []));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingOpcoes(false);
    }
  }

  async function salvarPalavrasChave(area: Area, palavras_chave: string): Promise<boolean> {
    setSavingOpcoes(true);
    setError('');
    try {
      const atualizada: Area = await api(`/areas/${area.id}/?company=${company.id}`, { method: 'PATCH', body: JSON.stringify({ palavras_chave }) });
      setAreas((v) => v.map((a) => (a.id === atualizada.id ? atualizada : a)));
      return true;
    } catch (err) {
      setError((err as Error).message);
      return false;
    } finally {
      setSavingOpcoes(false);
    }
  }

  async function saveQuestion(q: Question, patch: Partial<Pick<Question, 'text' | 'habilitada' | 'envio_obrigatorio' | 'horario_envio' | 'variavel' | 'question_id' | 'ordem' | 'variavel_roteiro' | 'variaveis_obrigatorias' | 'area' | 'etapa_spin'>>) {
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
        body: JSON.stringify({
          question_id: newQ.question_id.trim(),
          text: newQ.text,
          variavel: Number(newQ.variavel),
          area: areaDaLista,
          ordem: flowQuestions.length ? Math.max(...flowQuestions.map((q) => q.ordem)) + 1 : 0,
        }),
      });
      setQuestions((v) => [...v, created]);
      setNewQ({ question_id: '', text: '', variavel: '' });
      setNovaAberta(false);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingQ(null);
    }
  }

  async function removeQuestion(q: Question) {
    if (!(await confirmar({ titulo: `Remover a pergunta "${q.question_id}"?`, mensagem: 'As respostas já coletadas de leads continuam no histórico.', tom: 'perigo', icone: 'lixeira', confirmar: 'Remover pergunta' }))) return;
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

  // Move a pergunta para outra lista (fixas ou a Área), entrando no fim dela.
  async function moverParaLista(q: Question, destino: string) {
    const area = destino === 'fixas' ? null : Number(destino);
    const naLista = questions.filter((x) => !isOffflow(x) && (x.area ?? null) === area && x.id !== q.id);
    const ordem = naLista.length ? Math.max(...naLista.map((x) => x.ordem)) + 1 : 0;
    await saveQuestion(q, area === null ? { area: null, etapa_spin: '', ordem } : { area, ordem });
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
    if (!(await confirmar({ titulo: `Remover a variável "${variavel.name}"?`, mensagem: 'Se alguma pergunta do roteiro ainda usa esta variável, a remoção é recusada.', tom: 'perigo', icone: 'lixeira', confirmar: 'Remover variável' }))) return;
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
    if (!(await confirmar({ titulo: `Remover a variável de roteiro "${variavel.name}"?`, mensagem: 'Se uma pergunta ainda usa esta variável de roteiro, a remoção é recusada.', tom: 'perigo', icone: 'lixeira', confirmar: 'Remover variável' }))) return;
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

      <details className="rot-legenda">
        <summary>
          <span>Marcadores e variáveis disponíveis</span>
          <small>{'{empresa}'} · {'{nome}'} · {'<br>'} · áreas e variáveis do roteiro</small>
          <Chevron aberto={false} />
        </summary>
        <Legenda areas={areas} variaveis={variaveis} variaveisRoteiro={variaveisRoteiro} />
      </details>

      <div className="rot-tabs" role="tablist" aria-label="Seções do roteiro">
        {([
          ['perguntas', 'Perguntas do roteiro', questions.filter((q) => !isOffflow(q)).length],
          ['fora-do-fluxo', 'Textos fora do fluxo', null],
          ['variaveis', 'Variáveis', variaveis.length],
          ['opcoes-agente', 'Opções do Agente', null],
          ['classificacoes', 'Classificações', null],
        ] as const).map(([k, nome, n]) => (
          <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? 'ativa' : ''} onClick={() => setTab(k)}>
            {nome}
            {n !== null && <span className="rot-contagem">{n}</span>}
          </button>
        ))}
      </div>

      {busy && !questions.length && !variaveis.length && <SkeletonCards count={4} height={92} />}

      <div key={tab} className="rot-aba">

      {tab === 'perguntas' && (
        <section className={`section rot-grade${listaFora ? ' sem-chat' : ''}`}>
          <div className="rot-lista">
          <div className="spin-seletor" role="tablist" aria-label="Lista de perguntas">
            <button type="button" role="tab" aria-selected={lista === 'fixas'} className={lista === 'fixas' ? '' : 'secondary'} onClick={() => setLista('fixas')}>
              Perguntas fixas <span className="rot-contagem">{questions.filter((q) => !isOffflow(q) && (q.area ?? null) === null).length}</span>
            </button>
            {areasDoFluxo.map((a) => (
              <button type="button" role="tab" key={a.id} aria-selected={lista === a.id} className={lista === a.id ? '' : 'secondary'} onClick={() => setLista(a.id)}>
                {a.name} <span className="rot-contagem">{questions.filter((q) => !isOffflow(q) && q.area === a.id).length}</span>
              </button>
            ))}
            <button type="button" role="tab" aria-selected={listaFora} className={`rot-chip-fora${listaFora ? '' : ' secondary'}`} onClick={() => setLista(areaFora ? areaFora.id : 'fora')}>
              Fora de escopo
            </button>
          </div>
          <p style={{ fontSize: 13, color: 'var(--muted)', margin: '6px 0 10px' }}>
            {listaFora
              ? 'Cliente cujo assunto não é atendido pelo escritório.'
              : areaSelecionada
              ? `Perguntas feitas depois que o agente classifica a área como ${areaSelecionada.name}. Para guardar a demanda desta área, marque "Armazenar resposta" e use "Demanda" na pergunta de Problema.`
              : 'Perguntas feitas antes de o agente definir a área.'}
          </p>
          {listaFora ? (
            <article className="step-card rot-fora">
              <h3>Sempre presente, sem perguntas</h3>
              <p>
                Quando o assunto do cliente não corresponde a nenhuma das áreas, o agente não faz perguntas: o lead é concluído como <strong>Desqualificado</strong>{' '}
                (aparece só nas estatísticas) e o número fica livre para uma nova conversa. Por isso não há roteiro para editar aqui.
              </p>
              <ul>
                <li>Com <strong>Etapa Inicial</strong> e várias áreas, o agente usa as palavras-chave de cada área para reconhecer o assunto; sem correspondência, vale fora de escopo.</li>
                <li>O 4º pedido de repetição seguido na mesma pergunta também desqualifica (sem resposta).</li>
              </ul>
            </article>
          ) : (
            <>
          {canEdit && flowQuestions.length > 1 && (
            <p style={{ fontSize: 12.5, color: 'var(--muted)', marginBottom: 4 }}>Arraste os cartões pelo ⠿ para reordenar o fluxo.</p>
          )}
          {/* Container único com as etapas numeradas: deixa claro a ordem real do fluxo
              e dá uma faixa maior (o número) pra soltar o card, sem depender só do ⠿. */}
          <div className="step-list">
          {flowQuestions.map((q, index) => (
            <article
              key={q.id}
              className={`step-card rot-card${abertaQ === q.id ? ' aberta' : ''}`}
              id={`rot-q-${q.id}`}
              onDragOver={(e) => canEdit && e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                // Lê o id direto do dataTransfer (dado da sessão nativa de drag), não do state
                // dragId por closure -- mais robusto contra qualquer timing entre o re-render do
                // React e o evento nativo do navegador disparar.
                const sourceId = Number(e.dataTransfer.getData('text/plain'));
                if (sourceId) reorder(sourceId, q.id);
                setDragId(null);
              }}
              style={{ opacity: dragId === q.id ? 0.5 : 1 }}
            >
              <div
                className="rot-linha"
                role="button"
                tabIndex={0}
                aria-expanded={abertaQ === q.id}
                onClick={() => setAbertaQ(abertaQ === q.id ? null : q.id)}
                onKeyDown={(e) => {
                  if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
                    e.preventDefault();
                    setAbertaQ(abertaQ === q.id ? null : q.id);
                  }
                }}
              >
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
                    onClick={(e) => e.stopPropagation()}
                  >
                    <span className="step-number">{index + 1}</span>
                    <span aria-hidden>⠿</span>
                  </span>
                )}
                {!canEdit && <span className="step-number">{index + 1}</span>}
                <span className="step-tag">{MANDATORY_LABELS[q.question_id] || q.question_id}</span>
                <span className={`rot-previa${q.text.trim() ? '' : ' vazio'}`}>{q.text.trim() ? resumo(q.text) : 'Sem texto cadastrado'}</span>
                <span className="rot-etiquetas">
                  {q.etapa_spin && <span className="chip chip-neutral">{ETAPAS_SPIN.find((et) => et.value === q.etapa_spin)?.label}</span>}
                  {q.envio_obrigatorio && <span className="chip chip-neutral">envio obrigatório</span>}
                  {q.audio_gravado && <span className="chip chip-neutral">áudio gravado</span>}
                  {variaveis.find((v) => v.id === q.variavel) && <span className="chip chip-neutral">peso {variaveis.find((v) => v.id === q.variavel)?.peso}</span>}
                </span>
                <Chevron aberto={abertaQ === q.id} />
              </div>
              {abertaQ === q.id && (
              <div className="rot-corpo">
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
                  {areaDaLista !== null && (
                    <div>
                      <label style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
                        <input type="checkbox" style={{ width: 'auto' }} checked={q.envio_obrigatorio} disabled={savingQ === q.id || !q.text.trim()} onChange={(e) => saveQuestion(q, { envio_obrigatorio: e.target.checked })} />
                        Pergunta obrigatória (sempre enviar)
                      </label>
                      <small style={{ color: 'var(--muted)' }}>{q.text.trim() ? 'O agente envia esta pergunta antes de classificar, mesmo com nome, demanda e área preenchidos.' : 'Cadastre o texto da pergunta para marcar o envio obrigatório.'}</small>
                    </div>
                  )}
                  {areaDaLista !== null && (
                    <label style={{ margin: 0 }}>
                      Etapa SPIN
                      <select value={q.etapa_spin} onChange={(e) => saveQuestion(q, { etapa_spin: e.target.value as Question['etapa_spin'] })} disabled={savingQ === q.id}>
                        {ETAPAS_SPIN.map((et) => (
                          <option key={et.value} value={et.value}>
                            {et.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  {!SEMPRE_FIXAS.includes(q.question_id) && areasDoFluxo.length > 0 && (
                    <label style={{ margin: 0 }}>
                      Lista
                      <select value={q.area === null || q.area === undefined ? 'fixas' : String(q.area)} onChange={(e) => moverParaLista(q, e.target.value)} disabled={savingQ === q.id}>
                        <option value="fixas">Perguntas fixas</option>
                        {areasDoFluxo.map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <label style={{ margin: 0 }}>
                    Variável
                    <select
                      defaultValue={q.variavel}
                      onChange={(e) => saveQuestion(q, { variavel: Number(e.target.value) })}
                      disabled={savingQ === q.id}
                    >
                      {variaveis.filter((v) => !v.builtin).map((v) => (
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
              {company.allow_transcription && (
                <AudioDaPergunta api={api} companyId={company.id} question={q} canEdit={canEdit} onChange={atualizarPergunta} />
              )}
              </div>
              )}
            </article>
          ))}
          </div>
          {!busy && !flowQuestions.length && <div className="empty">{areaSelecionada ? `Nenhuma pergunta na lista ${areaSelecionada.name} ainda.` : 'Nenhuma pergunta cadastrada para esta empresa ainda.'}</div>}

          {canEdit && !novaAberta && (
            <button type="button" className="rot-adicionar" onClick={() => setNovaAberta(true)}>
              + Nova pergunta {areaSelecionada ? `em ${areaSelecionada.name}` : 'fixa'}
            </button>
          )}
          {canEdit && novaAberta && (
            <form onSubmit={createQuestion} className="step-card rot-nova" style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 10 }}>
              <strong style={{ fontSize: 14 }}>Nova pergunta {areaSelecionada ? `em ${areaSelecionada.name}` : 'fixa'}</strong>
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
              <div style={{ display: 'flex', gap: 10 }}>
                <button disabled={savingQ === 'new' || !variaveis.length}>
                  {savingQ === 'new' && <Spinner />}+ Adicionar pergunta
                </button>
                <button type="button" className="secondary" onClick={() => setNovaAberta(false)}>
                  Cancelar
                </button>
              </div>
            </form>
          )}
            </>
          )}
          </div>

          {!listaFora && (
          <aside className="rot-chat" aria-label="Pré-visualização da conversa">
            <div className="rot-chat-topo">
              <strong>Como o contato vê</strong>
              <small>{areaSelecionada ? areaSelecionada.name : 'Perguntas fixas'} · dados de exemplo</small>
            </div>
            <div className="rot-chat-corpo">
              {flowQuestions.map((q, i) => (
                <button
                  key={q.id}
                  type="button"
                  className={`rot-bolha${abertaQ === q.id ? ' ativa' : ''}${q.text.trim() ? '' : ' vazia'}`}
                  onClick={() => {
                    setAbertaQ(q.id);
                    window.setTimeout(() => document.getElementById(`rot-q-${q.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 60);
                  }}
                >
                  <span className="rot-bolha-n">{i + 1}</span>
                  {q.text.trim() ? textoDeExemplo(q.text, company.name, areaSelecionada?.name) : 'Sem texto cadastrado'}
                </button>
              ))}
              {!flowQuestions.length && <p className="dash-nota">Nenhuma pergunta nesta lista ainda.</p>}
            </div>
            <small className="rot-chat-nota">Clique em uma mensagem para editar a pergunta. {company.mensagens_audio && company.allow_transcription ? 'Com áudio ligado, o contato recebe estas mensagens em voz.' : ''}</small>
          </aside>
          )}
        </section>
      )}

      {tab === 'fora-do-fluxo' && (
        <section className="section">
          <p style={{ marginBottom: 16 }}>
            Mensagens usadas na apresentação, nas respostas sobre a empresa, na conclusão da triagem e nos pedidos de
            atendimento humano. Elas não entram na classificação de urgência.
          </p>
          {etapaInicial && <p style={{ color: 'var(--muted)' }}>Com “Etapa Inicial?” marcada, o agente envia somente as perguntas da SPIN selecionada.</p>}
          {OFFFLOW_IDS.map((id) => {
            const q = offflowQuestions.find((x) => x.question_id === id);
            const label = OFFFLOW_LABELS[id];
            return (
              <article key={id} className={`step-card rot-card${abertaF === id ? ' aberta' : ''}`}>
                <div
                  className="rot-linha"
                  role="button"
                  tabIndex={0}
                  aria-expanded={abertaF === id}
                  onClick={() => setAbertaF(abertaF === id ? null : id)}
                  onKeyDown={(e) => {
                    if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
                      e.preventDefault();
                      setAbertaF(abertaF === id ? null : id);
                    }
                  }}
                >
                  <span className="step-tag">{label.title}</span>
                  <span className={`rot-previa${q?.text.trim() ? '' : ' vazio'}`}>{q?.text.trim() ? resumo(q.text) : 'Sem texto cadastrado'}</span>
                  {q && (
                    <label className="rot-liga" style={{ display: 'flex', alignItems: 'center', gap: 8, margin: 0 }} onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" style={{ width: 'auto' }} checked={q.habilitada && !(etapaInicial && (id === 'necessidade_humana' || id === 'especial_acompanhamento'))} disabled={!canEdit || savingQ === q.id || (etapaInicial && (id === 'necessidade_humana' || id === 'especial_acompanhamento'))} onChange={(e) => saveQuestion(q, { habilitada: e.target.checked })} />
                      Permitir envio pelo agente
                    </label>
                  )}
                  <Chevron aberto={abertaF === id} />
                </div>
                {abertaF === id && (
                <div className="rot-corpo">
                <small style={{ display: 'block', color: 'var(--muted)', marginBottom: 10 }}>{label.help}</small>
                {etapaInicial && id === 'necessidade_humana' && <p style={{ color: 'var(--muted)', fontSize: 13 }}>Pedido de atendimento humano desabilitado durante o início por SPIN. O agente segue a triagem e encaminha a lead após classificá-la.</p>}
                {etapaInicial && id === 'especial_acompanhamento' && <p style={{ color: 'var(--muted)', fontSize: 13 }}>Com “Etapa Inicial?” marcada o agente não responde ao cliente: o lead vai para “Outras situações” em silêncio.</p>}
                {!q ? (
                  <p style={{ fontSize: 13, color: 'var(--warn)' }}>Carregando…</p>
                ) : canEdit ? (
                  <TextoComPreview value={q.text} rows={2} disabled={savingQ === q.id} variaveisRoteiro={variaveisRoteiro} onSave={(text) => saveQuestion(q, { text })} />
                ) : (
                  <p style={{ color: 'var(--ink)', fontSize: 15 }}>“{q.text ? destacarTexto(q.text, variaveisRoteiro) : 'Sem texto cadastrado'}”</p>
                )}
                {q && id === 'lembrete' && (
                  <label style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    Horário exato do envio
                    <input
                      type="time"
                      style={{ width: 140 }}
                      defaultValue={(q.horario_envio || '').slice(0, 5)}
                      disabled={!canEdit || savingQ === q.id}
                      onBlur={(e) => {
                        const valor = e.currentTarget.value;
                        if (valor !== (q.horario_envio || '').slice(0, 5)) saveQuestion(q, { horario_envio: valor || null });
                      }}
                    />
                    <small style={{ color: 'var(--muted)' }}>
                      Depois de 24 horas sem resposta, o lembrete sai neste horário (fuso de Fortaleza). Vazio = assim que completar 24 horas.
                    </small>
                  </label>
                )}
                {q && id === 'necessidade_humana' && (
                  <fieldset disabled={!canEdit || savingQ === q.id || etapaInicial} style={{ marginTop: 14, border: '1px solid var(--line)', borderRadius: 8 }}>
                    <legend>Variáveis mínimas obrigatórias</legend>
                    <small style={{ display: 'block', color: 'var(--muted)', marginBottom: 10 }}>
                      Selecione os dados que o cliente precisa informar antes de ser encaminhado ao humano.
                      O agente envia esta mensagem e coleta os dados faltantes. A transferência só acontece quando todos os selecionados estiverem preenchidos.
                    </small>
                    {variaveisRoteiro.map((v) => (
                      <label key={v.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 400 }}>
                        <input
                          type="checkbox"
                          style={{ width: 'auto' }}
                          checked={q.variaveis_obrigatorias.includes(v.id)}
                          onChange={(e) => {
                            const selected = e.target.checked;
                            saveQuestion(q, {
                              variaveis_obrigatorias: selected ? [...q.variaveis_obrigatorias, v.id] : q.variaveis_obrigatorias.filter((value) => value !== v.id),
                            });
                          }}
                        />
                        {v.name} · {'{'}{v.slug}{'}'}
                      </label>
                    ))}
                  </fieldset>
                )}
                {q && company.allow_transcription && (
                  <AudioDaPergunta api={api} companyId={company.id} question={q} canEdit={canEdit} onChange={atualizarPergunta} />
                )}
                </div>
                )}
              </article>
            );
          })}
        </section>
      )}

      {tab === 'variaveis' && (
        <div className="roteiro-variable-grid var-grade">
          <section className="section">
            <div className="var-topo">
              <div>
                <h3 style={{ marginTop: 0 }}>Variáveis do agente</h3>
                <p style={{ margin: 0, fontSize: 13.5 }}>Cada pergunta alimenta uma variável. O peso (1 a 10) define quanto ela pesa na urgência do lead.</p>
              </div>
            </div>
            {variaveis.length > 0 && (
              <div className="var-influencia" aria-label="Influência de cada variável na classificação">
                <div className="var-barra" role="img" aria-label={variaveisOrdenadas.map((v) => `${v.name} ${Math.round((v.peso / pesoTotal) * 100)}%`).join(', ')}>
                  {variaveisOrdenadas.map((v, i) => (
                    <span key={v.id} style={{ flex: `${v.peso} 1 0`, background: COR_VAR[i % COR_VAR.length] }} title={`${v.name}: ${Math.round((v.peso / pesoTotal) * 100)}%`} />
                  ))}
                </div>
                <small>Influência na classificação: quanto maior o peso, maior a fatia.</small>
              </div>
            )}
            <details className="var-ajuda">
              <summary>Como funciona</summary>
              <p>
                O agente dá a nota (0 a 10) de cada variável <strong>pelo sentido do nome</strong>: ele verifica se o que o nome descreve foi atingido na conversa e
                pontua a partir disso. Por isso use nomes explicativos (“Cliente informou o valor dos descontos” orienta melhor que “Descontos”). O CRM calcula a média ponderada
                dessas notas e define a urgência do lead a partir dela. <strong>Detalhamento</strong> é uma variável
                obrigatória do sistema: o CRM mede o quanto o cliente contou (demanda, observações, impacto e dados extras) e só o peso dela pode ser alterado.
              </p>
            </details>
            <div className="var-lista">
              {variaveisOrdenadas.map((v, i) => {
                const usos = questions.filter((q) => q.variavel === v.id).length;
                const pct = Math.round((v.peso / pesoTotal) * 100);
                return (
                  <article key={v.id} className={`step-card var-card${savingV === v.id ? ' salvando' : ''}`}>
                    <span className="var-cor" style={{ background: COR_VAR[i % COR_VAR.length] }} aria-hidden="true" />
                    <div className="var-nome">
                      {v.builtin || !canEdit ? (
                        <strong>
                          {v.name}
                          {v.builtin && <span className="chip chip-neutral" style={{ marginLeft: 8 }}>obrigatória</span>}
                        </strong>
                      ) : (
                        <input
                          defaultValue={v.name}
                          aria-label={`Nome da variável ${v.name}`}
                          onBlur={(e) => {
                            if (e.target.value.trim() && e.target.value !== v.name) saveVariavel(v, { name: e.target.value.trim() });
                          }}
                        />
                      )}
                      <small>{v.builtin ? 'calculada pelo CRM' : usos ? `usada em ${usos} pergunta${usos === 1 ? '' : 's'}` : 'ainda sem perguntas'} · {pct}% da classificação</small>
                    </div>
                    <div className="var-peso" role="radiogroup" aria-label={`Peso de ${v.name}`}>
                      {Array.from({ length: 10 }, (_, k) => k + 1).map((n) => (
                        <button
                          key={n}
                          type="button"
                          role="radio"
                          aria-checked={v.peso === n}
                          aria-label={`Peso ${n}`}
                          className={n <= v.peso ? 'cheio' : ''}
                          disabled={!canEdit || savingV === v.id}
                          onClick={() => v.peso !== n && saveVariavel(v, { peso: n })}
                        />
                      ))}
                      <strong>{v.peso}</strong>
                    </div>
                    {v.builtin || !canEdit ? <span className="var-espaco" aria-hidden="true" /> : (
                      <button type="button" className="danger-outline" onClick={() => removeVariavel(v)} disabled={savingV === v.id || usos > 0} title={usos > 0 ? 'Troque a variável das perguntas antes de remover' : 'Remover variável'}>
                        {savingV === v.id && <Spinner />}
                        Remover
                      </button>
                    )}
                  </article>
                );
              })}
            </div>
            {!busy && !variaveis.length && <div className="empty">Nenhuma variável cadastrada ainda.</div>}

            {canEdit && !novaVarAberta && (
              <button type="button" className="rot-adicionar" onClick={() => setNovaVarAberta(true)}>
                + Nova variável do agente
              </button>
            )}
            {canEdit && novaVarAberta && (
              <form onSubmit={async (e) => { await createVariavel(e); setNovaVarAberta(false); }} className="step-card rot-nova var-nova">
                <label style={{ margin: 0, flex: '1 1 200px' }}>
                  Nova variável
                  <input autoFocus placeholder="ex.: Urgência relatada" value={newV.name} onChange={(e) => setNewV((v) => ({ ...v, name: e.target.value }))} required />
                </label>
                <label style={{ margin: 0 }}>
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
                <button type="button" className="secondary" onClick={() => setNovaVarAberta(false)}>
                  Cancelar
                </button>
              </form>
            )}
          </section>

          <section className="section">
            <h3 style={{ marginTop: 0 }}>Variáveis de roteiro</h3>
            <p style={{ margin: '0 0 14px', fontSize: 13.5 }}>
              Sem peso: guardam o texto que o cliente respondeu para reusar como marcador em outros textos. Clique no marcador para copiar.
            </p>
            <div className="vr-lista">
              {variaveisRoteiro.map((v) => {
                const usos = questions.filter((q) => q.variavel_roteiro === v.id).length;
                return (
                  <article key={v.id} className="step-card vr-card">
                    <span aria-hidden className="var-cor" style={{ background: v.cor }} />
                    <div className="var-nome">
                      <strong>{v.name}</strong>
                      <small>{v.builtin ? 'fixa em toda empresa' : usos ? `guardada por ${usos} pergunta${usos === 1 ? '' : 's'}` : 'ainda sem pergunta'}</small>
                    </div>
                    <button
                      type="button"
                      className={`vr-token${copiado === v.slug ? ' copiado' : ''}`}
                      title="Copiar marcador"
                      onClick={() => {
                        navigator.clipboard?.writeText('{' + v.slug + '}');
                        setCopiado(v.slug);
                        window.setTimeout(() => setCopiado(''), 1400);
                      }}
                    >
                      {copiado === v.slug ? 'Copiado!' : '{' + v.slug + '}'}
                    </button>
                    {!v.builtin && canEdit && (
                      <button type="button" className="danger-outline" onClick={() => removeVariavelRoteiro(v)} disabled={savingVR === v.id}>
                        {savingVR === v.id && <Spinner />}
                        Remover
                      </button>
                    )}
                  </article>
                );
              })}
            </div>
            {!busy && !variaveisRoteiro.length && <div className="empty">Nenhuma variável de roteiro cadastrada ainda.</div>}

            {canEdit && (
              <form onSubmit={createVariavelRoteiro} className="vr-nova">
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

      {tab === 'classificacoes' && <ClassificacoesTab api={api} company={company} canEdit={canEdit} onSalvo={(c) => onCompanyChange?.(c)} />}

      {tab === 'opcoes-agente' && (
        <section className="section">
          <article className="step-card" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <label style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 10, fontWeight: 600 }}>
              <input type="checkbox" style={{ width: 'auto' }} checked={etapaInicial} disabled={!canEdit || savingOpcoes || busy} onChange={(e) => salvarInicioSpin({ etapa_inicial: e.target.checked })} />
              Etapa Inicial?
            </label>
            <fieldset disabled={!canEdit || savingOpcoes || busy} style={{ border: '1px solid var(--line)', borderRadius: 8, margin: 0 }}>
              <legend>SPINs que o cliente pode acessar</legend>
              {areasDoFluxo.map((area) => {
                const temPerguntas = questions.some((q) => q.area === area.id && q.text.trim());
                const marcada = spinsIniciais.includes(area.id);
                return (
                  <div key={area.id} style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 400, margin: 0 }}>
                      <input
                        type="checkbox"
                        style={{ width: 'auto' }}
                        checked={marcada}
                        disabled={!marcada && !temPerguntas}
                        onChange={(e) => salvarInicioSpin({ spins_iniciais: e.target.checked ? [...spinsIniciais, area.id] : spinsIniciais.filter((id) => id !== area.id) })}
                      />
                      {area.name}
                      {!temPerguntas && <small style={{ color: 'var(--muted)' }}>(sem perguntas com texto)</small>}
                    </label>
                    <button
                      type="button"
                      className="chip chip-neutral"
                      style={{ border: 'none', cursor: 'pointer' }}
                      onClick={() => setPalavrasArea(area)}
                      title="Palavras que levam o cliente até esta SPIN"
                    >
                      Palavras-chave{listaDePalavras(area.palavras_chave).length ? ` · ${listaDePalavras(area.palavras_chave).length}` : ''}
                    </button>
                  </div>
                );
              })}
              {!areasDoFluxo.length && <small style={{ color: 'var(--muted)' }}>Nenhuma área cadastrada ainda (tela Equipe).</small>}
              <small className="rot-fora-nota">Fora de escopo está sempre ativo: assunto sem área correspondente é desqualificado.</small>
            </fieldset>
            {spinsIniciais.length > 1 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <small style={{ color: 'var(--muted)' }}>
                  Com mais de uma SPIN, o cliente chega por uma campanha (o texto dela não é controlado por aqui) e o agente classifica a área
                  pela primeira mensagem. As palavras-chave de cada SPIN (chip ao lado do nome) ajudam o agente a reconhecer a área. Se a mensagem não corresponder a nenhuma
                  área habilitada, o lead é desqualificado como fora de escopo.
                </small>
              </div>
            )}
            {(() => {
              const ql = offflowQuestions.find((x) => x.question_id === 'lembrete');
              return (
                <div className="opc-lembrete">
                  <label>
                    <input type="checkbox" style={{ width: 'auto' }} checked={!!ql?.habilitada} disabled={!canEdit || !ql || savingQ === ql?.id || busy} onChange={(e) => ql && saveQuestion(ql, { habilitada: e.target.checked })} />
                    Enviar lembrete de continuidade ao cliente
                  </label>
                  <small>
                    Quem fica 24 horas sem responder recebe uma mensagem do agente e, logo depois, a pergunta em que parou. Sem retorno em mais 24 horas, a triagem é apagada.
                    O texto e o horário ficam em “Textos fora do fluxo”.
                  </small>
                </div>
              );
            })()}
            <p style={{ fontSize: 13.5, color: 'var(--muted)', margin: 0 }}>
              Marcada: o atendimento começa diretamente na SPIN habilitada (ou, com várias, na que o agente reconhecer pela
              mensagem inicial do cliente). O agente envia somente as perguntas dela,
              segue as etapas Situação, Problema, Implicação e Necessidade e classifica com as variáveis e pesos definidos.
              Dados reconhecidos nas mensagens do cliente preenchem as variáveis, sem perguntas extras de identificação,
              apresentação, validação ou encerramento.
              O pedido de atendimento humano fica desabilitado. Com nome, demanda e área preenchidos, o agente já pode
              classificar a urgência e encaminhar a lead, mesmo antes da última pergunta. O nome do perfil do WhatsApp
              pode preencher o nome quando o cliente não o informa.
            </p>
          </article>
          <article className="step-card" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <label style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 10, fontWeight: 600 }}>
              <input
                type="checkbox"
                style={{ width: 'auto' }}
                checked={conversacional}
                disabled={!canEdit || savingOpcoes || etapaInicial}
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
          <article className="step-card" style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 12 }}>
            <label style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 10, fontWeight: 600 }}>
              <input
                type="checkbox"
                style={{ width: 'auto' }}
                checked={company.allow_transcription && mensagensAudio}
                disabled={!canEdit || savingOpcoes || !company.allow_transcription}
                onChange={(e) => salvarOpcaoAudio({ mensagens_audio: e.target.checked })}
                data-testid="mensagens-audio"
              />
              Mensagens via áudio
            </label>
            <p style={{ fontSize: 13.5, color: 'var(--muted)', margin: 0 }}>
              O agente envia todas as mensagens como áudio. O áudio é gerado automaticamente a partir do texto; perguntas
              com gravação própria usam a gravação.
            </p>
            {!company.allow_transcription && (
              <p style={{ fontSize: 13.5, color: 'var(--warn)', margin: 0 }}>Habilite o áudio no painel Admin.</p>
            )}
            <label style={{ margin: 0 }}>
              Voz
              <select
                value={voz}
                disabled={!canEdit || savingOpcoes || !company.allow_transcription}
                onChange={(e) => salvarOpcaoAudio({ voz_tts: e.target.value })}
              >
                {VOZES_TTS.map((v) => (
                  <option key={v.id} value={v.id}>{v.label}</option>
                ))}
              </select>
            </label>
            {erroOpcoes && <small style={{ color: 'var(--danger, #c0392b)' }}>{erroOpcoes}</small>}
          </article>
        </section>
      )}
      {palavrasArea && (
        <PalavrasChaveDialog
          area={palavrasArea.name}
          valor={palavrasArea.palavras_chave}
          somenteLeitura={!canEdit}
          salvando={savingOpcoes}
          multiplasSpins={spinsIniciais.length > 1}
          onSalvar={(palavras) => salvarPalavrasChave(palavrasArea, palavras)}
          onClose={() => setPalavrasArea(null)}
        />
      )}
      </div>
    </>
  );
}
