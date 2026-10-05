import { useEffect, useState } from 'react';
import { fetchTodasAsPaginas, type Api } from '../api';
import type { BlacklistEntry, Company } from '../types';
import { SkeletonCards, Spinner } from '../components/Skeleton';

export function BlackList({ api, company }: { api: Api; company: Company }) {
  const [entries, setEntries] = useState<BlacklistEntry[]>([]);
  const [contact, setContact] = useState('');
  const [motivo, setMotivo] = useState('');
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState<number | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setBusy(true);
    setEntries([]);
    setContact('');
    setMotivo('');
    setSearch('');
    setError('');
    fetchTodasAsPaginas<BlacklistEntry>(api, `/blacklist/?company=${company.id}`)
      .then((data) => active && setEntries(data))
      .catch((err) => active && setError(err.message))
      .finally(() => active && setBusy(false));
    return () => { active = false; };
  }, [api, company.id]);

  async function add(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSaving(true);
    setError('');
    try {
      const entry: BlacklistEntry = await api(`/blacklist/?company=${company.id}`, {
        method: 'POST', body: JSON.stringify({ contact, motivo }),
      });
      setEntries((items) => [entry, ...items]);
      setContact('');
      setMotivo('');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function remove(entry: BlacklistEntry) {
    setRemoving(entry.id);
    setError('');
    try {
      await api(`/blacklist/${entry.id}/?company=${company.id}`, { method: 'DELETE' });
      setEntries((items) => items.filter((item) => item.id !== entry.id));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRemoving(null);
    }
  }

  const query = search.trim().toLowerCase();
  const digits = query.replace(/\D/g, '');
  const visible = entries.filter((entry) => `${entry.contact} ${entry.motivo} ${entry.adicionado_por_nome}`.toLowerCase().includes(query)
    || (!!digits && entry.contact.includes(digits)));

  return (
    <>
      <header className="page-header">
        <div>
          <small className="eyebrow">Controle de contatos</small>
          <h1>BlackList</h1>
          <p>O bot ignora os números desta lista. Empresa e atendentes podem adicionar e remover contatos.</p>
        </div>
      </header>
      {error && <p role="alert" className="error">{error}</p>}
      <form onSubmit={add} className="panel" style={{ padding: 20, marginBottom: 24 }}>
        <h2>Bloquear número</h2>
        <div className="fields">
          <label>Telefone com DDD
            <input type="tel" required maxLength={40} placeholder="+55 85 99999-8888" value={contact} onChange={(e) => setContact(e.target.value)} />
          </label>
          <label>Motivo (opcional)
            <input maxLength={200} value={motivo} onChange={(e) => setMotivo(e.target.value)} />
          </label>
        </div>
        <button type="submit" className="block-button" disabled={saving || busy}>
          {saving && <Spinner />}Adicionar à BlackList
        </button>
      </form>
      <section className="section">
        <div className="section-head">
          <h2>Números bloqueados ({entries.length})</h2>
          <input type="search" placeholder="Buscar telefone ou motivo" aria-label="Buscar na BlackList" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <p style={{ color: 'var(--muted)', fontSize: 12.5 }}>Remover libera o número para o bot. Atendimentos já concluídos permanecem no histórico.</p>
        {busy && <SkeletonCards count={3} height={96} />}
        {!busy && visible.map((entry) => (
          <article key={entry.id} className="queue-card">
            <div style={{ minWidth: 0 }}>
              <strong>{entry.contact}</strong>
              {entry.motivo && <p>{entry.motivo}</p>}
              <small style={{ color: 'var(--muted)' }}>
                Adicionado em {new Date(entry.created_at).toLocaleString('pt-BR')}{entry.adicionado_por_nome && ` por ${entry.adicionado_por_nome}`}
              </small>
            </div>
            <button type="button" className="secondary" disabled={removing !== null} onClick={() => remove(entry)}>
              {removing === entry.id && <Spinner />}Remover bloqueio
            </button>
          </article>
        ))}
        {!busy && !visible.length && <div className="empty">{query ? 'Nenhum número encontrado.' : 'Nenhum número na BlackList.'}</div>}
      </section>
    </>
  );
}
