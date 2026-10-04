import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiFactory, logoutRequest, trySilentLogin } from './api';
import type { Company, Lead, Me, Paginated, Role } from './types';
import { Sidebar, type View } from './components/Sidebar';
import { AdminSidebar, type AdminView } from './components/AdminSidebar';
import { Login } from './views/Login';
import { Dashboard } from './views/Dashboard';
import { Leads } from './views/Leads';
import { Pendencias } from './views/Pendencias';
import { AtendimentoHumano } from './views/AtendimentoHumano';
import { Roteiro } from './views/Roteiro';
import { DadosEmpresa } from './views/DadosEmpresa';
import { Equipe } from './views/Equipe';
import { Admin } from './views/Admin';
import { AdminDashboard } from './views/AdminDashboard';
import { AdminEquipe } from './views/AdminEquipe';
import { TrocarSenhaObrigatoria } from './views/TrocarSenhaObrigatoria';
import { TrocarEmailPagina } from './views/TrocarEmailPagina';
import { TrocarSenhaPagina } from './views/TrocarSenhaPagina';

type Screen = 'app' | 'trocar-email' | 'trocar-senha';

export function App() {
  // null = ainda checando a sessão (refresh silencioso via cookie httpOnly).
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState('');
  const [view, setView] = useState<View>('dashboard');
  const [error, setError] = useState('');
  const [leadsCount, setLeadsCount] = useState(0);
  const [pendingCount, setPendingCount] = useState(0);
  const [humanCount, setHumanCount] = useState(0);
  const [companiesRetry, setCompaniesRetry] = useState(0);
  const [screen, setScreen] = useState<Screen>('app');
  const [adminView, setAdminView] = useState<AdminView>('dashboard');

  const onSessionExpired = useCallback(() => {
    setAuthed(false);
    setMe(null);
  }, []);
  const api = useMemo(() => apiFactory(onSessionExpired), [onSessionExpired]);
  const company = companies.find((c) => String(c.id) === companyId) || null;
  const role: Role = me?.is_superuser ? 'admin' : me?.is_staff ? 'empresa' : 'atendente';

  useEffect(() => {
    trySilentLogin().then(setAuthed);
  }, []);

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
    // O admin geral nunca entra no workspace de empresa nenhuma -- não precisa
    // buscar /companies/ (ver bloco role === 'admin' mais abaixo).
    if (!authed || role === 'admin') return;
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
  }, [authed, companiesRetry, role]);

  useEffect(() => {
    if (!company) return;
    let active = true;
    // Só os `count` (total no servidor) -- nunca contar em cima de results, que é só a 1ª página.
    Promise.all([
      api(`/leads/?company=${company.id}&ativos=1`),
      api(`/leads/?company=${company.id}&pending=1`),
      api(`/leads/?company=${company.id}&meus=1`),
    ])
      .then(([ativos, pending, meus]: [Paginated<Lead>, Paginated<Lead>, Paginated<Lead>]) => {
        if (!active) return;
        setLeadsCount(ativos.count);
        setHumanCount(meus.count);
        setPendingCount(pending.count);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [company?.id]);

  useEffect(() => {
    if (role === 'atendente' && (view === 'roteiro' || view === 'dados-empresa' || view === 'equipe')) setView('dashboard');
    if (role === 'empresa' && (view === 'leads' || view === 'pendencias' || view === 'humano')) setView('dashboard');
  }, [role, view]);

  function logout() {
    logoutRequest();
    setAuthed(false);
    setMe(null);
    setCompanies([]);
    setCompanyId('');
    setView('dashboard');
    setScreen('app');
    setError('');
  }

  if (authed === null) return <div className="shell" />;
  if (!authed) return <Login onLogin={() => setAuthed(true)} />;
  if (!me) return <div className="shell" />;
  if (me.must_change_password) return <TrocarSenhaObrigatoria api={api} onDone={() => setMe({ ...me, must_change_password: false })} onLogout={logout} />;
  if (screen === 'trocar-email')
    return (
      <TrocarEmailPagina
        api={api}
        me={me}
        onDone={(email) => {
          setMe({ ...me, email });
          setScreen('app');
        }}
        onCancel={() => setScreen('app')}
      />
    );
  if (screen === 'trocar-senha') return <TrocarSenhaPagina api={api} me={me} onDone={() => setScreen('app')} onCancel={() => setScreen('app')} />;

  if (role === 'admin') {
    return (
      <div className="shell">
        <AdminSidebar
          view={adminView}
          onNavigate={setAdminView}
          onLogout={logout}
          api={api}
          me={me}
          onMeChange={(patch) => setMe((prev) => (prev ? { ...prev, ...patch } : prev))}
          onAccountDeleted={logout}
          onOpenTrocarEmail={() => setScreen('trocar-email')}
          onOpenTrocarSenha={() => setScreen('trocar-senha')}
        />
        <main className="main">
          <div key={adminView} className="view-enter">
            {adminView === 'dashboard' && <AdminDashboard api={api} />}
            {adminView === 'equipe' && <AdminEquipe api={api} />}
            {adminView === 'painel' && <Admin api={api} />}
          </div>
        </main>
      </div>
    );
  }

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
        role={role === 'atendente' ? 'atendente' : 'empresa'}
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
        onOpenTrocarEmail={() => setScreen('trocar-email')}
        onOpenTrocarSenha={() => setScreen('trocar-senha')}
      />
      <main className="main">
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div key={view} className="view-enter">
          {view === 'dashboard' && <Dashboard api={api} company={company} role={role === 'atendente' ? 'atendente' : 'empresa'} />}
          {view === 'leads' && <Leads api={api} company={company} role={role} me={me} />}
          {view === 'pendencias' && <Pendencias api={api} company={company} />}
          {view === 'humano' && <AtendimentoHumano api={api} company={company} me={me} />}
          {view === 'roteiro' && <Roteiro api={api} company={company} canEdit={role !== 'atendente'} />}
          {view === 'dados-empresa' && <DadosEmpresa api={api} company={company} />}
          {view === 'equipe' && <Equipe api={api} company={company} />}
        </div>
      </main>
    </div>
  );
}
