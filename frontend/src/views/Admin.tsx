import { useEffect, useState } from 'react';
import { Spinner, SkeletonCards } from '../components/Skeleton';
import { fetchTodasAsPaginas, type Api } from '../api';
import { AdminContas } from '../components/AdminContas';
import type { AdminCompany, AgentStatus } from '../types';
import { useConfirmar } from '../components/ConfirmDialog';

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

  const confirmar = useConfirmar();
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
    if (agentStatus?.masked_key && !(await confirmar({
      titulo: 'Gerar nova chave do agente?',
      mensagem: 'Já existe uma chave ativa para esta empresa. Ao gerar outra, a atual deixa de valer na hora e o agente fica sem acesso ao CRM até receber a nova.',
      detalhe: (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <code>{agentStatus.masked_key}</code>
          {agentStatus.validade && <small>{agentStatus.validade.expirado ? 'expirada em ' : 'válida até '}{new Date(agentStatus.validade.expires_at).toLocaleDateString('pt-BR')}</small>}
        </div>
      ),
      tom: 'atencao',
      icone: 'chave',
      confirmar: 'Gerar nova chave',
    }))) return;
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
    if (!(await confirmar({ titulo: 'Revogar a chave desta empresa?', mensagem: 'O agente para de conseguir chamar a API imediatamente.', tom: 'perigo', icone: 'chave', confirmar: 'Revogar chave' }))) return;
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

  const visible = companies.filter((c) => `${c.name} ${c.gestor_nome ?? ''}`.toLowerCase().includes(search.toLowerCase()));

  const formularioCriar = creating && (
    <form onSubmit={createCompany} className="dash-card adm-form-nova">
      <label>
        Nome da empresa
        <input name="name" required />
      </label>
      <label>
        question_id inicial
        <input name="initial_state" defaultValue="apresentacao" />
      </label>
      <label>
        Número do agente (WhatsApp)
        <input name="numero_agente" placeholder="+5586999999999" inputMode="tel" />
        <small>Número conectado ao agente. Normalmente é o mesmo número em que a equipe faz os atendimentos.</small>
      </label>
      <label className="adm-check">
        <input type="checkbox" name="allow_transcription" /> Habilitar áudio (transcrição/voz)
      </label>
      <label className="adm-check">
        <input type="checkbox" name="coletar_historico_conversa" /> Permitir coleta de histórico de conversa
      </label>
      <div className="cob-acoes">
        <button type="button" className="secondary" onClick={() => setCreating(false)}>
          Cancelar
        </button>
        <button disabled={savingCompany}>
          {savingCompany && <Spinner />}
          Criar empresa
        </button>
      </div>
    </form>
  );

  if (!selected) {
    return (
      <>
        <header className="page-header" style={{ alignItems: 'flex-end' }}>
          <div>
            <small className="eyebrow">Plataforma</small>
            <h1>Empresas</h1>
            <p>Cada empresa com o gestor, o agente e a situação. Visível apenas para a equipe Axioma.</p>
          </div>
          <div className="adm-filtros">
            <input placeholder="Buscar empresa ou gestor" aria-label="Buscar empresa" style={{ width: 260 }} value={search} onChange={(e) => setSearch(e.target.value)} />
            <button onClick={() => setCreating((v) => !v)}>{creating ? 'Cancelar' : '+ Nova empresa'}</button>
          </div>
        </header>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {formularioCriar}
        {busy && !companies.length ? (
          <SkeletonCards count={3} height={110} />
        ) : (
          <section className="adm-empresas" aria-label="Empresas">
            {visible.map((c) => (
              <button key={c.id} type="button" className="dash-card adm-empresa" onClick={() => setSelectedId(c.id)}>
                <span className="adm-empresa-topo">
                  <strong>{c.name}</strong>
                  <span className={`badge ${c.tem_agente_ativo ? 'status-active' : 'status-pending'}`}>{c.tem_agente_ativo ? 'Agente ativo' : 'Sem agente'}</span>
                </span>
                <small>{c.gestor_nome ? `Gestor: ${c.gestor_nome}` : 'Sem gestor vinculado'}</small>
                <span className="adm-empresa-rodape">
                  <span>{c.member_count} conta(s)</span>
                  {c.teste?.em_teste && <span className="dash-selo" style={{ background: '#E3ECFD', color: '#1D4FBF' }}>Em teste · {c.teste.situacao}</span>}
                  <span className="adm-link">Abrir →</span>
                </span>
              </button>
            ))}
            {!visible.length && <div className="empty">Nenhuma empresa encontrada.</div>}
          </section>
        )}
      </>
    );
  }

  return (
    <div key={selected.id} className="adm-detalhe-empresa">
      <nav className="adm-caminho" aria-label="Caminho">
        <button type="button" className="adm-link" onClick={() => setSelectedId(null)}>Empresas</button>
        <span aria-hidden="true">/</span>
        <span>{selected.name}</span>
      </nav>

      <section className="dash-card adm-cabecalho">
        <div>
          <div className="adm-titulo-linha">
            <h1>{selected.name}</h1>
            <span className={`badge ${selected.tem_agente_ativo ? 'status-active' : 'status-pending'}`}>{selected.tem_agente_ativo ? 'Agente ativo' : 'Sem agente'}</span>
            {selected.teste?.em_teste && <span className="dash-selo" style={{ background: '#E3ECFD', color: '#1D4FBF' }}>Em teste · {selected.teste.situacao}</span>}
          </div>
          <p>{selected.member_count} conta(s) vinculada(s){selected.gestor_nome ? ` · gestor ${selected.gestor_nome}` : ' · sem gestor'}</p>
        </div>
      </section>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <div className="dash-duas">
        <section className="dash-card" aria-labelledby="emp-agente">
          <div>
            <h2 id="emp-agente">Credenciais do agente</h2>
            <small>Usadas pelo agente Axioma desta empresa para autenticar no Conecta CRM.</small>
          </div>
          {agentError && <p className="error">{agentError}</p>}
          {agentStatus?.existe && (
            <div className="adm-selos">
              <span className={`badge ${agentStatus.vinculada ? 'status-active' : 'status-pending'}`}>{agentStatus.vinculada ? 'Conta vinculada à empresa' : 'Conta SEM vínculo'}</span>
              <span className={`badge ${agentStatus.ativa ? 'status-active' : 'status-pending'}`}>{agentStatus.ativa ? 'Conta ativa' : 'Conta desativada'}</span>
              {!agentStatus.vinculada && (
                <button type="button" className="secondary" onClick={religarAgente} disabled={agentBusy}>
                  Religar à empresa
                </button>
              )}
            </div>
          )}
          {agentStatus?.existe && !agentStatus.vinculada && <p className="error">Sem vínculo, o agente recebe 404 em todas as chamadas ao CRM, mesmo com a chave válida.</p>}

          {generatedKey ? (
            <div className="adm-chave-nova">
              <strong>Copie agora — essa chave não aparece de novo:</strong>
              <div className="api-key-row">
                <input readOnly value={generatedKey} onFocus={(e) => e.currentTarget.select()} />
                <button type="button" className="secondary" onClick={() => navigator.clipboard?.writeText(generatedKey)}>
                  Copiar
                </button>
              </div>
            </div>
          ) : (
            <label>
              Chave de API do CRM
              <div className="api-key-row">
                <input readOnly value={agentStatus?.masked_key || 'Nenhuma chave gerada ainda'} />
              </div>
            </label>
          )}
          {agentStatus?.validade && (
            <p className="dash-nota" style={{ color: agentStatus.validade.expirado ? 'var(--danger)' : undefined }}>
              {agentStatus.validade.expirado ? 'Expirada em ' : 'Válida até '}
              {new Date(agentStatus.validade.expires_at).toLocaleDateString('pt-BR')}
            </p>
          )}
          <label>
            Validade da nova chave (dias)
            <input type="number" min={1} max={730} value={validadeDias} onChange={(e) => setValidadeDias(Number(e.target.value))} style={{ fontFamily: "'DM Mono',monospace" }} />
            <small>Padrão 180 dias (6 meses) — máximo 730 (2 anos).</small>
          </label>
          <div className="cob-acoes" style={{ justifyContent: 'flex-start' }}>
            <button type="button" onClick={gerarToken} disabled={agentBusy}>
              {agentBusy && <Spinner />}
              Gerar nova chave
            </button>
            <button type="button" className="danger-outline" onClick={revogarToken} disabled={agentBusy || !agentStatus?.masked_key}>
              Revogar
            </button>
          </div>
          <div className="adm-kv">
            <div><span>Usuário de serviço</span><strong>{agentStatus?.username}</strong></div>
            <div><span>Webhook (incoming)</span><strong>/api/companies/{selected.id}/incoming/</strong></div>
            <div><span>Confirmação de entrega</span><strong>/api/companies/{selected.id}/delivery/</strong></div>
          </div>
        </section>

        <section className="dash-card" aria-labelledby="emp-dados">
          <div>
            <h2 id="emp-dados">Dados e portões da empresa</h2>
            <small>Os portões liberam recursos que a empresa pode ligar por conta própria.</small>
          </div>
          <form onSubmit={saveCompany} className="adm-form-dados">
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
              <small>Mensagens deste número nunca abrem lead.</small>
            </label>
            <label className="adm-check">
              <input type="checkbox" name="allow_transcription" defaultChecked={selected.allow_transcription} /> Habilitar áudio (transcrição/voz)
            </label>
            <label className="adm-check">
              <input type="checkbox" name="coletar_historico_conversa" defaultChecked={selected.coletar_historico_conversa} /> Permitir coleta de histórico de conversa
            </label>
            <div className="cob-acoes">
              <button disabled={savingCompany}>
                {savingCompany && <Spinner />}
                Salvar
              </button>
            </div>
          </form>
        </section>
      </div>

      <section className="dash-card" aria-labelledby="emp-contas">
        <h2 id="emp-contas" className="sr-only">Contas da empresa</h2>
        <AdminContas api={api} companyId={selected.id} companyName={selected.name} />
      </section>

      <section className="dash-card adm-risco" aria-labelledby="emp-risco">
        <div>
          <h2 id="emp-risco" style={{ color: 'var(--danger)' }}>Zona de risco</h2>
          <p className="dash-nota">
            Excluir apaga a empresa e tudo que é dela: leads, histórico, roteiro, variáveis, áreas, dados da empresa e a chave do agente. Contas que pertencem só a esta empresa também são excluídas. Não dá para desfazer.
          </p>
        </div>
        {deleteError && <p className="error">{deleteError}</p>}
        <label>
          Digite <strong>{selected.name}</strong> para confirmar
          <input value={confirmDelete} onChange={(e) => setConfirmDelete(e.target.value)} autoComplete="off" />
        </label>
        <div className="cob-acoes" style={{ justifyContent: 'flex-start' }}>
          <button type="button" className="danger-outline" onClick={excluirEmpresa} disabled={deleting || confirmDelete.trim() !== selected.name.trim()}>
            {deleting && <Spinner />}
            Excluir empresa definitivamente
          </button>
        </div>
      </section>
    </div>
  );
}
