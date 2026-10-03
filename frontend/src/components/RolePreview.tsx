import type { Role } from '../types';

const ROLES: { key: Role; label: string }[] = [
  { key: 'atendente', label: 'Atendente' },
  { key: 'empresa', label: 'Empresa' },
  { key: 'admin', label: 'Admin' },
];

/**
 * O backend ainda não tem um campo de papel por usuário (ver docs/definicoes.md,
 * "Permissões de escrita dos papéis admin, supervisor e atendente" como pendência).
 * Este seletor é só para pré-visualizar as 3 telas no frontend; remover quando
 * o papel vier do /api/login/ ou de um endpoint de perfil.
 */
export function RolePreview({ role, onChange }: { role: Role; onChange: (r: Role) => void }) {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, color: 'var(--muted)' }}>
      <span>Pré-visualizar como:</span>
      {ROLES.map((r) => (
        <button
          key={r.key}
          type="button"
          className={r.key === role ? '' : 'secondary'}
          style={{ padding: '3px 10px', fontSize: 12 }}
          onClick={() => onChange(r.key)}
        >
          {r.label}
        </button>
      ))}
    </div>
  );
}
