import { Logo } from './Logo';
import { IconeMenu } from './IconesMenu';
import { BotaoFixarPainel, useSidebarFixa } from './PainelLateral';
import { ProfileMenu } from './ProfileMenu';
import type { Api } from '../api';
import type { Me } from '../types';
import { confirmarSaida, useConfirmar } from './ConfirmDialog';

export type AdminView = 'dashboard' | 'equipe' | 'painel' | 'gestores' | 'faturamento' | 'cobrancas';

const ITEMS: { key: AdminView; label: string }[] = [
  { key: 'dashboard', label: 'Dashboard' },
  { key: 'equipe', label: 'Equipe' },
  { key: 'painel', label: 'Painel admin interno' },
  { key: 'gestores', label: 'Gestores' },
  { key: 'faturamento', label: 'Faturamento' },
  { key: 'cobrancas', label: 'Cobranças' },
];

/**
 * Sidebar exclusiva do admin geral (is_superuser) -- nunca vê o workspace de
 * nenhuma empresa, então não tem seletor de empresa nem os itens operacionais
 * (Leads/Pendências/Roteiro/etc.) que o Sidebar normal (componente Sidebar)
 * mostra pra atendente/empresa.
 */
export function AdminSidebar({
  view,
  onNavigate,
  onLogout,
  api,
  me,
  onMeChange,
  onAccountDeleted,
  onOpenTrocarEmail,
  onOpenTrocarSenha,
}: {
  view: AdminView;
  onNavigate: (v: AdminView) => void;
  onLogout: () => void;
  api: Api;
  me: Me;
  onMeChange: (patch: Partial<Me>) => void;
  onAccountDeleted: () => void;
  onOpenTrocarEmail: () => void;
  onOpenTrocarSenha: () => void;
}) {
  const confirmar = useConfirmar();
  const [fixa, alternarFixa] = useSidebarFixa();
  return (
    <div className={`sidebar-slot${fixa ? ' fixa' : ''}`}>
    <aside className="sidebar">
      <div className="sidebar-glow" />
      <div className="sidebar-dots" />
      <BotaoFixarPainel fixa={fixa} onAlternar={alternarFixa} />
      <div className="brand">
        <Logo />
        <span>Conecta</span>
      </div>
      <div className="workspace">
        <small>ESPAÇO DE TRABALHO</small>
        <span className="role-pill">Perfil: Admin geral</span>
      </div>
      <nav>
        {ITEMS.map((it) => (
          <button key={it.key} type="button" className={view === it.key ? 'nav-active' : ''} onClick={() => onNavigate(it.key)}>
            <span className="nav-label">
              <IconeMenu nome={it.key} />
              <span className="nav-texto">{it.label}</span>
            </span>
          </button>
        ))}
      </nav>
      <p className="sidebar-note">Visão agregada de toda a plataforma — nenhum workspace de empresa específica.</p>
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
    </div>
  );
}
