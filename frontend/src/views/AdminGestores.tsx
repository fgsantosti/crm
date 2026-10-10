import { useCallback, useEffect, useState } from 'react';
import { fetchTodasAsPaginas, type Api } from '../api';
import type { AdminCompany, Gestor } from '../types';
import { Spinner } from '../components/Skeleton';
import { useConfirmar } from '../components/ConfirmDialog';

// Painel Admin → Gestores: o cliente que paga e as empresas dele (base do faturamento).
const FORMAS = [['pix', 'PIX'], ['boleto', 'Boleto'], ['cartao', 'Cartão'], ['outro', 'Outro']] as const;
const VAZIO = { nome: '', email: '', dia_vencimento: 10, forma_pagamento: 'pix', contrato_inicio: '', indice_reajuste: 'IPCA', notas: '' };
const dataBr = (iso: string | null | undefined) => (iso ? iso.slice(0, 10).split('-').reverse().join('/') : '—');

export function AdminGestores({ api }: { api: Api }) {
  const confirmar = useConfirmar();
  const [gestores, setGestores] = useState<Gestor[]>([]);
  const [empresas, setEmpresas] = useState<(AdminCompany & { gestor?: number | null })[]>([]);
  const [busca, setBusca] = useState('');
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<{ id: number | null; dados: typeof VAZIO } | null>(null);
  const [saving, setSaving] = useState(false);
  const [vincular, setVincular] = useState<Record<number, string>>({});

  const carregar = useCallback(() => {
    setBusy(true);
    setError('');
    Promise.all([fetchTodasAsPaginas<Gestor>(api, '/admin-gestores/'), fetchTodasAsPaginas<AdminCompany>(api, '/admin-companies/')])
      .then(([g, e]) => {
        setGestores(g);
        setEmpresas(e);
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }, [api]);
  useEffect(carregar, [carregar]);

  const comGestor = new Set(gestores.flatMap((g) => g.empresas.map((e) => e.id)));
  const livres = empresas.filter((e) => !comGestor.has(e.id));
  const visiveis = gestores.filter((g) => `${g.nome} ${g.email} ${g.empresas.map((e) => e.name).join(' ')}`.toLowerCase().includes(busca.toLowerCase()));

  function trocar(g: Gestor) {
    setGestores((v) => v.map((x) => (x.id === g.id ? g : x)));
  }
  async function salvar(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setSaving(true);
    setError('');
    try {
      const corpo = { ...form.dados, contrato_inicio: form.dados.contrato_inicio || null };
      const g: Gestor = await api(form.id ? `/admin-gestores/${form.id}/` : '/admin-gestores/', { method: form.id ? 'PATCH' : 'POST', body: JSON.stringify(corpo) });
      if (form.id) trocar(g);
      else setGestores((v) => [...v, g].sort((a, b) => a.nome.localeCompare(b.nome)));
      setForm(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }
  async function acao(g: Gestor, caminho: 'vincular' | 'desvincular', companyId: number) {
    setError('');
    try {
      trocar(await api(`/admin-gestores/${g.id}/${caminho}/`, { method: 'POST', body: JSON.stringify({ company_id: companyId }) }));
      setVincular((v) => ({ ...v, [g.id]: '' }));
    } catch (err) {
      setError((err as Error).message);
    }
  }
  async function excluir(g: Gestor) {
    if (!(await confirmar({ titulo: `Excluir o gestor ${g.nome}?`, mensagem: 'As empresas ficam no CRM, só perdem o vínculo. As cobranças e os pagamentos dele são apagados.', tom: 'perigo', icone: 'lixeira', confirmar: 'Excluir gestor' }))) return;
    try {
      await api(`/admin-gestores/${g.id}/`, { method: 'DELETE' });
      setGestores((v) => v.filter((x) => x.id !== g.id));
    } catch (err) {
      setError((err as Error).message);
    }
  }
  async function implantacao(g: Gestor) {
    setError('');
    setAviso('');
    try {
      await api(`/admin-gestores/${g.id}/implantacao/`, { method: 'POST' });
      setAviso(`Cobrança de implantação de ${g.nome} emitida. Ela aparece em Faturamento.`);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const campo = (k: keyof typeof VAZIO, v: string | number) => setForm((f) => (f ? { ...f, dados: { ...f.dados, [k]: v } } : f));

  return (
    <>
      <header className="page-header" style={{ alignItems: 'flex-end' }}>
        <div>
          <small className="eyebrow">Plataforma</small>
          <h1>Gestores</h1>
          <p>Cada gestor é um cliente que paga. Reúna as empresas dele aqui: a mensalidade é calculada por gestor.</p>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <input placeholder="Buscar gestor ou empresa" aria-label="Buscar gestor" style={{ width: 260 }} value={busca} onChange={(e) => setBusca(e.target.value)} />
          <button type="button" onClick={() => setForm({ id: null, dados: VAZIO })}>
            + Novo gestor
          </button>
        </div>
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {aviso && (
        <p role="status" className="classif-aviso">
          {aviso}
        </p>
      )}

      {form && (
        <form className="dash-card gestor-form" onSubmit={salvar}>
          <h2>{form.id ? 'Editar gestor' : 'Novo gestor'}</h2>
          <div className="cob-campos">
            <label>
              Nome
              <input value={form.dados.nome} onChange={(e) => campo('nome', e.target.value)} required />
            </label>
            <label>
              E-mail de contato e cobrança
              <input type="email" value={form.dados.email} onChange={(e) => campo('email', e.target.value)} />
            </label>
            <label>
              Dia de vencimento
              <input type="number" min={1} max={28} value={form.dados.dia_vencimento} onChange={(e) => campo('dia_vencimento', Number(e.target.value))} />
            </label>
            <label>
              Forma de pagamento
              <select value={form.dados.forma_pagamento} onChange={(e) => campo('forma_pagamento', e.target.value)}>
                {FORMAS.map(([v, r]) => (
                  <option key={v} value={v}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Início do contrato
              <input type="date" value={form.dados.contrato_inicio ?? ''} onChange={(e) => campo('contrato_inicio', e.target.value)} />
            </label>
            <label>
              Índice de reajuste
              <select value={form.dados.indice_reajuste} onChange={(e) => campo('indice_reajuste', e.target.value)}>
                {['IPCA', 'IGP-M', 'Percentual fixo'].map((i) => (
                  <option key={i}>{i}</option>
                ))}
              </select>
            </label>
          </div>
          <label>
            Notas internas (só você vê)
            <textarea rows={3} value={form.dados.notas} onChange={(e) => campo('notas', e.target.value)} />
          </label>
          <div className="cob-acoes">
            <button type="button" className="secondary" onClick={() => setForm(null)}>
              Cancelar
            </button>
            <button disabled={saving || !form.dados.nome.trim()}>
              {saving && <Spinner />}
              Salvar gestor
            </button>
          </div>
        </form>
      )}

      <section className="gestor-lista" aria-label="Gestores">
        {visiveis.map((g) => (
          <article key={g.id} className="dash-card">
            <div className="gestor-topo">
              <div>
                <h2>{g.nome}</h2>
                <small>
                  {g.email || 'sem e-mail'} · vence todo dia {g.dia_vencimento} · {FORMAS.find(([v]) => v === g.forma_pagamento)?.[1]} · contrato desde {dataBr(g.contrato_inicio)} ({g.indice_reajuste})
                </small>
              </div>
              <div className="cob-acoes-linha">
                <button type="button" className="secondary" onClick={() => setForm({ id: g.id, dados: { nome: g.nome, email: g.email, dia_vencimento: g.dia_vencimento, forma_pagamento: g.forma_pagamento, contrato_inicio: g.contrato_inicio ?? '', indice_reajuste: g.indice_reajuste, notas: g.notas } })}>
                  Editar
                </button>
                <button type="button" className="secondary" onClick={() => implantacao(g)}>
                  Emitir implantação
                </button>
                <button type="button" className="danger-outline" onClick={() => excluir(g)}>
                  Excluir
                </button>
              </div>
            </div>
            <ul className="gestor-empresas">
              {g.empresas.map((e) => (
                <li key={e.id}>
                  <strong>{e.name}</strong>
                  {e.em_teste && <span className="dash-selo" style={{ background: '#E3ECFD', color: '#1D4FBF' }}>Em teste</span>}
                  <button type="button" className="secondary" aria-label={`Desvincular ${e.name}`} onClick={() => acao(g, 'desvincular', e.id)}>
                    Desvincular
                  </button>
                </li>
              ))}
              {!g.empresas.length && <li className="dash-nota">Nenhuma empresa vinculada ainda.</li>}
            </ul>
            <div className="gestor-vincular">
              <label className="select-field">
                <select aria-label={`Vincular empresa a ${g.nome}`} value={vincular[g.id] ?? ''} onChange={(e) => setVincular((v) => ({ ...v, [g.id]: e.target.value }))}>
                  <option value="">Vincular empresa…</option>
                  {livres.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.name}
                    </option>
                  ))}
                </select>
              </label>
              <button type="button" disabled={!vincular[g.id]} onClick={() => acao(g, 'vincular', Number(vincular[g.id]))}>
                Vincular
              </button>
            </div>
            {g.notas && <p className="dash-nota">Notas: {g.notas}</p>}
          </article>
        ))}
        {!busy && !visiveis.length && <div className="empty">Nenhum gestor cadastrado.</div>}
      </section>
    </>
  );
}
