import { Logo } from './Logo';
import { paletaDaEmpresa } from '../identidade';
import { ProfileMenu } from './ProfileMenu';
import type { Api } from '../api';
import type { Company, Me } from '../types';
import { confirmarSaida, useConfirmar } from './ConfirmDialog';

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
            <span>{it.label}</span>
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
