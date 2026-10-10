import { useEffect, useState } from 'react';
import type { Api } from '../api';
import type { AdminLeadsResumo } from '../types';
import { NumeroAnimado } from '../components/NumeroAnimado';
import { SkeletonTiles } from '../components/Skeleton';

// Painel Admin → Leads: só agregados (volume, classificação, evolução mensal) de todas as empresas, nunca conversas.
const COR_TEMP: Record<string, string> = { Quente: '#E2574C', Qualificado: '#D4A72C', Frio: '#2563EB', Desconfiado: '#8C7B69', Desqualificado: '#C9BBA9' };
const COR_TIPO: Record<string, string> = { automatico: '#2563EB', aguardando: '#C88A1E', equipe: '#D9531A', despachado: '#2F7D5C', especial: '#7C3AED', desqualificado: '#8C7B69', nao_prosseguiram: '#D8CBBB' };
const PERIODOS: [AdminLeadsResumo['periodo'], string][] = [['30', '30 dias'], ['90', '90 dias'], ['all', 'Todo o período']];
const MES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

export function AdminLeads({ api }: { api: Api }) {
  const [periodo, setPeriodo] = useState<AdminLeadsResumo['periodo']>('30');
  const [gestor, setGestor] = useState('');
  const [d, setD] = useState<AdminLeadsResumo | null>(null);
  const [error, setError] = useState('');
  const [gestores, setGestores] = useState<AdminLeadsResumo['gestores']>([]);

  useEffect(() => {
    setError('');
    api(`/admin-leads/?periodo=${periodo}${gestor ? `&gestor=${gestor}` : ''}`)
      .then((r: AdminLeadsResumo) => {
        setD(r);
        setGestores(r.gestores);
      })
      .catch((e) => setError(e.message));
  }, [api, periodo, gestor]);

  const tipos = d ? [...d.tipos].sort((a, b) => b.valor - a.valor) : [];
  const somaTipos = tipos.reduce((t, i) => t + i.valor, 0) || 1;
  let acc = 0;
  const fundo = tipos.length
    ? `conic-gradient(${tipos.map((i) => { const ini = acc; acc += (i.valor / somaTipos) * 360; return `${COR_TIPO[i.chave]} ${ini.toFixed(2)}deg ${acc.toFixed(2)}deg`; }).join(',')})`
    : undefined;
  const maxMes = Math.max(1, ...(d?.mensal.map((m) => m.valor) ?? [1]));
  const r = d?.resumo;

  return (
    <>
      <header className="page-header" style={{ alignItems: 'flex-end' }}>
        <div>
          <small className="eyebrow">Plataforma</small>
          <h1>Leads</h1>
          <p>Quantos leads cada empresa recebe, como foram classificados e como evoluem mês a mês.</p>
        </div>
        <div className="adm-filtros">
          <label className="select-field">
            <select aria-label="Gestor" value={gestor} onChange={(e) => setGestor(e.target.value)}>
              <option value="">Todos os gestores</option>
              {gestores.map((g) => (
                <option key={g.id} value={g.id}>{g.nome}</option>
              ))}
            </select>
          </label>
          <div className="adm-seg" role="group" aria-label="Período">
            {PERIODOS.map(([k, nome]) => (
              <button key={k} type="button" aria-pressed={periodo === k} className={periodo === k ? 'ativo' : ''} onClick={() => setPeriodo(k)}>
                {nome}
              </button>
            ))}
          </div>
        </div>
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {!d ? (
        <SkeletonTiles />
      ) : (
        <>
          <section className="adm-kpis adm-kpis-4" aria-label="Resumo">
            <article className="dash-card">
              <small>Atendimentos</small>
              <strong><NumeroAnimado valor={r!.atendimentos} /></strong>
              <small>incluindo os que não prosseguiram</small>
            </article>
            <article className="dash-card">
              <small>Leads classificados</small>
              <strong><NumeroAnimado valor={r!.classificados} /></strong>
              <small>{Math.round((r!.classificados / Math.max(1, r!.atendimentos)) * 100)}% do total</small>
            </article>
            <article className="dash-card">
              <small>Quentes</small>
              <strong><NumeroAnimado valor={r!.quentes} /></strong>
              <small>maior prioridade de atendimento</small>
            </article>
            <article className="dash-card">
              <small>Não prosseguiram</small>
              <strong><NumeroAnimado valor={r!.nao_prosseguiram} /></strong>
              <small>apagados automaticamente</small>
            </article>
          </section>

          <div className="dash-duas">
            <section className="dash-card" aria-labelledby="al-tipos">
              <div>
                <h2 id="al-tipos">Tipos de atendimento</h2>
                <small>Onde cada atendimento está agora</small>
              </div>
              <div className="adm-pizza-linha">
                <div className="adm-pizza" style={{ background: fundo }} role="img" aria-label={`Tipos de atendimento: ${tipos.map((i) => `${i.valor} ${i.rotulo.toLowerCase()}`).join(', ')}`} />
                <ul className="adm-legenda">
                  {tipos.map((i) => (
                    <li key={i.chave}>
                      <span style={{ background: COR_TIPO[i.chave] }} aria-hidden="true" />
                      {i.rotulo}
                      <strong>{i.valor}</strong>
                      <small>{Math.round((i.valor / somaTipos) * 100)}%</small>
                    </li>
                  ))}
                </ul>
              </div>
            </section>

            <section className="dash-card" aria-labelledby="al-mes">
              <div>
                <h2 id="al-mes">Atendimentos por mês</h2>
                <small>Total de atendimentos, incluindo os que não prosseguiram</small>
              </div>
              <div className="adm-colunas" role="img" aria-label={`Atendimentos por mês: ${d.mensal.map((m) => `${MES[Number(m.mes.slice(5)) - 1]} ${m.valor}`).join(', ')}`}>
                {d.mensal.map((m, i) => (
                  <div key={m.mes}>
                    <span>{m.valor}</span>
                    <span className="adm-coluna" style={{ height: `${Math.max(3, (m.valor / maxMes) * 190)}px`, background: i === d.mensal.length - 1 ? '#D9531A' : '#EBCDB6' }} />
                    <small>{MES[Number(m.mes.slice(5)) - 1]}</small>
                  </div>
                ))}
              </div>
            </section>
          </div>

          <section className="dash-card dash-card-tabela" aria-labelledby="al-emp">
            <div>
              <h2 id="al-emp">Leads por empresa</h2>
              <small>Cada empresa com a distribuição por classificação</small>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Empresa</th>
                    <th>Leads</th>
                    <th>Classificação</th>
                    {d.temperaturas.map((t) => (
                      <th key={t}>
                        <span className="adm-th-temp"><span style={{ background: COR_TEMP[t] }} aria-hidden="true" />{t}</span>
                      </th>
                    ))}
                    <th>Não prosseguiram</th>
                  </tr>
                </thead>
                <tbody>
                  {d.empresas.map((e) => {
                    const soma = d.temperaturas.reduce((t, k) => t + (e.temperaturas[k] ?? 0), 0) || 1;
                    return (
                      <tr key={e.empresa_id}>
                        <td>
                          <strong style={{ display: 'block' }}>{e.empresa}</strong>
                          <small>{e.gestor || 'sem gestor'}</small>
                        </td>
                        <td>{e.total}</td>
                        <td>
                          <span className="adm-mini" aria-hidden="true">
                            {d.temperaturas.map((t) => (
                              <span key={t} style={{ width: `${((e.temperaturas[t] ?? 0) / soma) * 100}%`, background: COR_TEMP[t] }} />
                            ))}
                          </span>
                        </td>
                        {d.temperaturas.map((t) => (
                          <td key={t}>{e.temperaturas[t] ?? 0}</td>
                        ))}
                        <td>{e.nao_prosseguiram}</td>
                      </tr>
                    );
                  })}
                  {!d.empresas.length && (
                    <tr>
                      <td colSpan={d.temperaturas.length + 4}>Nenhuma empresa neste filtro.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </>
  );
}
