import { useEffect, useState } from 'react';
import type { Api } from '../api';
import type { Company, Question, Paginated } from '../types';
import { SkeletonCards } from '../components/Skeleton';

export function Roteiro({ api, company, canEdit }: { api: Api; company: Company; canEdit: boolean }) {
  const [questions, setQuestions] = useState<Question[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setBusy(true);
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
        {canEdit && <button>Nova pergunta</button>}
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <section className="section">
        {busy && !questions.length && <SkeletonCards count={4} height={92} />}
        {questions.map((q) => (
          <article key={q.id} className="step-card">
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginBottom: 10 }}>
              <span className="step-tag">{q.question_id}</span>
              {q.audio_asset && <span className="chip chip-neutral">áudio: {q.audio_asset}</span>}
            </div>
            <p style={{ color: 'var(--ink)', fontSize: 15 }}>“{q.text || 'Sem texto cadastrado'}”</p>
          </article>
        ))}
        {!busy && !questions.length && <div className="empty">Nenhuma pergunta cadastrada para esta empresa ainda.</div>}
      </section>
    </>
  );
}
