import { useEffect, useMemo, useState } from 'react';
import { apiFactory } from './api';
import type { Company, Lead, Paginated, Role } from './types';
import { Sidebar, type View } from './components/Sidebar';
import { RolePreview } from './components/RolePreview';
import { Login } from './views/Login';
import { Dashboard } from './views/Dashboard';
import { Leads } from './views/Leads';
import { Pendencias } from './views/Pendencias';
import { AtendimentoHumano } from './views/AtendimentoHumano';
import { Roteiro } from './views/Roteiro';
import { DadosEmpresa } from './views/DadosEmpresa';
import { Admin } from './views/Admin';

export function App() {
  const [token, setToken] = useState('');
  const [role, setRole] = useState<Role>('atendente');
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState('');
  const [view, setView] = useState<View>('dashboard');
  const [error, setError] = useState('');
  const [leadsCount, setLeadsCount] = useState(0);
  const [pendingCount, setPendingCount] = useState(0);
  const [humanCount, setHumanCount] = useState(0);

  const api = useMemo(() => apiFactory(token), [token]);
  const company = companies.find((c) => String(c.id) === companyId) || null;

  useEffect(() => {
    if (!token) return;
    let active = true;
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
  }, [token]);

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
    if (role !== 'empresa' && (view === 'roteiro' || view === 'dados-empresa')) setView('dashboard');
  }, [role, view]);

  function logout() {
    setToken('');
    setCompanies([]);
    setCompanyId('');
    setView('dashboard');
    setError('');
  }

  if (!token) return <Login onLogin={setToken} />;
  if (role === 'admin') return <Admin role={role} onRoleChange={setRole} onLogout={logout} />;

  if (!company) {
    return (
      <div className="empty">
        {error || (companies.length ? 'Carregando empresa…' : 'Nenhuma empresa vinculada. Solicite o vínculo ao administrador.')}
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
      />
      <main className="main">
        <RolePreview role={role} onChange={setRole} />
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
        </div>
      </main>
    </div>
  );
}
