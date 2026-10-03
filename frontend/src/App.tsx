import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiFactory, clearTokens, hasSession, logoutRequest } from './api';
import type { Company, Lead, Me, Paginated, Role } from './types';
import { Sidebar, type View } from './components/Sidebar';
import { Login } from './views/Login';
import { Dashboard } from './views/Dashboard';
import { Leads } from './views/Leads';
import { Pendencias } from './views/Pendencias';
import { AtendimentoHumano } from './views/AtendimentoHumano';
import { Roteiro } from './views/Roteiro';
import { DadosEmpresa } from './views/DadosEmpresa';
import { Equipe } from './views/Equipe';
import { Admin } from './views/Admin';
import { TrocarSenhaObrigatoria } from './views/TrocarSenhaObrigatoria';

export function App() {
  const [authed, setAuthed] = useState(() => hasSession());
  const [me, setMe] = useState<Me | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState('');
  const [view, setView] = useState<View>('dashboard');
  const [error, setError] = useState('');
  const [leadsCount, setLeadsCount] = useState(0);
  const [pendingCount, setPendingCount] = useState(0);
  const [humanCount, setHumanCount] = useState(0);
  const [companiesRetry, setCompaniesRetry] = useState(0);

  const onSessionExpired = useCallback(() => {
    clearTokens();
    setAuthed(false);
    setMe(null);
  }, []);
  const api = useMemo(() => apiFactory(onSessionExpired), [onSessionExpired]);
  const company = companies.find((c) => String(c.id) === companyId) || null;
  const role: Role = me?.is_superuser ? 'admin' : me?.is_staff ? 'empresa' : 'atendente';

  useEffect(() => {
    if (!authed) {
      setMe(null);
      return;
    }
    let active = true;
    api('/me/')
      .then((d: Me) => {
        if (active) setMe(d);
      })
      .catch((e) => {
        if (active) {
          setError(e.message);
          setAuthed(false);
        }
      });
    return () => {
      active = false;
    };
  }, [authed]);

  useEffect(() => {
    if (!authed) return;
    let active = true;
    setError('');
    api('/companies/')
      .then((d) => {
        if (active) {
          setCompanies(d.results);
          setCompanyId(String(d.results[0]?.id || ''));
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [authed, companiesRetry]);

  useEffect(() => {
    if (!company) return;
    let active = true;
    Promise.all([api(`/leads/?company=${company.id}`), api(`/leads/?company=${company.id}&pending=1`)])
      .then(([main, pending]: [Paginated<Lead>, Paginated<Lead>]) => {
        if (!active) return;
        setLeadsCount(main.count);
        setHumanCount(main.results.filter((l) => l.mode === 'HUMANO').length);
        setPendingCount(pending.count);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [company?.id]);

  useEffect(() => {
    if (role !== 'empresa' && (view === 'roteiro' || view === 'dados-empresa' || view === 'equipe')) setView('dashboard');
  }, [role, view]);

  function logout() {
    logoutRequest();
    clearTokens();
    setAuthed(false);
    setMe(null);
    setCompanies([]);
    setCompanyId('');
    setView('dashboard');
    setError('');
  }

  if (!authed) return <Login onLogin={() => setAuthed(true)} />;
  if (!me) return <div className="shell" />;
  if (me.must_change_password) return <TrocarSenhaObrigatoria api={api} onDone={() => setMe({ ...me, must_change_password: false })} onLogout={logout} />;
  if (role === 'admin') return <Admin onLogout={logout} />;

  if (!company) {
    return (
      <div className="shell">
        <main className="main">
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <div className="empty">
            {error ? 'Não foi possível carregar suas empresas.' : companies.length ? 'Carregando empresa…' : 'Nenhuma empresa vinculada. Solicite o vínculo ao administrador.'}
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 16 }}>
            {error && (
              <button type="button" onClick={() => setCompaniesRetry((n) => n + 1)}>
                Tentar novamente
              </button>
            )}
            <button type="button" className="secondary" onClick={logout}>
              Sair
            </button>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="shell">
      <Sidebar
        role={role === 'empresa' ? 'empresa' : 'atendente'}
        companies={companies}
        companyId={companyId}
        onCompanyChange={setCompanyId}
        view={view}
        onNavigate={setView}
        onLogout={logout}
        leadsCount={leadsCount}
        pendingCount={pendingCount}
        humanCount={humanCount}
        api={api}
        me={me}
        onMeChange={(patch) => setMe((prev) => (prev ? { ...prev, ...patch } : prev))}
        onAccountDeleted={logout}
      />
      <main className="main">
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div key={view} className="view-enter">
          {view === 'dashboard' && <Dashboard api={api} company={company} role={role === 'empresa' ? 'empresa' : 'atendente'} />}
          {view === 'leads' && <Leads api={api} company={company} />}
          {view === 'pendencias' && <Pendencias api={api} company={company} />}
          {view === 'humano' && <AtendimentoHumano api={api} company={company} />}
          {view === 'roteiro' && <Roteiro api={api} company={company} canEdit={role === 'empresa'} />}
          {view === 'dados-empresa' && <DadosEmpresa api={api} company={company} />}
          {view === 'equipe' && <Equipe api={api} company={company} />}
        </div>
      </main>
    </div>
  );
}
