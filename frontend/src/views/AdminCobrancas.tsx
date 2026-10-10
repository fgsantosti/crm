import { useCallback, useEffect, useMemo, useState } from 'react';
import { fetchTodasAsPaginas, type Api } from '../api';
import type { AdminCompany, PrecoItem, TabelaPrecos } from '../types';
import { Spinner } from '../components/Skeleton';
import { useConfirmar } from '../components/ConfirmDialog';

// Painel Admin → Cobranças (fase 1): tabela de valores com vigência + histórico de alterações e empresas em teste.
// Os valores mudam com o tempo: cada alteração é uma linha nova com data de vigência (nada é editado nem apagado).

const brl = (v: string | number | null | undefined) => (v === null || v === undefined ? '—' : `R$ ${Number(v).toLocaleString('pt-BR', { minimumFractionDigits: Number(v) % 1 ? 2 : 0, maximumFractionDigits: 2 })}`);
const dataBr = (iso: string | null | undefined) => (iso ? iso.slice(0, 10).split('-').reverse().join('/') : '—');
const hojeIso = () => new Date().toLocaleDateString('en-CA', { timeZone: 'America/Fortaleza' });
const ESCOPOS: { valor: string; nome: string; ajuda: string }[] = [
  { valor: 'novos', nome: 'Novos contratos', ajuda: 'Quem já tem contrato mantém o valor combinado.' },
  { valor: 'reajuste', nome: 'No próximo reajuste de cada contrato', ajuda: 'O valor novo entra na data de aniversário, junto com o índice.' },
  { valor: 'todos', nome: 'Todos os contratos a partir da vigência', ajuda: 'Use quando o cliente aceitou a mudança.' },
  { valor: 'escolher', nome: 'Escolher gestores', ajuda: 'Aplique só a quem você combinou.' },
];

