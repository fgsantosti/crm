import { useEffect, useState } from 'react';
import type { Api } from '../api';
import type { Area, AtendenteInvite, Company, EquipeMembro, Paginated } from '../types';
import { SkeletonCards, Spinner } from '../components/Skeleton';
import { Avatar } from '../components/ProfileMenu';

export function Equipe({ api, company }: { api: Api; company: Company }) {
  const [membros, setMembros] = useState<EquipeMembro[]>([]);
  const [areas, setAreas] = useState<Area[]>([]);
  const [convites, setConvites] = useState<AtendenteInvite[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [savingArea, setSavingArea] = useState<number | 'new' | null>(null);
  const [savingConvite, setSavingConvite] = useState(false);
  const [newArea, setNewArea] = useState('');
  const [membroAction, setMembroAction] = useState<number | null>(null);

  function load() {
    setBusy(true);
    setError('');
    Promise.all([
      api(`/companies/${company.id}/equipe/`),
      api(`/areas/?company=${company.id}`),
      api(`/convites/?company=${company.id}`),
    ])
      .then(([membrosData, areasData, convitesData]: [EquipeMembro[], Paginated<Area>, Paginated<AtendenteInvite>]) => {
        setMembros(membrosData);
        setAreas(areasData.results);
        setConvites(convitesData.results);
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [company.id]);

  async function addArea(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!newArea.trim()) return;
    setSavingArea('new');
    setError('');
    try {
      const created = await api(`/areas/?company=${company.id}`, { method: 'POST', body: JSON.stringify({ name: newArea.trim() }) });
      setAreas((v) => [...v, created].sort((a, b) => a.name.localeCompare(b.name)));
      setNewArea('');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingArea(null);
    }
  }

  async function removeArea(area: Area) {
    if (!window.confirm(`Remover a área "${area.name}"? Leads já classificados com ela mantêm o registro.`)) return;
    setSavingArea(area.id);
    setError('');
    try {
      await api(`/areas/${area.id}/?company=${company.id}`, { method: 'DELETE' });
      setAreas((v) => v.filter((a) => a.id !== area.id));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingArea(null);
    }
  }

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
    if (!window.confirm(`Enviar uma nova senha por e-mail para ${membro.email}?`)) return;
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
    if (!window.confirm(`Desligar ${membro.display_name || membro.username}? A conta de acesso dele(a) será removida permanentemente.`)) return;
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
    if (!window.confirm(`Cancelar o convite enviado para ${invite.email}?`)) return;
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
          <p>Cadastre atendentes e as áreas de atendimento usadas na classificação de leads.</p>
        </div>
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {busy && !membros.length && !areas.length ? (
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

          <section className="panel">
            <div className="panel-toolbar">
              <h2>Áreas de atendimento</h2>
            </div>
            <form onSubmit={addArea} style={{ display: 'flex', gap: 10, padding: '0 24px 16px' }}>
              <input placeholder="Nova área" value={newArea} onChange={(e) => setNewArea(e.target.value)} style={{ flex: 1 }} />
              <button disabled={savingArea === 'new'}>
                {savingArea === 'new' && <Spinner />}+ Adicionar
              </button>
            </form>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, padding: '0 24px 24px' }}>
              {areas.map((area) => (
                <span key={area.id} className="tag-pill" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {area.name}
                  <button
                    type="button"
                    aria-label={`Remover área ${area.name}`}
                    onClick={() => removeArea(area)}
                    disabled={savingArea === area.id}
                    style={{ border: 'none', background: 'none', padding: 0, cursor: 'pointer', color: 'inherit' }}
                  >
                    ×
                  </button>
                </span>
              ))}
              {!areas.length && <div className="empty">Nenhuma área cadastrada ainda.</div>}
            </div>
          </section>
        </>
      )}
    </>
  );
}
