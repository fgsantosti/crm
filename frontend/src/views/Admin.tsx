import { useEffect, useState } from 'react';
import { Spinner, SkeletonCards } from '../components/Skeleton';
import { fetchTodasAsPaginas, type Api } from '../api';
import { AdminContas } from '../components/AdminContas';
import type { AdminCompany, AgentStatus } from '../types';

/**
 * Painel Admin interno da Axioma: cadastro de empresas e token de API do
 * agente, cross-tenant de propósito (restrito a is_superuser no backend —
 * ver crm.views.IsSuperUser). Uma das 3 abas do workspace do admin geral
 * (ver AdminShell) -- sem header próprio, o shell cuida de navegação/logout.
 */
export function Admin({ api }: { api: Api }) {
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

  const [confirmDelete, setConfirmDelete] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  const selected = companies.find((c) => c.id === selectedId) || null;

  function loadCompanies() {
    setBusy(true);
    setError('');
    fetchTodasAsPaginas<AdminCompany>(api, '/admin-companies/')
      .then(setCompanies)
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
    setConfirmDelete('');
    setDeleteError('');
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
          numero_agente: form.get('numero_agente') || '',
          allow_transcription: form.get('allow_transcription') === 'on',
          coletar_historico_conversa: form.get('coletar_historico_conversa') === 'on',
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
          numero_agente: form.get('numero_agente'),
          allow_transcription: form.get('allow_transcription') === 'on',
          coletar_historico_conversa: form.get('coletar_historico_conversa') === 'on',
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

  async function religarAgente() {
    if (!selected) return;
    setAgentBusy(true);
    setAgentError('');
    try {
      await api(`/admin-companies/${selected.id}/contas/agente/vincular/`, { method: 'POST' });
      const status = await api(`/admin-companies/${selected.id}/agente/`);
      setAgentStatus(status);
      setCompanies((v) => v.map((c) => (c.id === selected.id ? { ...c, tem_agente_ativo: Boolean(status.masked_key && status.ativa && !status.validade?.expirado) } : c)));
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

  async function excluirEmpresa() {
    if (!selected || confirmDelete.trim() !== selected.name.trim()) return;
    setDeleting(true);
    setDeleteError('');
    try {
      await api(`/admin-companies/${selected.id}/`, { method: 'DELETE', body: JSON.stringify({ confirmar_nome: confirmDelete.trim() }) });
      setCompanies((v) => v.filter((c) => c.id !== selected.id));
      setSelectedId(null);
    } catch (err) {
      setDeleteError((err as Error).message);
    } finally {
      setDeleting(false);
    }
  }

  const visible = companies.filter((c) => c.name.toLowerCase().includes(search.toLowerCase()));

  return (
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
                Número do agente (WhatsApp)
                <input name="numero_agente" placeholder="+5586999999999" inputMode="tel" />
                <small style={{ display: 'block', fontWeight: 400, color: 'var(--muted)', marginTop: 4 }}>Número conectado ao agente. Normalmente é o mesmo número em que a equipe faz os atendimentos.</small>
              </label>
              <label style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 6, fontWeight: 500 }}>
                <input type="checkbox" name="allow_transcription" style={{ width: 'auto' }} /> Habilitar áudio (transcrição/voz)
              </label>
              <label style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 6, fontWeight: 500 }}>
                <input type="checkbox" name="coletar_historico_conversa" style={{ width: 'auto' }} /> Permitir coleta de histórico de conversa
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
                      <th>Contas</th>
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
            <div key={selected.id}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                <h2 style={{ fontSize: 21 }}>{selected.name}</h2>
                <span className={`badge ${selected.tem_agente_ativo ? 'status-active' : 'status-pending'}`}>
                  {selected.tem_agente_ativo ? 'Agente ativo' : 'Sem agente'}
                </span>
              </div>
              <p style={{ fontSize: '13.5px', marginBottom: 18 }}>{selected.member_count} conta(s) vinculada(s).</p>

              <form onSubmit={saveCompany}>
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
                  Número do agente (WhatsApp)
                  <input name="numero_agente" defaultValue={selected.numero_agente} placeholder="+5586999999999" inputMode="tel" />
                  <small style={{ display: 'block', fontWeight: 400, color: 'var(--muted)', marginTop: 4 }}>Número conectado ao agente. Normalmente é o mesmo número em que a equipe faz os atendimentos.</small>
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 20 }}>
                  <input type="checkbox" name="allow_transcription" defaultChecked={selected.allow_transcription} style={{ width: 'auto' }} /> Habilitar áudio (transcrição/voz)
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 20 }}>
                  <input type="checkbox" name="coletar_historico_conversa" defaultChecked={selected.coletar_historico_conversa} style={{ width: 'auto' }} /> Permitir coleta de histórico de conversa
                </label>
              </div>
              <button disabled={savingCompany} style={{ marginTop: 12 }}>
                {savingCompany && <Spinner />}
                Salvar
              </button>
              </form>

              <div className="section-divider" />

              <div>
                <h3 style={{ fontSize: 17, marginBottom: 4 }}>Credenciais de integração</h3>
                <p style={{ fontSize: 13, marginBottom: 14 }}>Usadas pelo agente Axioma desta empresa para autenticar no Conecta CRM.</p>

                {agentError && <p className="error">{agentError}</p>}

                {agentStatus?.existe && (
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
                    <span className={`badge ${agentStatus.vinculada ? 'status-active' : 'status-pending'}`}>{agentStatus.vinculada ? 'Conta vinculada à empresa' : 'Conta SEM vínculo'}</span>
                    <span className={`badge ${agentStatus.ativa ? 'status-active' : 'status-pending'}`}>{agentStatus.ativa ? 'Conta ativa' : 'Conta desativada'}</span>
                    {!agentStatus.vinculada && (
                      <button type="button" className="secondary" onClick={religarAgente} disabled={agentBusy}>
                        Religar à empresa
                      </button>
                    )}
                  </div>
                )}
                {agentStatus?.existe && !agentStatus.vinculada && (
                  <p className="error" style={{ fontSize: 12.5 }}>Sem vínculo, o agente recebe 404 em todas as chamadas ao CRM, mesmo com a chave válida.</p>
                )}

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

              <AdminContas api={api} companyId={selected.id} companyName={selected.name} />

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

              <div className="section-divider" />

              <div>
                <h3 style={{ fontSize: 15, marginBottom: 4, color: 'var(--danger)' }}>Excluir empresa</h3>
                <p style={{ fontSize: 13, marginBottom: 10 }}>
                  Apaga a empresa e tudo que é dela: leads, histórico, roteiro, variáveis, áreas, dados da empresa e a chave do agente.
                  Contas que pertencem só a esta empresa também são excluídas. Não dá para desfazer.
                </p>
                {deleteError && <p className="error">{deleteError}</p>}
                <label>
                  Digite <strong>{selected.name}</strong> para confirmar
                  <input value={confirmDelete} onChange={(e) => setConfirmDelete(e.target.value)} autoComplete="off" />
                </label>
                <button
                  type="button"
                  className="danger-outline"
                  onClick={excluirEmpresa}
                  disabled={deleting || confirmDelete.trim() !== selected.name.trim()}
                  style={{ marginTop: 10 }}
                >
                  {deleting && <Spinner />}
                  Excluir empresa definitivamente
                </button>
              </div>
            </div>
          )}
        </aside>
    </div>
  );
}