export function AdminCobrancas({ api }: { api: Api }) {
  const confirmar = useConfirmar();
  const [tabela, setTabela] = useState<TabelaPrecos | null>(null);
  const [empresas, setEmpresas] = useState<AdminCompany[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [editando, setEditando] = useState<PrecoItem | null>(null);
  const [novoValor, setNovoValor] = useState('');
  const [vigencia, setVigencia] = useState('');
  const [escopo, setEscopo] = useState('novos');
  const [saving, setSaving] = useState(false);
  const [agindo, setAgindo] = useState<number | null>(null);

  const carregar = useCallback(() => {
    setBusy(true);
    setError('');
    Promise.all([api('/admin-precos/'), fetchTodasAsPaginas<AdminCompany>(api, '/admin-companies/')])
      .then(([t, e]) => {
        setTabela(t);
        setEmpresas(e);
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }, [api]);
  useEffect(carregar, [carregar]);

  const itens = tabela?.itens ?? [];
  const valorDe = (k: string) => Number(itens.find((i) => i.item === k)?.valor ?? 0);
  const usoDe = (k: string) => itens.find((i) => i.item === k)?.em_uso ?? 0;

  // Prévia: mensalidade recorrente de hoje e depois da vigência, quando o novo valor se aplica aos contratos existentes.
  const previa = useMemo(() => {
    if (!editando) return null;
    const antes = Number(tabela?.recorrente_atual ?? 0);
    const novo = Number(String(novoValor).replace(',', '.'));
    const mensal = ['base', 'agente_adicional'].includes(editando.item);
    if (Number.isNaN(novo) || !mensal || escopo === 'novos') {
      return { antes, depois: antes, texto: mensal ? 'Vale só para contratos novos: a mensalidade atual não muda.' : 'Valor único: vale para os próximos clientes; cobranças já emitidas não mudam.' };
    }
    const base = editando.item === 'base' ? novo : valorDe('base');
    const ag = editando.item === 'agente_adicional' ? novo : valorDe('agente_adicional');
    const depois = base * usoDe('base') + ag * usoDe('agente_adicional');
    const quando = escopo === 'reajuste' ? 'Aplicado no próximo reajuste de cada contrato.' : escopo === 'todos' ? 'Todos os contratos passam ao novo valor na vigência.' : 'Só os gestores escolhidos passam ao novo valor.';
    return { antes, depois, texto: `${quando} Muda a mensalidade de ${editando.em_uso ?? 0} contrato(s).` };
  }, [editando, novoValor, escopo, tabela]);

  function abrirEdicao(i: PrecoItem) {
    setEditando(i);
    setNovoValor(i.valor ?? '');
    setVigencia(hojeIso());
    setEscopo('novos');
  }

  async function salvarPreco() {
    if (!editando) return;
    setSaving(true);
    setError('');
    try {
      const t: TabelaPrecos = await api('/admin-precos/', { method: 'POST', body: JSON.stringify({ item: editando.item, valor: novoValor, vigente_desde: vigencia, escopo }) });
      setTabela(t);
      setEditando(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function agirNoTeste(empresa: AdminCompany, acao: 'ligar' | 'desligar' | 'prorrogar' | 'converter') {
    if (acao === 'converter' && !(await confirmar({ titulo: `Converter ${empresa.name} em contrato?`, mensagem: 'A empresa sai da fase de teste e passa a cobrar a mensalidade. O valor do piloto é abatido da implantação.', icone: 'pessoa', confirmar: 'Converter em contrato' }))) return;
    setAgindo(empresa.id);
    setError('');
    try {
      const base = `/admin-companies/${empresa.id}/teste/`;
      const teste = acao === 'prorrogar' ? await api(`${base}prorrogar/`, { method: 'POST', body: JSON.stringify({ dias: 15 }) })
        : acao === 'converter' ? await api(`${base}converter/`, { method: 'POST' })
        : await api(base, { method: 'POST', body: JSON.stringify(acao === 'ligar' ? { em_teste: true, inicio: hojeIso(), dias: 30 } : { em_teste: false }) });
      setEmpresas((v) => v.map((c) => (c.id === empresa.id ? { ...c, teste } : c)));
      const t: TabelaPrecos = await api('/admin-precos/');
      setTabela(t);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAgindo(null);
    }
  }

  return (
    <>
      <header className="page-header">
        <div>
          <small className="eyebrow">Plataforma</small>
          <h1>Cobranças</h1>
          <p>Defina quanto cobrar por implantação, empresa e agente e quais empresas estão em teste. Os valores mudam com o tempo: cada alteração tem data de vigência e fica registrada.</p>
        </div>
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <section className="dash-card dash-card-tabela" aria-labelledby="cob-valores">
        <div className="dash-card-topo">
          <div>
            <h2 id="cob-valores">Tabela de valores</h2>
            <small>Valores vigentes hoje; contratos existentes mantêm o valor combinado até o próximo reajuste, salvo se você escolher aplicar antes.</small>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th>Cobrança</th>
                <th style={{ textAlign: 'right' }}>Valor vigente</th>
                <th>Vigente desde</th>
                <th style={{ textAlign: 'right' }}>Em uso</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {itens.map((i) => (
                <tr key={i.item} className={editando?.item === i.item ? 'cob-linha-ativa' : undefined}>
                  <td>
                    <strong style={{ display: 'block' }}>{i.nome}</strong>
                    <small>{i.nota}</small>
                    {i.proximo && <small className="cob-agendado">A partir de {dataBr(i.proximo.vigente_desde)}: {brl(i.proximo.valor)}</small>}
                  </td>
                  <td>{i.tipo}</td>
                  <td className="cob-valor">{brl(i.valor)}</td>
                  <td style={{ fontFamily: "'DM Mono',monospace", fontSize: 13 }}>{dataBr(i.vigente_desde)}</td>
                  <td className="dash-num">{i.em_uso === null ? '—' : i.em_uso}</td>
                  <td style={{ textAlign: 'right' }}>
                    <button type="button" className="secondary" aria-expanded={editando?.item === i.item} onClick={() => abrirEdicao(i)}>
                      Alterar valor
                    </button>
                  </td>
                </tr>
              ))}
              {busy && !itens.length && (
                <tr>
                  <td colSpan={6}>Carregando…</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {editando && previa && (
          <div className="cob-edicao">
            <strong>Alterar: {editando.nome}</strong>
            <div className="cob-campos">
              <label>
                Novo valor (R$)
                <input type="number" min={0} step={10} value={novoValor} onChange={(e) => setNovoValor(e.target.value)} />
              </label>
              <label>
                Vale a partir de
                <input type="date" value={vigencia} onChange={(e) => setVigencia(e.target.value)} />
              </label>
            </div>
            <div role="radiogroup" aria-label="Aplicar a" className="cob-escopos">
              {ESCOPOS.map((e) => (
                <label key={e.valor}>
                  <input type="radio" name="escopo" checked={escopo === e.valor} onChange={() => setEscopo(e.valor)} />
                  <span>
                    <strong>{e.nome}</strong>
                    <small>{e.ajuda}</small>
                  </span>
                </label>
              ))}
            </div>
            <div className="cob-previa">
              <div>
                <small>Mensalidade recorrente hoje</small>
                <strong>{brl(previa.antes)}</strong>
              </div>
              <span aria-hidden="true">→</span>
              <div>
                <small>Depois da vigência</small>
                <strong style={{ color: previa.depois > previa.antes ? 'var(--success)' : previa.depois < previa.antes ? 'var(--danger)' : undefined }}>{brl(previa.depois)}</strong>
              </div>
              <small className="cob-previa-texto">{previa.texto}</small>
            </div>
            <div className="cob-acoes">
              <button type="button" className="secondary" onClick={() => setEditando(null)}>
                Cancelar
              </button>
              <button type="button" disabled={saving || !novoValor || !vigencia} onClick={salvarPreco}>
                {saving && <Spinner />}
                Salvar nova vigência
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="dash-card" aria-labelledby="cob-historico">
        <h2 id="cob-historico">Histórico de alterações de valor</h2>
        {tabela?.historico.length ? (
          <ul className="cob-historico">
            {tabela.historico.map((h) => (
              <li key={h.id}>
                <span className="cob-quando">{dataBr(h.criado_em)}</span>
                <strong>{h.nome}</strong>
                <span className="cob-de-para">{brl(h.valor)} a partir de {dataBr(h.vigente_desde)}</span>
                <span>{h.escopo_rotulo}</span>
                <small>{h.por || '—'}</small>
              </li>
            ))}
          </ul>
        ) : (
          <p className="dash-nota">Nenhuma alteração registrada.</p>
        )}
      </section>

      <section className="dash-card dash-card-tabela" aria-labelledby="cob-testes">
        <div className="dash-card-topo">
          <div>
            <h2 id="cob-testes">Empresas em fase de teste</h2>
            <small>Empresas em piloto cobram o valor do piloto ({brl(valorDe('piloto'))}) em vez da mensalidade e saem da base de contas de empresa.</small>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Empresa</th>
                <th>Em teste</th>
                <th>Início</th>
                <th>Duração</th>
                <th>Fim</th>
                <th>Situação</th>
                <th style={{ textAlign: 'right' }}>Ações</th>
              </tr>
            </thead>
            <tbody>
              {empresas.map((c) => {
                const t = c.teste;
                const em = !!t?.em_teste;
                const ocupado = agindo === c.id;
                return (
                  <tr key={c.id}>
                    <td>
                      <strong>{c.name}</strong>
                    </td>
                    <td>
                      <button type="button" role="switch" aria-checked={em} aria-label={`Em teste: ${c.name}`} className={`chave-switch${em ? ' ligada' : ''}`} disabled={ocupado} onClick={() => agirNoTeste(c, em ? 'desligar' : 'ligar')}>
                        <span />
                      </button>
                    </td>
                    <td style={{ fontFamily: "'DM Mono',monospace", fontSize: 13 }}>{em ? dataBr(t?.inicio) : '—'}</td>
                    <td style={{ fontFamily: "'DM Mono',monospace", fontSize: 13 }}>{em ? `${t?.dias} dias` : '—'}</td>
                    <td style={{ fontFamily: "'DM Mono',monospace", fontSize: 13 }}>{em ? dataBr(t?.fim) : '—'}</td>
                    <td>
                      <span className="dash-selo" style={em ? { background: (t?.restam ?? 1) < 0 ? '#FBE6E3' : '#E3ECFD', color: (t?.restam ?? 1) < 0 ? '#A3271C' : '#1D4FBF' } : { background: '#F1E8DB', color: '#4E4136' }}>
                        {t?.situacao ?? '—'}
                      </span>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      {em && (
                        <span className="cob-acoes-linha">
                          <button type="button" className="secondary" disabled={ocupado} onClick={() => agirNoTeste(c, 'prorrogar')}>
                            Prorrogar +15 dias
                          </button>
                          <button type="button" disabled={ocupado} onClick={() => agirNoTeste(c, 'converter')}>
                            Converter em contrato
                          </button>
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
              {!busy && !empresas.length && (
                <tr>
                  <td colSpan={7}>Nenhuma empresa cadastrada.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
