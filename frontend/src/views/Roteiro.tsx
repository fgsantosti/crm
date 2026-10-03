import { useEffect, useState } from 'react';
import type { Api } from '../api';
import type { Company, Question, Paginated } from '../types';
import { SkeletonCards } from '../components/Skeleton';

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

function LegendaTokens() {
  return (
    <section className="panel" style={{ padding: '16px 24px', marginBottom: 20, display: 'flex', flexWrap: 'wrap', gap: '14px 28px', alignItems: 'center' }}>
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
      <small style={{ color: 'var(--muted)' }}>Esses marcadores são resolvidos automaticamente pelo CRM antes de enviar — nunca edite o texto dentro das chaves.</small>
    </section>
  );
}

export function Roteiro({ api, company, canEdit }: { api: Api; company: Company; canEdit: boolean }) {
  const [questions, setQuestions] = useState<Question[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setBusy(true);
    setError('');
    api(`/questions/?company=${company.id}`)
      .then((d: Paginated<Question> | Question[]) => {
        if (active) setQuestions(Array.isArray(d) ? d : d.results);
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

  return (
    <>
      <header className="page-header">
        <div>
          <small className="eyebrow">Configuração</small>
          <h1>Roteiro aprovado</h1>
          <p>
            O agente Axioma decide a próxima pergunta e a classificação sozinho; aqui você só define o texto (e o áudio,
            quando houver) de cada <code>question_id</code> que ele pode pedir. {canEdit ? 'Você edita este conteúdo.' : 'Somente a empresa edita.'}
          </p>
        </div>
        {canEdit && (
          <button disabled title="Em breve">
            Nova pergunta
          </button>
        )}
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <LegendaTokens />

      <section className="section">
        {busy && !questions.length && <SkeletonCards count={4} height={92} />}
        {questions.map((q) => (
          <article key={q.id} className="step-card">
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginBottom: 10 }}>
              <span className="step-tag">{q.question_id}</span>
              {q.audio_asset && <span className="chip chip-neutral">áudio: {q.audio_asset}</span>}
            </div>
            <p style={{ color: 'var(--ink)', fontSize: 15 }}>“{q.text ? destacarTexto(q.text) : 'Sem texto cadastrado'}”</p>
          </article>
        ))}
        {!busy && !questions.length && <div className="empty">Nenhuma pergunta cadastrada para esta empresa ainda.</div>}
      </section>
    </>
  );
}
