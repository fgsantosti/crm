import { useEffect, useState } from 'react';
import type { Api } from '../api';
import type { Company, CompanyInfoEntry, Paginated } from '../types';
import { SkeletonCards, Spinner } from '../components/Skeleton';

export function DadosEmpresa({ api, company }: { api: Api; company: Company }) {
  const [entries, setEntries] = useState<CompanyInfoEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [savingId, setSavingId] = useState<number | 'new' | null>(null);
  const [error, setError] = useState('');

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

  return (
    <>
      <header className="page-header">
        <div>
          <small className="eyebrow">Base de conhecimento</small>
          <h1>Dados da empresa</h1>
          <p>
            Título e texto que o agente consulta para responder perguntas livres sobre a empresa — horário, endereço,
            serviços, formas de pagamento etc. — fora do roteiro fixo de qualificação.
          </p>
        </div>
        <button type="button" onClick={addEntry} disabled={savingId === 'new'}>
          {savingId === 'new' && <Spinner />}+ Nova entrada
        </button>
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <section className="section">
        {busy && !entries.length && <SkeletonCards count={3} height={140} />}
        {entries.map((entry) => (
          <form key={entry.id} className="step-card" onSubmit={(e) => save(entry, e)} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <label style={{ margin: 0 }}>
              Título
              <input name="title" defaultValue={entry.title} required style={{ fontWeight: 600 }} />
            </label>
            <label style={{ margin: 0 }}>
              Texto
              <textarea name="content" defaultValue={entry.content} rows={3} />
            </label>
            <div style={{ display: 'flex', gap: 10 }}>
              <button disabled={savingId === entry.id}>
                {savingId === entry.id && <Spinner />}
                Salvar
              </button>
              <button type="button" className="danger-outline" onClick={() => remove(entry)} disabled={savingId === entry.id}>
                Excluir
              </button>
            </div>
          </form>
        ))}
        {!busy && !entries.length && <div className="empty">Nenhuma entrada cadastrada ainda. Clique em "+ Nova entrada" para começar.</div>}
      </section>
    </>
  );
}
