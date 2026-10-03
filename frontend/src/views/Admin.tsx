import { useEffect, useState } from 'react';
import { Logo } from '../components/Logo';
import { Spinner, SkeletonCards } from '../components/Skeleton';
import type { Api } from '../api';
import type { AdminCompany, AgentStatus } from '../types';

/**
 * Painel Admin interno da Axioma: cadastro de empresas e token de API do
 * agente, cross-tenant de propósito (restrito a is_superuser no backend —
 * ver crm.views.IsSuperUser). Única tela do sistema com essa visão.
 */
export function Admin({ api, onLogout, onBackToCrm }: { api: Api; onLogout: () => void; onBackToCrm?: () => void }) {
  const [companies, setCompanies] = useState<AdminCompany[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [creating, setCreating] = useState(false);
  const [savingCompany, setSavingCompany] = useState(false);

  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null);
  const [agentBusy, setAgentBusy] = useState(false);
  const [agentError, setAgentError] = useState('');
  const [validadeDias, setValidadeDias] = useState(180);
  const [generatedKey, setGeneratedKey] = useState<string | null>(null);

  const selected = companies.find((c) => c.id === selectedId) || null;

  function loadCompanies() {
    setBusy(true);
    setError('');
    api('/admin-companies/')
      .then((d: { results: AdminCompany[] }) => setCompanies(d.results))
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }

  useEffect(() => {
    loadCompanies();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setGeneratedKey(null);
    setAgentError('');
    if (!selected) {
      setAgentStatus(null);
      return;
    }
    setAgentBusy(true);
    api(`/admin-companies/${selected.id}/agente/`)
      .then((d: AgentStatus) => setAgentStatus(d))
      .catch((e) => setAgentError(e.message))
      .finally(() => setAgentBusy(false));
  }, [selectedId]);

  async function createCompany(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSavingCompany(true);
    setError('');
    const form = new FormData(e.currentTarget);
    try {
      const created = await api('/admin-companies/', {
        method: 'POST',
        body: JSON.stringify({
          name: form.get('name'),
          initial_state: form.get('initial_state') || 'apresentacao',
          default_owner: form.get('default_owner') || '',
          allow_transcription: form.get('allow_transcription') === 'on',
        }),
      });
      setCompanies((v) => [...v, created].sort((a, b) => a.name.localeCompare(b.name)));
      setSelectedId(created.id);
      setCreating(false);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingCompany(false);
    }
  }

  async function saveCompany(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!selected) return;
    setSavingCompany(true);
    setError('');
    const form = new FormData(e.currentTarget);
    try {
      const updated = await api(`/admin-companies/${selected.id}/`, {
        method: 'PATCH',
        body: JSON.stringify({
          name: form.get('name'),
          initial_state: form.get('initial_state'),
          default_owner: form.get('default_owner'),
          allow_transcription: form.get('allow_transcription') === 'on',
        }),
      });
      setCompanies((v) => v.map((c) => (c.id === updated.id ? { ...c, ...updated } : c)));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingCompany(false);
    }
  }

  async function gerarToken() {
    if (!selected) return;
    if (agentStatus?.masked_key && !window.confirm('Já existe uma chave ativa para esta empresa. Gerar uma nova vai invalidar a atual imediatamente. Continuar?')) return;
    setAgentBusy(true);
    setAgentError('');
    try {
      const data = await api(`/admin-companies/${selected.id}/agente/`, { method: 'POST', body: JSON.stringify({ validade_dias: validadeDias }) });
      setGeneratedKey(data.token);
      const status = await api(`/admin-companies/${selected.id}/agente/`);
      setAgentStatus(status);
      setCompanies((v) => v.map((c) => (c.id === selected.id ? { ...c, tem_agente_ativo: true } : c)));
    } catch (err) {
      setAgentError((err as Error).message);
    } finally {
      setAgentBusy(false);
    }
  }

  async function revogarToken() {
    if (!selected) return;
    if (!window.confirm('Revogar a chave desta empresa? O agente para de conseguir chamar a API imediatamente.')) return;
    setAgentBusy(true);
    setAgentError('');
    try {
      await api(`/admin-companies/${selected.id}/agente/`, { method: 'DELETE' });
      setGeneratedKey(null);
      const status = await api(`/admin-companies/${selected.id}/agente/`);
      setAgentStatus(status);
      setCompanies((v) => v.map((c) => (c.id === selected.id ? { ...c, tem_agente_ativo: false } : c)));
    } catch (err) {
      setAgentError((err as Error).message);
    } finally {
      setAgentBusy(false);
    }
  }

  const visible = companies.filter((c) => c.name.toLowerCase().includes(search.toLowerCase()));

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
          {onBackToCrm && (
            <button className="secondary" onClick={onBackToCrm}>
              Voltar ao CRM
            </button>
          )}
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
            <button onClick={() => setCreating((v) => !v)}>{creating ? 'Cancelar' : '+ Nova empresa'}</button>
          </div>

          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}

          {creating && (
            <form onSubmit={createCompany} className="panel" style={{ padding: 20, display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end' }}>
              <label style={{ margin: 0, flex: '1 1 220px' }}>
                Nome da empresa
                <input name="name" required />
              </label>
              <label style={{ margin: 0, flex: '1 1 180px' }}>
                question_id inicial
                <input name="initial_state" defaultValue="apresentacao" />
              </label>
              <label style={{ margin: 0, flex: '1 1 180px' }}>
                Responsável padrão
                <input name="default_owner" />
              </label>
              <label style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 6, fontWeight: 500 }}>
                <input type="checkbox" name="allow_transcription" style={{ width: 'auto' }} /> Permite transcrição de áudio
              </label>
              <button disabled={savingCompany}>
                {savingCompany && <Spinner />}
                Criar empresa
              </button>
            </form>
          )}

          <input placeholder="Buscar empresa" aria-label="Buscar empresa" style={{ maxWidth: 320 }} value={search} onChange={(e) => setSearch(e.target.value)} />

          <section className="panel">
            {busy && !companies.length ? (
              <div style={{ padding: 20 }}>
                <SkeletonCards count={3} height={60} />
              </div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Empresa</th>
                      <th>Atendentes</th>
                      <th>Agente</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((c) => (
                      <tr
                        key={c.id}
                        className={c.id === selectedId ? 'company-row-active' : ''}
                        onClick={() => setSelectedId(c.id)}
                        style={{ cursor: 'pointer' }}
                      >
                        <td style={{ fontWeight: 600 }}>{c.name}</td>
                        <td style={{ fontFamily: "'DM Mono',monospace" }}>{c.member_count}</td>
                        <td>
                          <span className={`badge ${c.tem_agente_ativo ? 'status-active' : 'status-pending'}`}>
                            {c.tem_agente_ativo ? 'Ativo' : 'Sem agente'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!visible.length && <div className="empty">Nenhuma empresa encontrada.</div>}
              </div>
            )}
          </section>
        </main>

        <aside className="admin-detail">
          {!selected ? (
            <div className="empty">Selecione uma empresa na lista para ver os detalhes.</div>
          ) : (
            <form key={selected.id} onSubmit={saveCompany}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                <h2 style={{ fontSize: 21 }}>{selected.name}</h2>
                <span className={`badge ${selected.tem_agente_ativo ? 'status-active' : 'status-pending'}`}>
                  {selected.tem_agente_ativo ? 'Agente ativo' : 'Sem agente'}
                </span>
              </div>
              <p style={{ fontSize: '13.5px', marginBottom: 18 }}>{selected.member_count} atendente(s) vinculado(s).</p>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
                <label>
                  Nome
                  <input name="name" defaultValue={selected.name} />
                </label>
                <label>
                  question_id inicial
                  <input name="initial_state" defaultValue={selected.initial_state} style={{ fontFamily: "'DM Mono',monospace", fontSize: 13 }} />
                </label>
                <label>
                  Responsável padrão
                  <input name="default_owner" defaultValue={selected.default_owner} />
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 20 }}>
                  <input type="checkbox" name="allow_transcription" defaultChecked={selected.allow_transcription} style={{ width: 'auto' }} /> Permite transcrição
                </label>
              </div>
              <button disabled={savingCompany} style={{ marginTop: 12 }}>
                {savingCompany && <Spinner />}
                Salvar
              </button>

              <div className="section-divider" />

              <div>
                <h3 style={{ fontSize: 17, marginBottom: 4 }}>Credenciais de integração</h3>
                <p style={{ fontSize: 13, marginBottom: 14 }}>Usadas pelo agente Axioma desta empresa para autenticar no Conecta CRM.</p>

                {agentError && <p className="error">{agentError}</p>}

                {generatedKey ? (
                  <div style={{ background: 'var(--warn-soft)', border: '1px solid var(--warn)', borderRadius: 10, padding: 14, marginBottom: 14 }}>
                    <strong style={{ fontSize: 13 }}>Copie agora — essa chave não aparece de novo:</strong>
                    <div className="api-key-row">
                      <input readOnly value={generatedKey} onFocus={(e) => e.currentTarget.select()} />
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => navigator.clipboard?.writeText(generatedKey)}
                      >
                        Copiar
                      </button>
                    </div>
                  </div>
                ) : (
                  <label>
                    Chave de API
                    <div className="api-key-row">
                      <input readOnly value={agentStatus?.masked_key || 'Nenhuma chave gerada ainda'} />
                    </div>
                  </label>
                )}

                {agentStatus?.validade && (
                  <p style={{ fontSize: 12.5, color: agentStatus.validade.expirado ? 'var(--danger)' : 'var(--muted)', marginTop: 4 }}>
                    {agentStatus.validade.expirado ? 'Expirada em ' : 'Válida até '}
                    {new Date(agentStatus.validade.expires_at).toLocaleDateString('pt-BR')}
                  </p>
                )}

                <label style={{ marginTop: 10 }}>
                  Validade da nova chave (dias)
                  <input
                    type="number"
                    min={1}
                    max={730}
                    value={validadeDias}
                    onChange={(e) => setValidadeDias(Number(e.target.value))}
                    style={{ fontFamily: "'DM Mono',monospace" }}
                  />
                </label>
                <small style={{ display: 'block', color: 'var(--muted)', marginBottom: 12 }}>Padrão 180 dias (6 meses) — máximo 730 (2 anos).</small>

                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  <button type="button" onClick={gerarToken} disabled={agentBusy}>
                    {agentBusy && <Spinner />}
                    Gerar nova chave
                  </button>
                  <button type="button" className="danger-outline" onClick={revogarToken} disabled={agentBusy || !agentStatus?.masked_key}>
                    Revogar
                  </button>
                </div>
              </div>

              <div className="section-divider" />

              <div>
                <h3 style={{ fontSize: 15, marginBottom: 10 }}>Integração com a API</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13 }}>
                  <div className="kv-row">
                    <span style={{ color: 'var(--muted)' }}>Usuário de serviço</span>
                    <strong style={{ fontFamily: "'DM Mono',monospace" }}>{agentStatus?.username}</strong>
                  </div>
                  <div className="kv-row">
                    <span style={{ color: 'var(--muted)' }}>Webhook (incoming)</span>
                    <strong style={{ fontFamily: "'DM Mono',monospace", fontSize: '12.5px' }}>/api/companies/{selected.id}/incoming/</strong>
                  </div>
                  <div className="kv-row">
                    <span style={{ color: 'var(--muted)' }}>Confirmação de entrega</span>
                    <strong style={{ fontFamily: "'DM Mono',monospace", fontSize: '12.5px' }}>/api/companies/{selected.id}/delivery/</strong>
                  </div>
                </div>
              </div>
            </form>
          )}
        </aside>
      </div>
    </div>
  );
}
