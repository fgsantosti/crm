import { useEffect, useState } from 'react';
import type { Api } from '../api';
import type { AdminOverview } from '../types';
import { SkeletonTiles } from '../components/Skeleton';

export function AdminDashboard({ api }: { api: Api }) {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setBusy(true);
    setError('');
    api('/admin-companies/overview/')
      .then((d: AdminOverview) => setOverview(d))
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }, [api]);

  return (
    <>
      <header className="page-header">
        <div>
          <small className="eyebrow">Plataforma</small>
          <h1>Dashboard administrativo</h1>
          <p>Visão agregada de toda a plataforma Conecta — nenhum workspace de empresa específica.</p>
        </div>
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <section className="section">
        <h2>Resumo</h2>
        {busy && !overview ? (
          <SkeletonTiles />
        ) : (
          overview && (
            <div className="tiles">
              <article className="tile">
                <small>Empresas cadastradas</small>
                <strong style={{ color: 'var(--ink)' }}>{overview.empresas_total}</strong>
              </article>
              <article className="tile">
                <small>Chaves de API ativas</small>
                <strong style={{ color: 'var(--success)' }}>{overview.empresas_com_agente_ativo}</strong>
              </article>
              <article className="tile">
                <small>Sem chave ativa</small>
                <strong style={{ color: 'var(--muted)' }}>{overview.empresas_sem_agente_ativo}</strong>
              </article>
              <article className="tile">
                <small>Usuários ativos</small>
                <strong style={{ color: 'var(--accent)' }}>{overview.usuarios_ativos}</strong>
              </article>
            </div>
          )
        )}
        <p style={{ marginTop: 10, fontSize: 12, color: 'var(--muted)' }}>
          "Sem chave ativa" cobre empresas sem agente configurado, com a chave revogada ou expirada — gerenciar em "Painel
          admin interno".
        </p>
      </section>
    </>
  );
}
