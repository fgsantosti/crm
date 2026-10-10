import { useCallback, useEffect, useState } from 'react';
import type { Api } from '../api';
import type { CobrancaItem, Faturamento } from '../types';
import { Spinner } from '../components/Skeleton';
import { NumeroAnimado } from '../components/NumeroAnimado';
import { useConfirmar } from '../components/ConfirmDialog';

// Painel Admin → Faturamento: o que a plataforma fatura, de quem, e o controle de recebimentos, atrasos e contratos.
const brl = (v: string | number) => `R$ ${Number(v).toLocaleString('pt-BR', { minimumFractionDigits: Number(v) % 1 ? 2 : 0, maximumFractionDigits: 2 })}`;
const dataBr = (iso: string | null | undefined) => (iso ? iso.slice(0, 10).split('-').reverse().join('/') : '—');
const hojeIso = () => new Date().toLocaleDateString('en-CA', { timeZone: 'America/Fortaleza' });
const mesAtual = () => hojeIso().slice(0, 7);
const FORMAS: Record<string, string> = { pix: 'PIX', boleto: 'Boleto', cartao: 'Cartão', outro: 'Outro' };
const STATUS: Record<string, { rotulo: string; fundo: string; cor: string }> = {
  recebido: { rotulo: 'Recebido', fundo: '#EEF7F1', cor: '#245F46' },
  a_receber: { rotulo: 'A receber', fundo: '#FBF0D8', cor: '#7A4F0E' },
  em_atraso: { rotulo: 'Em atraso', fundo: '#FBE6E3', cor: '#A3271C' },
  sem_cobranca: { rotulo: 'Sem cobrança', fundo: '#F1E8DB', cor: '#4E4136' },
};
const FAIXAS = [
  { nome: 'Atraso curto', cor: '#C88A1E', acao: 'Lembrete automático ao gestor.' },
  { nome: 'Atraso médio', cor: '#D9531A', acao: 'Lembrete firme, com cópia ao financeiro.' },
  { nome: 'Atraso longo', cor: '#B23A2E', acao: 'Aviso de desligamento dos agentes.' },
];

