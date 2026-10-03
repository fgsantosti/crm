import { Logo } from '../components/Logo';

/**
 * Tela interna da Axioma: cadastro de empresas e chave de API do agente.
 * Ainda SEM backend — Company não tem campo de api_key e não há endpoint
 * de CRUD de empresas na API (hoje isso é feito pelo Django Admin, conforme
 * o README). Os dados abaixo são estáticos, só para validar o layout.
 */
export function Admin({ onLogout }: { onLogout: () => void }) {
  return (
    <div className="admin-shell">
      <header className="admin-top">
        <div className="glow" />
        <div className="admin-top-left">
          <Logo size={34} />
          <span style={{ fontFamily: "'Neuton',serif", fontWeight: 700, fontSize: 20 }}>Conecta</span>
          <span className="admin-badge">Admin interno</span>
        </div>
        <div style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 18 }}>
          <span style={{ fontSize: 13.5, color: '#D9C7B4' }}>Axioma Operações</span>
          <button className="logout" onClick={onLogout}>
            Sair
          </button>
        </div>
      </header>

      <div className="admin-body">
        <main className="admin-main">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <small className="eyebrow">Plataforma</small>
              <h1 style={{ fontSize: 30 }}>Empresas cadastradas</h1>
              <p>Visível apenas para a equipe Axioma — nenhum cliente acessa esta tela.</p>
            </div>
            <button disabled title="Cadastro real pendente: ainda não há endpoint de empresas na API">
              + Nova empresa
            </button>
          </div>

          <input placeholder="Buscar empresa" aria-label="Buscar empresa" style={{ maxWidth: 320 }} disabled />

          <section className="panel">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Empresa</th>
                    <th>Atendentes</th>
                    <th>Status</th>
                    <th>Criada em</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="company-row-active">
                    <td style={{ fontWeight: 600 }}>Oliveira Advogados</td>
                    <td style={{ fontFamily: "'DM Mono',monospace" }}>3</td>
                    <td>
                      <span className="badge status-active">Ativa</span>
                    </td>
                    <td style={{ fontFamily: "'DM Mono',monospace", fontSize: 13, color: 'var(--muted)' }}>24/08/2026</td>
                  </tr>
                  <tr>
                    <td style={{ fontWeight: 600 }}>Felipe Santos Consultoria</td>
                    <td style={{ fontFamily: "'DM Mono',monospace" }}>1</td>
                    <td>
                      <span className="badge status-active">Ativa</span>
                    </td>
                    <td style={{ fontFamily: "'DM Mono',monospace", fontSize: 13, color: 'var(--muted)' }}>24/08/2026</td>
                  </tr>
                  <tr>
                    <td style={{ fontWeight: 600 }}>Nunes Odontologia</td>
                    <td style={{ fontFamily: "'DM Mono',monospace" }}>2</td>
                    <td>
                      <span className="badge status-suspended">Suspensa</span>
                    </td>
                    <td style={{ fontFamily: "'DM Mono',monospace", fontSize: 13, color: 'var(--muted)' }}>02/09/2026</td>
                  </tr>
                  <tr>
                    <td style={{ fontWeight: 600 }}>Cliente em homologação</td>
                    <td style={{ fontFamily: "'DM Mono',monospace" }}>0</td>
                    <td>
                      <span className="badge status-pending">Pendente</span>
                    </td>
                    <td style={{ fontFamily: "'DM Mono',monospace", fontSize: 13, color: 'var(--muted)' }}>30/09/2026</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <p style={{ fontSize: '12.5px', color: 'var(--muted)' }}>
            Dados estáticos — a lista real depende de um endpoint de empresas no backend (hoje a criação é só pelo Django Admin).
          </p>
        </main>

        <aside className="admin-detail">
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <h2 style={{ fontSize: 21 }}>Oliveira Advogados</h2>
              <span className="badge status-active">Ativa</span>
            </div>
            <p style={{ fontSize: '13.5px' }}>Cadastrada em 24/08/2026 · responsável: equipe interna Axioma</p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <label>
              Estado inicial
              <input readOnly value="INICIAL" style={{ fontFamily: "'DM Mono',monospace", fontSize: 13 }} />
            </label>
            <label>
              Canal de saída
              <input readOnly value="TEXTO" style={{ fontFamily: "'DM Mono',monospace", fontSize: 13 }} />
            </label>
          </div>

          <div className="section-divider" />

          <div>
            <h3 style={{ fontSize: 17, marginBottom: 4 }}>Credenciais de integração</h3>
            <p style={{ fontSize: 13, marginBottom: 18 }}>Usadas pelo agente OpenClaw desta empresa para autenticar no CRM.</p>
            <label>
              Chave de API
              <div className="api-key-row">
                <input readOnly value="sk_live_••••••••••••7f3a" />
                <button className="secondary" type="button" disabled>
                  Copiar
                </button>
              </div>
            </label>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <button type="button" disabled>
                Gerar nova chave
              </button>
              <button className="danger-outline" type="button" disabled>
                Revogar
              </button>
            </div>
            <p style={{ fontSize: 12, marginTop: 14, color: 'var(--muted)' }}>
              Protótipo visual: requer um campo de chave por empresa e um endpoint de rotação no backend antes de funcionar de verdade.
            </p>
          </div>

          <div className="section-divider" />

          <div>
            <h3 style={{ fontSize: 15, marginBottom: 10 }}>Vínculo com o Gateway OpenClaw</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13 }}>
              <div className="kv-row">
                <span style={{ color: 'var(--muted)' }}>Tenant</span>
                <strong style={{ fontFamily: "'DM Mono',monospace" }}>oliveira-advogados</strong>
              </div>
              <div className="kv-row">
                <span style={{ color: 'var(--muted)' }}>Porta local</span>
                <strong style={{ fontFamily: "'DM Mono',monospace" }}>18802</strong>
              </div>
              <div className="kv-row">
                <span style={{ color: 'var(--muted)' }}>Webhook</span>
                <strong style={{ fontFamily: "'DM Mono',monospace", fontSize: '12.5px' }}>/api/companies/14/incoming/</strong>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
