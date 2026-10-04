import { useEffect, useState } from 'react';
import type { Api } from '../api';
import type { AdminContaEmpresa } from '../types';
import { SkeletonRows } from '../components/Skeleton';

export function AdminEquipe({ api }: { api: Api }) {
  const [contas, setContas] = useState<AdminContaEmpresa[]>([]);
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setBusy(true);
    setError('');
    api('/admin-companies/contas-empresa/')
      .then((d: AdminContaEmpresa[]) => setContas(d))
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }, [api]);

  const visible = contas.filter((c) => `${c.display_name} ${c.username} ${c.email}`.toLowerCase().includes(search.toLowerCase()));

  return (
    <>
      <header className="page-header" style={{ alignItems: 'flex-end' }}>
        <div>
          <small className="eyebrow">Plataforma</small>
          <h1>Equipe</h1>
          <p>Contas "Empresa" cadastradas em toda a plataforma — atendentes ficam na Equipe de dentro de cada empresa.</p>
        </div>
        <input placeholder="Buscar conta" aria-label="Buscar conta" style={{ width: 260 }} value={search} onChange={(e) => setSearch(e.target.value)} />
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <section className="panel">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Nome</th>
                <th>Usuário</th>
                <th>E-mail</th>
                <th>Empresa(s)</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {busy && !visible.length && <SkeletonRows rows={4} cols={5} />}
              {visible.map((c) => (
                <tr key={c.id}>
                  <td style={{ fontWeight: 600 }}>{c.display_name || '—'}</td>
                  <td style={{ fontFamily: "'DM Mono',monospace" }}>{c.username}</td>
                  <td>{c.email || '—'}</td>
                  <td>{c.companies.join(', ') || '—'}</td>
                  <td>
                    <span className={`badge ${c.is_active ? 'status-active' : 'status-suspended'}`}>{c.is_active ? 'Ativa' : 'Inativa'}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!busy && !visible.length && <div className="empty">Nenhuma conta de empresa encontrada.</div>}
        </div>
      </section>
    </>
  );
}
