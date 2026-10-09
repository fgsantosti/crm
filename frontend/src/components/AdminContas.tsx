import { useCallback, useEffect, useState } from 'react';
import type { Api } from '../api';
import type { ContaEmpresa, ContasDaEmpresa } from '../types';
import { Spinner } from './Skeleton';
import { ConfirmPessoa, useConfirmar } from './ConfirmDialog';

type Credencial = { titulo: string; email: string; senha: string; emailEnviado: boolean };

/**
 * Painel Admin → seletor da empresa: contas "Empresa" (login humano do cliente no painel) e
 * outras contas de agente da mesma empresa. A conta principal do agente (vínculo e chave)
 * fica no bloco "Credenciais de integração" de Admin.tsx. Sem <form>: este componente vive
 * ao lado do formulário da empresa, e Enter aqui nunca pode salvá-la.
 */
export function AdminContas({ api, companyId, companyName }: { api: Api; companyId: number; companyName: string }) {
  const confirmar = useConfirmar();
  const [dados, setDados] = useState<ContasDaEmpresa | null>(null);
  const [erro, setErro] = useState('');
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState('');
  const [nome, setNome] = useState('');
  const [credencial, setCredencial] = useState<Credencial | null>(null);
  const base = `/admin-companies/${companyId}`;

  const carregar = useCallback(() => {
    return api(`${base}/contas/`)
      .then((d: ContasDaEmpresa) => setDados(d))
      .catch((e) => setErro(e.message));
  }, [api, base]);

  useEffect(() => {
    setDados(null);
    setErro('');
    setCredencial(null);
    setEmail('');
    setNome('');
    carregar();
  }, [carregar]);

  async function executar(fn: () => Promise<void>) {
    setBusy(true);
    setErro('');
    try {
      await fn();
      await carregar();
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const criar = () =>
    executar(async () => {
      const r = await api(`${base}/contas/empresa/`, { method: 'POST', body: JSON.stringify({ email, nome }) });
      setCredencial({ titulo: 'Conta criada', email: r.conta.email, senha: r.senha_provisoria, emailEnviado: r.email_enviado });
      setEmail('');
      setNome('');
    });

  const redefinir = async (c: ContaEmpresa) => {
    if (!(await confirmar({ titulo: 'Gerar uma nova senha provisória?', mensagem: 'A senha atual deixa de valer e a pessoa terá de trocá-la no próximo acesso.', detalhe: <ConfirmPessoa nome={c.display_name || c.email} sub={c.email} />, tom: 'atencao', icone: 'chave', confirmar: 'Gerar nova senha' }))) return;
    return executar(async () => {
      const r = await api(`${base}/contas/empresa/${c.id}/redefinir-senha/`, { method: 'POST' });
      setCredencial({ titulo: 'Nova senha gerada', email: c.email, senha: r.senha_provisoria, emailEnviado: r.email_enviado });
    });
  };

  const alternar = async (c: ContaEmpresa) => {
    if (c.is_active && !(await confirmar({ titulo: 'Desativar este login?', mensagem: 'A pessoa não consegue mais entrar; dá para reativar depois.', detalhe: <ConfirmPessoa nome={c.display_name || c.email} sub={c.email} />, tom: 'atencao', icone: 'pessoa', confirmar: 'Desativar login' }))) return;
    return executar(async () => {
      await api(`${base}/contas/empresa/${c.id}/`, { method: 'PATCH', body: JSON.stringify({ is_active: !c.is_active }) });
    });
  };

  const revogarExtra = async (id: number, username: string) => {
    if (!(await confirmar({ titulo: 'Revogar esta chave?', mensagem: 'Quem usar essa chave perde o acesso à API na hora.', detalhe: <ConfirmPessoa nome={username} />, tom: 'perigo', icone: 'chave', confirmar: 'Revogar chave' }))) return;
    return executar(async () => {
      await api(`${base}/agente/?user_id=${id}`, { method: 'DELETE' });
    });
  };

  return (
    <>
      <div>
        <h3 style={{ fontSize: 17, marginBottom: 4 }}>Contas Empresa</h3>
        <p style={{ fontSize: 13, marginBottom: 14 }}>Logins humanos do cliente no painel de {companyName}. A senha provisória exige troca no primeiro acesso.</p>

        {erro && (
          <p role="alert" className="error">
            {erro}
          </p>
        )}

        {credencial && (
          <div style={{ background: 'var(--warn-soft)', border: '1px solid var(--warn)', borderRadius: 10, padding: 14, marginBottom: 14 }}>
            <strong style={{ fontSize: 13 }}>{credencial.titulo} — copie agora, a senha não aparece de novo:</strong>
            <div className="kv-row" style={{ marginTop: 8, fontSize: 13 }}>
              <span style={{ color: 'var(--muted)' }}>Login</span>
              <strong style={{ fontFamily: "'DM Mono',monospace" }}>{credencial.email}</strong>
            </div>
            <div className="api-key-row">
              <input readOnly aria-label="Senha provisória" value={credencial.senha} onFocus={(e) => e.currentTarget.select()} />
              <button type="button" className="secondary" onClick={() => navigator.clipboard?.writeText(credencial.senha)}>
                Copiar
              </button>
            </div>
            <p style={{ fontSize: 12.5, marginTop: 8, color: credencial.emailEnviado ? 'var(--muted)' : 'var(--danger)' }}>
              {credencial.emailEnviado ? 'O e-mail com as credenciais foi enviado.' : 'O e-mail NÃO foi enviado: repasse o login e a senha acima por outro canal.'}
            </p>
            <button type="button" className="secondary" onClick={() => setCredencial(null)}>
              Fechar
            </button>
          </div>
        )}

        {!dados ? (
          <p style={{ fontSize: 13 }}>Carregando…</p>
        ) : dados.empresa.length === 0 ? (
          <p style={{ fontSize: 13, color: 'var(--muted)' }}>Nenhuma conta Empresa nesta empresa ainda.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {dados.empresa.map((c) => (
              <div key={c.id} className="kv-row" style={{ alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
                <div style={{ minWidth: 0 }}>
                  <strong style={{ fontSize: 13.5, wordBreak: 'break-all' }}>{c.email || c.username}</strong>
                  {c.display_name && <div style={{ fontSize: 12.5, color: 'var(--muted)' }}>{c.display_name}</div>}
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
                    <span className={`badge ${c.is_active ? 'status-active' : 'status-pending'}`}>{c.is_active ? 'Ativa' : 'Desativada'}</span>
                    {c.must_change_password && <span className="badge status-pending">Troca de senha pendente</span>}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
                    {c.last_login ? `Último acesso: ${new Date(c.last_login).toLocaleString('pt-BR')}` : 'Nunca acessou'}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <button type="button" className="secondary" disabled={busy} onClick={() => redefinir(c)}>
                    Nova senha
                  </button>
                  <button type="button" className={c.is_active ? 'danger-outline' : 'secondary'} disabled={busy} onClick={() => alternar(c)}>
                    {c.is_active ? 'Desativar' : 'Reativar'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 14 }}>
          <label style={{ margin: 0 }}>
            E-mail do login
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  if (email.trim() && !busy) criar();
                }
              }}
              placeholder="dono@empresa.com"
              autoComplete="off"
            />
          </label>
          <label style={{ margin: 0 }}>
            Nome (opcional)
            <input value={nome} onChange={(e) => setNome(e.target.value)} autoComplete="off" />
          </label>
        </div>
        <button type="button" onClick={criar} disabled={busy || !email.trim()} style={{ marginTop: 10 }}>
          {busy && <Spinner />}
          Criar conta Empresa
        </button>
      </div>

      {dados && dados.agentes_extras.length > 0 && (
        <>
          <div className="section-divider" />
          <div>
            <h3 style={{ fontSize: 15, marginBottom: 4 }}>Outras contas de agente desta empresa</h3>
            <p style={{ fontSize: 13, marginBottom: 12 }}>Contas antigas ou duplicadas com acesso a esta empresa. Revogue a chave das que não são mais usadas.</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {dados.agentes_extras.map((a) => (
                <div key={a.id ?? a.username} className="kv-row" style={{ alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                  <div>
                    <strong style={{ fontFamily: "'DM Mono',monospace", fontSize: 13 }}>{a.username}</strong>
                    <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>
                      {a.masked_key ? `Chave ${a.masked_key}` : 'Sem chave'}
                      {a.validade && ` · ${a.validade.expirado ? 'expirada em' : 'válida até'} ${new Date(a.validade.expires_at).toLocaleDateString('pt-BR')}`}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="danger-outline"
                    disabled={busy || !a.masked_key || a.id == null}
                    onClick={() => a.id != null && revogarExtra(a.id, a.username)}
                  >
                    Revogar chave
                  </button>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </>
  );
}
