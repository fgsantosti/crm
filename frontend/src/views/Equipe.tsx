import { useEffect, useState } from 'react';
import type { Api } from '../api';
import type { AtendenteInvite, Company, EquipeMembro, Paginated } from '../types';
import { SkeletonCards, Spinner } from '../components/Skeleton';
import { Avatar } from '../components/ProfileMenu';
import { ConfirmPessoa, useConfirmar } from '../components/ConfirmDialog';

export function Equipe({ api, company }: { api: Api; company: Company }) {
  const confirmar = useConfirmar();
  const [membros, setMembros] = useState<EquipeMembro[]>([]);
  const [convites, setConvites] = useState<AtendenteInvite[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [savingConvite, setSavingConvite] = useState(false);
  const [membroAction, setMembroAction] = useState<number | null>(null);

  function load() {
    setBusy(true);
    setError('');
    Promise.all([
      api(`/companies/${company.id}/equipe/`),
      api(`/convites/?company=${company.id}`),
    ])
      .then(([membrosData, convitesData]: [EquipeMembro[], Paginated<AtendenteInvite>]) => {
        setMembros(membrosData);
        setConvites(convitesData.results);
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [company.id]);

  async function convidar(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSavingConvite(true);
    setError('');
    const formEl = e.currentTarget;
    const form = new FormData(formEl);
    try {
      const created = await api(`/convites/?company=${company.id}`, {
        method: 'POST',
        body: JSON.stringify({ name: form.get('name'), email: form.get('email') }),
      });
      setConvites((v) => [created, ...v]);
      formEl.reset();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingConvite(false);
    }
  }

  async function redefinirSenha(membro: EquipeMembro) {
    if (!(await confirmar({ titulo: 'Enviar uma nova senha?', mensagem: 'A senha atual deixa de valer e a pessoa terá de trocá-la no próximo acesso.', detalhe: <ConfirmPessoa nome={membro.display_name || membro.username} sub={membro.email} />, icone: 'email', confirmar: 'Enviar nova senha' }))) return;
    setMembroAction(membro.id);
    setError('');
    try {
      await api(`/companies/${company.id}/equipe/${membro.id}/redefinir-senha/`, { method: 'POST' });
      window.alert('Nova senha enviada para o e-mail do atendente.');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setMembroAction(null);
    }
  }

  async function desligarAtendente(membro: EquipeMembro) {
    if (!(await confirmar({ titulo: `Desligar ${membro.display_name || membro.username}?`, mensagem: 'A conta de acesso será removida permanentemente. Os leads atendidos continuam no histórico da empresa.', detalhe: <ConfirmPessoa nome={membro.display_name || membro.username} sub={membro.email} selo="Irreversível" />, tom: 'perigo', icone: 'lixeira', confirmar: 'Desligar atendente' }))) return;
    setMembroAction(membro.id);
    setError('');
    try {
      await api(`/companies/${company.id}/equipe/${membro.id}/`, { method: 'DELETE' });
      setMembros((v) => v.filter((m) => m.id !== membro.id));
    } catch (err) {
      setError((err as Error).message);
      setMembroAction(null);
    }
  }

  async function cancelarConvite(invite: AtendenteInvite) {
    if (!(await confirmar({ titulo: 'Cancelar o convite?', mensagem: `O convite enviado para ${invite.email} deixa de valer.`, tom: 'atencao', icone: 'email', confirmar: 'Cancelar convite', cancelar: 'Manter convite' }))) return;
    try {
      await api(`/convites/${invite.id}/?company=${company.id}`, { method: 'DELETE' });
      setConvites((v) => v.filter((c) => c.id !== invite.id));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const statusLabel: Record<AtendenteInvite['status'], string> = { pendente: 'Pendente', expirado: 'Expirado', verificado: 'Verificado' };

  return (
    <>
      <header className="page-header">
        <div>
          <small className="eyebrow">Pessoas e organização</small>
          <h1>Equipe</h1>
          <p>Cadastre e acompanhe os atendentes da empresa. As áreas de atendimento ficam em Dados da empresa.</p>
        </div>
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {busy && !membros.length ? (
        <SkeletonCards count={3} height={100} />
      ) : (
        <>
          <section className="panel" style={{ marginBottom: 20 }}>
            <div className="panel-toolbar">
              <h2>Atendentes</h2>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th />
                    <th>Nome</th>
                    <th>E-mail</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {membros.map((m) => (
                    <tr key={m.id}>
                      <td style={{ width: 40 }}>
                        <Avatar me={m} size={32} />
                      </td>
                      <td style={{ fontWeight: 600 }}>{m.display_name || m.username}</td>
                      <td>{m.email}</td>
                      <td style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', padding: '10px 24px' }}>
                        <button type="button" className="secondary" disabled={membroAction === m.id} onClick={() => redefinirSenha(m)}>
                          {membroAction === m.id && <Spinner />}
                          Redefinir senha
                        </button>
                        <button type="button" className="danger-outline" disabled={membroAction === m.id} onClick={() => desligarAtendente(m)}>
                          Desligar atendente
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!membros.length && <div className="empty">Nenhum atendente cadastrado ainda.</div>}
            </div>
          </section>

          <section className="panel" style={{ marginBottom: 20 }}>
            <div className="panel-toolbar">
              <h2>Convidar novo atendente</h2>
            </div>
            <form onSubmit={convidar} style={{ display: 'flex', gap: 10, flexWrap: 'wrap', padding: '0 24px 20px', alignItems: 'flex-end' }}>
              <label style={{ margin: 0, flex: '1 1 200px' }}>
                Nome
                <input name="name" required />
              </label>
              <label style={{ margin: 0, flex: '1 1 240px' }}>
                E-mail
                <input name="email" type="email" required />
              </label>
              <button disabled={savingConvite}>
                {savingConvite && <Spinner />}
                Enviar convite
              </button>
            </form>
            <p style={{ padding: '0 24px 16px', fontSize: 12.5, color: 'var(--muted)' }}>
              Um código de 6 dígitos e um link de confirmação serão enviados para o e-mail informado. Depois de
              confirmado, a senha provisória de acesso é enviada automaticamente.
            </p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Nome</th>
                    <th>E-mail</th>
                    <th>Status</th>
                    <th>Enviado em</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {convites.map((c) => (
                    <tr key={c.id}>
                      <td style={{ fontWeight: 600 }}>{c.name}</td>
                      <td>{c.email}</td>
                      <td>
                        <span className={`badge status-${c.status === 'verificado' ? 'active' : c.status === 'expirado' ? 'suspended' : 'pending'}`}>
                          {statusLabel[c.status]}
                        </span>
                      </td>
                      <td style={{ fontFamily: "'DM Mono',monospace", fontSize: 13, color: 'var(--muted)' }}>
                        {new Date(c.created_at).toLocaleString('pt-BR')}
                      </td>
                      <td>
                        {c.status !== 'verificado' && (
                          <button type="button" className="danger-outline" onClick={() => cancelarConvite(c)}>
                            Cancelar
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!convites.length && <div className="empty">Nenhum convite enviado ainda.</div>}
            </div>
          </section>
        </>
      )}
    </>
  );
}