export function AdminFaturamento({ api }: { api: Api }) {
  const confirmar = useConfirmar();
  const [mes, setMes] = useState(mesAtual());
  const [dados, setDados] = useState<Faturamento | null>(null);
  const [visao, setVisao] = useState<'gestor' | 'empresa' | 'agente'>('gestor');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [pagando, setPagando] = useState<CobrancaItem | null>(null);
  const [pg, setPg] = useState({ data: hojeIso(), valor: '', forma: 'pix', comprovante: '' });
  const [saving, setSaving] = useState(false);

  const carregar = useCallback(() => {
    setBusy(true);
    setError('');
    api(`/admin-faturamento/?mes=${mes}`)
      .then((d: Faturamento) => setDados(d))
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }, [api, mes]);
  useEffect(carregar, [carregar]);

  function abrirPagamento(c: CobrancaItem) {
    setPagando(c);
    setPg({ data: hojeIso(), valor: c.saldo, forma: c.forma, comprovante: '' });
  }
  async function registrar() {
    if (!pagando) return;
    setSaving(true);
    setError('');
    try {
      await api(`/admin-cobrancas/${pagando.id}/pagamentos/`, { method: 'POST', body: JSON.stringify(pg) });
      setPagando(null);
      carregar();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  async function desfazer(id: number, quem: string) {
    if (!(await confirmar({ titulo: 'Desfazer este pagamento?', mensagem: `O pagamento de ${quem} sai do histórico e a cobrança volta a ter saldo.`, tom: 'atencao', icone: 'aviso', confirmar: 'Desfazer pagamento' }))) return;
    try {
      await api(`/admin-pagamentos/${id}/`, { method: 'DELETE' });
      carregar();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const k = dados?.kpis;
  const serie = dados?.recorrente ?? [];
  const maxSerie = Math.max(1, ...serie.map((s) => Number(s.valor)));
  const kpis = k
    ? [
        { rotulo: 'Previsto no mês', valor: Number(k.previsto), cor: 'var(--ink)', nota: 'todas as cobranças do mês' },
        { rotulo: 'Recebido', valor: Number(k.recebido), cor: '#245F46', nota: `${Number(k.previsto) ? Math.round((Number(k.recebido) / Number(k.previsto)) * 100) : 0}% do previsto` },
        { rotulo: 'A receber', valor: Number(k.a_receber), cor: '#7A4F0E', nota: 'dentro do prazo' },
        { rotulo: 'Em atraso', valor: Number(k.em_atraso), cor: Number(k.em_atraso) ? '#A3271C' : '#245F46', nota: dados?.inadimplencia.atrasados.length ? `${dados.inadimplencia.atrasados.length} cobrança(s)` : 'nenhuma' },
      ]
    : [];

  return (
    <>
      <header className="page-header" style={{ alignItems: 'flex-end' }}>
        <div>
          <small className="eyebrow">Plataforma</small>
          <h1>Faturamento</h1>
          <p>Quanto a plataforma fatura, de quem e por quê, com o controle de recebimentos, atrasos e contratos.</p>
        </div>
        <label className="select-field" style={{ margin: 0 }}>
          <span className="sr-only">Mês</span>
          <input type="month" aria-label="Mês" value={mes} onChange={(e) => e.target.value && setMes(e.target.value)} style={{ height: 44, borderRadius: 11 }} />
        </label>
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <section className="fat-kpis" aria-label="Resumo">
        {kpis.map((c) => (
          <article key={c.rotulo} className="dash-card">
            <small>{c.rotulo}</small>
            <strong style={{ color: c.cor }}>
              R$ <NumeroAnimado valor={Math.round(c.valor)} />
            </strong>
            <small>{c.nota}</small>
          </article>
        ))}
        {busy && !k && <p>Carregando…</p>}
      </section>

      <section className="dash-card dash-card-tabela" aria-labelledby="fat-det">
        <div className="dash-card-topo">
          <div className="dash-card-cab">
            <div>
              <h2 id="fat-det">Detalhe do faturamento</h2>
              <small>{visao === 'gestor' ? 'Por gestor, que é quem paga. Registre os recebimentos aqui.' : visao === 'empresa' ? 'Cada empresa e o quanto ela gera; a cobrança é do gestor.' : 'Cada agente e o que representa na mensalidade.'}</small>
            </div>
            <div className="segmentado" role="group" aria-label="Visão">
              {([['gestor', 'Por gestor'], ['empresa', 'Por empresa'], ['agente', 'Por agente']] as const).map(([v, r]) => (
                <button key={v} type="button" aria-pressed={visao === v} onClick={() => setVisao(v)}>
                  {r}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{visao === 'gestor' ? 'Gestor' : visao === 'empresa' ? 'Empresa' : 'Agente'}</th>
                <th>Composição</th>
                <th style={{ textAlign: 'right' }}>Valor</th>
                {visao === 'gestor' && (
                  <>
                    <th>Vencimento</th>
                    <th>Cobrança</th>
                    <th />
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {visao === 'gestor' &&
                dados?.cobrancas.map((c) => {
                  const st = STATUS[c.status];
                  return (
                    <tr key={c.id}>
                      <td>
                        <strong style={{ display: 'block' }}>{c.gestor}</strong>
                        <small>{c.tipo_rotulo} · {FORMAS[c.forma] ?? c.forma}</small>
                      </td>
                      <td className="fat-composicao">{c.linhas.map((l) => `${l.descricao} (${Number(l.valor) < 0 ? '−' : ''}${brl(Math.abs(Number(l.valor)))})`).join(' · ')}</td>
                      <td className="cob-valor" style={{ fontSize: 18 }}>{brl(c.valor)}</td>
                      <td style={{ fontFamily: "'DM Mono',monospace", fontSize: 13 }}>{dataBr(c.vencimento)}</td>
                      <td>
                        <span className="dash-selo" style={{ background: st.fundo, color: st.cor }}>{st.rotulo}{c.status === 'em_atraso' ? ` · ${c.dias_atraso} dias` : ''}</span>
                        {c.recebido_em && <small style={{ display: 'block' }}>recebido em {dataBr(c.recebido_em)}</small>}
                        {c.status === 'a_receber' && Number(c.pago) > 0 && <small style={{ display: 'block' }}>pago {brl(c.pago)}</small>}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {(c.status === 'a_receber' || c.status === 'em_atraso') && (
                          <button type="button" className="secondary" onClick={() => abrirPagamento(c)}>
                            Registrar pagamento
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              {visao === 'empresa' &&
                dados?.por_empresa.map((e) => (
                  <tr key={e.empresa}>
                    <td>
                      <strong style={{ display: 'block' }}>{e.empresa}</strong>
                      <small>gestor: {e.gestor}</small>
                    </td>
                    <td className="fat-composicao">{e.linhas.join(' · ')}</td>
                    <td className="cob-valor" style={{ fontSize: 18 }}>{brl(e.valor)}</td>
                  </tr>
                ))}
              {visao === 'agente' &&
                dados?.por_agente.map((a) => (
                  <tr key={a.agente}>
                    <td>
                      <strong style={{ display: 'block', fontFamily: "'DM Mono',monospace", fontSize: 13 }}>{a.agente}</strong>
                      <small>{a.empresa} · {a.gestor}</small>
                    </td>
                    <td className="fat-composicao">{a.linhas.join(' · ')}</td>
                    <td className="cob-valor" style={{ fontSize: 18 }}>{brl(a.valor)}</td>
                  </tr>
                ))}
              {!busy && dados && ((visao === 'gestor' && !dados.cobrancas.length) || (visao === 'empresa' && !dados.por_empresa.length) || (visao === 'agente' && !dados.por_agente.length)) && (
                <tr>
                  <td colSpan={6}>Nada a cobrar neste mês. Cadastre gestores e vincule as empresas em Gestores.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {pagando && (
          <div className="cob-edicao">
            <strong>Registrar pagamento · {pagando.gestor} · {pagando.tipo_rotulo} ({brl(pagando.saldo)} em aberto)</strong>
            <div className="cob-campos">
              <label>
                Data
                <input type="date" value={pg.data} onChange={(e) => setPg({ ...pg, data: e.target.value })} />
              </label>
              <label>
                Valor (R$)
                <input type="number" min={0} step={0.01} value={pg.valor} onChange={(e) => setPg({ ...pg, valor: e.target.value })} />
              </label>
              <label>
                Forma
                <select value={pg.forma} onChange={(e) => setPg({ ...pg, forma: e.target.value })}>
                  {Object.entries(FORMAS).map(([v, r]) => (
                    <option key={v} value={v}>
                      {r}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Comprovante (arquivo ou link)
                <input value={pg.comprovante} placeholder="ex.: pix-1010.pdf" onChange={(e) => setPg({ ...pg, comprovante: e.target.value })} />
              </label>
            </div>
            <div className="cob-acoes">
              <button type="button" className="secondary" onClick={() => setPagando(null)}>
                Cancelar
              </button>
              <button type="button" disabled={saving} onClick={registrar}>
                {saving && <Spinner />}
                Registrar
              </button>
            </div>
          </div>
        )}
      </section>

      <div className="dash-duas">
        <section className="dash-card" aria-labelledby="fat-rec">
          <div>
            <h2 id="fat-rec">Receita recorrente</h2>
            <small>Mensalidades emitidas nos últimos 6 meses e projeção dos próximos 3 com os contratos atuais</small>
          </div>
          <div className="dash-meses" role="img" aria-label={`Receita recorrente: ${serie.map((s) => `${s.mes.slice(0, 7)} ${brl(s.valor)}`).join(', ')}`}>
            {serie.map((s) => (
              <div key={s.mes} className="dash-mes">
                <span className="dash-mes-valor">{(Number(s.valor) / 1000).toFixed(1).replace('.', ',')}k</span>
                <span className="dash-mes-barra" style={{ height: Math.max(6, Math.round((Number(s.valor) / maxSerie) * 150)), background: s.projecao ? '#F6D6BE' : undefined, border: s.projecao ? '1.5px dashed var(--accent)' : undefined }} />
                <small>{new Date(`${s.mes.slice(0, 7)}-15T12:00:00`).toLocaleDateString('pt-BR', { month: 'short' })}</small>
              </div>
            ))}
          </div>
        </section>

        <section className="dash-card" aria-labelledby="fat-con">
          <div>
            <h2 id="fat-con">Contratos, reajuste e descontos</h2>
            <small>Reajuste anual com alerta antes da renovação, desconto por tempo e a implantação</small>
          </div>
          <ul className="fat-contratos">
            {dados?.contratos.map((c) => (
              <li key={c.gestor_id}>
                <div className="fat-contrato-topo">
                  <strong>{c.gestor}</strong>
                  <span className="dash-selo" style={c.implantacao === 'recebido' ? { background: '#EEF7F1', color: '#245F46' } : c.implantacao === 'nao_cobrada' ? { background: '#F1E8DB', color: '#4E4136' } : { background: '#FBF0D8', color: '#7A4F0E' }}>
                    {c.em_teste ? 'Em teste' : c.implantacao === 'recebido' ? 'Implantação paga' : c.implantacao === 'nao_cobrada' ? 'Implantação não emitida' : 'Implantação em aberto'}
                  </span>
                </div>
                <small>
                  Início {dataBr(c.contrato_inicio)} · reajuste {c.proximo_reajuste ? `${dataBr(c.proximo_reajuste)} (${c.indice})` : '—'}
                  {c.desconto_por_tempo_pct ? ` · desconto por tempo ${c.desconto_por_tempo_pct}%` : ''}
                </small>
                {c.alerta_reajuste && <span className="dash-selo" style={{ background: '#FBF0D8', color: '#7A4F0E', alignSelf: 'flex-start' }}>Renovação em {c.dias_para_reajuste} dias</span>}
              </li>
            ))}
            {!dados?.contratos.length && <p className="dash-nota">Nenhum gestor cadastrado.</p>}
          </ul>
        </section>
      </div>

      <section className="dash-card" aria-labelledby="fat-ina">
        <div>
          <h2 id="fat-ina">Inadimplência</h2>
          <small>
            Faixas: até {dados?.inadimplencia.limites.curta} dias, até {dados?.inadimplencia.limites.media} dias e acima. No atraso longo o gestor é avisado {dados?.inadimplencia.limites.aviso_desligamento_dias} dias antes de os agentes serem desligados.
          </small>
        </div>
        <div className="fat-faixas">
          {dados?.inadimplencia.faixas.map((f) => (
            <article key={f.faixa} style={{ borderTopColor: FAIXAS[f.faixa - 1].cor }}>
              <strong>{FAIXAS[f.faixa - 1].nome}</strong>
              <span className="fat-faixa-valor">{brl(f.valor)}</span>
              <small>{f.n} cobrança(s) · {FAIXAS[f.faixa - 1].acao}</small>
            </article>
          ))}
        </div>
        <ul className="fat-atrasados">
          {dados?.inadimplencia.atrasados.map((a) => (
            <li key={a.cobranca_id}>
              <div>
                <strong>{a.gestor}</strong>
                <small>{a.tipo_rotulo} · {brl(a.saldo)} · venceu em {dataBr(a.vencimento)} · {a.dias_atraso} dias de atraso</small>
              </div>
            </li>
          ))}
          {dados && !dados.inadimplencia.atrasados.length && <li className="dash-nota">Nenhuma cobrança em atraso.</li>}
        </ul>
      </section>

      <section className="dash-card dash-card-tabela" aria-labelledby="fat-his">
        <div className="dash-card-topo">
          <h2 id="fat-his">Histórico de pagamentos</h2>
          <small>Data, valor e comprovante de cada recebimento, com quem registrou</small>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Data</th>
                <th>Gestor</th>
                <th>Referência</th>
                <th style={{ textAlign: 'right' }}>Valor</th>
                <th>Forma</th>
                <th>Comprovante</th>
                <th>Registrado por</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {dados?.pagamentos.map((p) => (
                <tr key={p.id}>
                  <td style={{ fontFamily: "'DM Mono',monospace", fontSize: 13 }}>{dataBr(p.data)}</td>
                  <td style={{ fontWeight: 600 }}>{p.gestor}</td>
                  <td>{p.referencia}</td>
                  <td className="dash-num">{brl(p.valor)}</td>
                  <td>{FORMAS[p.forma] ?? p.forma}</td>
                  <td>{p.comprovante ? (/^https?:\/\//.test(p.comprovante) ? <a href={p.comprovante} target="_blank" rel="noreferrer">Ver comprovante</a> : p.comprovante) : <span className="dash-nota">sem comprovante</span>}</td>
                  <td>{p.por || '—'}</td>
                  <td style={{ textAlign: 'right' }}>
                    <button type="button" className="secondary" onClick={() => desfazer(p.id, p.gestor)}>
                      Desfazer
                    </button>
                  </td>
                </tr>
              ))}
              {dados && !dados.pagamentos.length && (
                <tr>
                  <td colSpan={8}>Nenhum pagamento registrado ainda.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
