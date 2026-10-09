import { Logo } from './Logo';
import { paletaDaEmpresa } from '../identidade';
import { ProfileMenu } from './ProfileMenu';
import type { Api } from '../api';
import type { Company, Me } from '../types';
import { confirmarSaida, useConfirmar } from './ConfirmDialog';

// Ícones de traço da navegação (cor = texto do item, respeita a identidade visual da empresa).
const ICONES: Record<string, React.ReactNode> = {
  dashboard: <><rect x="2" y="2" width="5" height="6" rx="1.5" /><rect x="9" y="2" width="5" height="4" rx="1.5" /><rect x="2" y="10" width="5" height="4" rx="1.5" /><rect x="9" y="8" width="5" height="6" rx="1.5" /></>,
  leads: <><rect x="2" y="2.5" width="3.2" height="11" rx="1" /><rect x="6.4" y="2.5" width="3.2" height="7" rx="1" /><rect x="10.8" y="2.5" width="3.2" height="9" rx="1" /></>,
  especiais: <><circle cx="8" cy="8" r="6" /><path d="M8 5v3l2 1.5" strokeLinecap="round" /></>,
  pendencias: <><path d="M8 2.5l5.5 10h-11z" strokeLinejoin="round" /><path d="M8 6.5v2.5" strokeLinecap="round" /></>,
  humano: <><circle cx="8" cy="5.5" r="2.5" /><path d="M3 13.5c.8-2.4 2.7-3.6 5-3.6s4.2 1.2 5 3.6" strokeLinecap="round" /></>,
  blacklist: <><circle cx="8" cy="8" r="6" /><path d="M4 12L12 4" /></>,
  roteiro: <path d="M3 3h10M3 8h10M3 13h6" strokeLinecap="round" />,
  'dados-empresa': <><rect x="3" y="2" width="10" height="12" rx="2" /><path d="M6 6h4M6 9h4" strokeLinecap="round" /></>,
  equipe: <><circle cx="6" cy="6" r="2.5" /><path d="M1.5 13c.6-2.3 2.4-3.5 4.5-3.5s3.9 1.2 4.5 3.5" strokeLinecap="round" /><circle cx="11.5" cy="5.5" r="2" /></>,
  identidade: <><circle cx="8" cy="8" r="6" /><circle cx="6" cy="6.5" r=".6" /><circle cx="10" cy="6.5" r=".6" /><circle cx="8" cy="10.5" r=".6" /></>,
};

export type View = 'dashboard' | 'leads' | 'especiais' | 'pendencias' | 'humano' | 'blacklist' | 'roteiro' | 'dados-empresa' | 'equipe';

export function Sidebar({
  role,
  companies,
  companyId,
  onCompanyChange,
  view,
  onNavigate,
  onLogout,
  leadsCount,
  especialCount,
  pendingCount,
  humanCount,
  api,
  me,
  onMeChange,
  onAccountDeleted,
  onOpenTrocarEmail,
  onOpenTrocarSenha,
  onOpenIdentidade,
}: {
  role: 'atendente' | 'empresa';
  companies: Company[];
  companyId: string;
  onCompanyChange: (id: string) => void;
  view: View;
  onNavigate: (v: View) => void;
  onLogout: () => void;
  leadsCount: number;
  especialCount: number;
  pendingCount: number;
  humanCount: number;
  api: Api;
  me: Me;
  onMeChange: (patch: Partial<Me>) => void;
  onAccountDeleted: () => void;
  onOpenTrocarEmail: () => void;
  onOpenTrocarSenha: () => void;
  /** Abre o popup de identidade visual (só a conta Empresa). */
  onOpenIdentidade: () => void;
}) {
  const confirmar = useConfirmar();
  const items: { key: View | 'identidade'; label: string; count?: number }[] = [{ key: 'dashboard', label: 'Dashboard' }];
  if (role === 'atendente') {
    items.push({ key: 'leads', label: 'Todos os leads', count: leadsCount });
    items.push({ key: 'especiais', label: 'Outras situações', count: especialCount });
    items.push({ key: 'pendencias', label: 'Pendências', count: pendingCount });
    items.push({ key: 'humano', label: 'Meus Atendimentos', count: humanCount });
  }
  if (role === 'empresa') items.push({ key: 'especiais', label: 'Outras situações', count: especialCount });
  items.push({ key: 'blacklist', label: 'BlackList' });
  if (role === 'empresa') {
    items.push({ key: 'roteiro', label: 'Roteiro do agente' });
    items.push({ key: 'dados-empresa', label: 'Dados da empresa' });
    items.push({ key: 'equipe', label: 'Equipe' });
    items.push({ key: 'identidade', label: 'Identidade visual' });
  }

  // Identidade visual da empresa selecionada (só ela e a equipe dela a recebem do CRM); sem ela, padrão Conecta.
  const identidade = companies.find((c) => String(c.id) === companyId)?.identidade_visual;
  const paleta = paletaDaEmpresa(identidade);

  return (
    <aside className={`sidebar${paleta ? ' sidebar-custom' : ''}`} style={paleta ? ({ background: paleta.fundo, color: paleta.vars['--sb-fg'], ...paleta.vars } as React.CSSProperties) : undefined}>
      <div className="sidebar-glow" />
      <div className="sidebar-dots" />
      <div className="brand">
        {identidade?.logo_url ? <img src={identidade.logo_url} alt="" /> : <Logo />}
        <span>{identidade?.nome || 'Conecta'}</span>
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
          <button key={it.key} type="button" className={view === it.key ? 'nav-active' : ''} onClick={() => (it.key === 'identidade' ? onOpenIdentidade() : onNavigate(it.key))}>
            <span className="nav-label">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">{ICONES[it.key]}</svg>
              {it.label}
            </span>
            {it.count !== undefined && <span className="nav-count">{it.count}</span>}
          </button>
        ))}
      </nav>
      <p className="sidebar-note">
        {role === 'empresa'
          ? 'Você define o roteiro que o agente segue. Atendentes recebem a triagem já concluída e não configuram esse fluxo.'
          : 'O agente conduz a triagem automática e só chega até você quando precisa de uma decisão humana.'}
      </p>
      <div className="sidebar-actions" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <ProfileMenu
          api={api}
          me={me}
          onMeChange={onMeChange}
          onAccountDeleted={onAccountDeleted}
          onOpenTrocarEmail={onOpenTrocarEmail}
          onOpenTrocarSenha={onOpenTrocarSenha}
          onLogout={onLogout}
        />
        <button
          type="button"
          className="logout"
          style={{ flex: 1 }}
          onClick={async () => {
            if (await confirmarSaida(confirmar, me)) onLogout();
          }}
        >
          Sair
        </button>
      </div>
    </aside>
  );
}
