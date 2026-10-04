import { Logo } from './Logo';
import { ProfileMenu } from './ProfileMenu';
import type { Api } from '../api';
import type { Company, Me } from '../types';

export type View = 'dashboard' | 'leads' | 'pendencias' | 'humano' | 'roteiro' | 'dados-empresa' | 'equipe';

export function Sidebar({
  role,
  companies,
  companyId,
  onCompanyChange,
  view,
  onNavigate,
  onLogout,
  leadsCount,
  pendingCount,
  humanCount,
  api,
  me,
  onMeChange,
  onAccountDeleted,
  onOpenTrocarEmail,
  onOpenTrocarSenha,
  isSuperuser,
  onOpenAdminPanel,
}: {
  role: 'atendente' | 'empresa';
  companies: Company[];
  companyId: string;
  onCompanyChange: (id: string) => void;
  view: View;
  onNavigate: (v: View) => void;
  onLogout: () => void;
  leadsCount: number;
  pendingCount: number;
  humanCount: number;
  api: Api;
  me: Me;
  onMeChange: (patch: Partial<Me>) => void;
  onAccountDeleted: () => void;
  onOpenTrocarEmail: () => void;
  onOpenTrocarSenha: () => void;
  isSuperuser: boolean;
  onOpenAdminPanel: () => void;
}) {
  const items: { key: View; label: string; count?: number }[] = [
    { key: 'dashboard', label: 'Dashboard' },
    { key: 'leads', label: 'Todos os leads', count: leadsCount },
    { key: 'pendencias', label: 'Pendências', count: pendingCount },
    { key: 'humano', label: 'Meus Atendimentos', count: humanCount },
  ];
  if (role === 'empresa') {
    items.push({ key: 'roteiro', label: 'Roteiro do agente' });
    items.push({ key: 'dados-empresa', label: 'Dados da empresa' });
    items.push({ key: 'equipe', label: 'Equipe' });
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-glow" />
      <div className="sidebar-dots" />
      <div className="brand">
        <Logo />
        <span>Conecta</span>
      </div>
      <div className="workspace">
        <small>ESPAÇO DE TRABALHO</small>
        <select className="company-pill" value={companyId} onChange={(e) => onCompanyChange(e.target.value)} aria-label="Empresa">
          {companies.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <span className="role-pill">{role === 'empresa' ? 'Perfil: Administrador da empresa' : 'Perfil: Atendente'}</span>
      </div>
      <nav>
        {items.map((it) => (
          <button key={it.key} type="button" className={view === it.key ? 'nav-active' : ''} onClick={() => onNavigate(it.key)}>
            <span>{it.label}</span>
            {it.count !== undefined && <span className="nav-count">{it.count}</span>}
          </button>
        ))}
      </nav>
      {isSuperuser && (
        <button type="button" className="secondary" onClick={onOpenAdminPanel}>
          Painel Admin interno
        </button>
      )}
      <p className="sidebar-note">
        {role === 'empresa'
          ? 'Você define o roteiro que o agente segue. Atendentes recebem a triagem já concluída e não configuram esse fluxo.'
          : 'O agente conduz a triagem automática e só chega até você quando precisa de uma decisão humana.'}
      </p>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <ProfileMenu
          api={api}
          me={me}
          onMeChange={onMeChange}
          onAccountDeleted={onAccountDeleted}
          onOpenTrocarEmail={onOpenTrocarEmail}
          onOpenTrocarSenha={onOpenTrocarSenha}
          onLogout={onLogout}
        />
        <button type="button" className="logout" style={{ flex: 1 }} onClick={onLogout}>
          Sair
        </button>
      </div>
    </aside>
  );
}
