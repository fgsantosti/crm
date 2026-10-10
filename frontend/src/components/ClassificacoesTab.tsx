import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Api } from '../api';
import type { Company } from '../types';
import { TEMPERATURA_VISUAL } from './KanbanVisual';
import { Spinner } from './Skeleton';
import { ICONE_ALERTA, ImpactoClassificacaoDialog, type LeadAfetada } from './ImpactoClassificacaoDialog';
import { SaidaAnimada } from '../popupSaida';

// Aba "Classificações" do Roteiro: onde terminam as faixas de nota (rigorosidade), legenda editável,
// teste rápido e a regra em texto que o agente lê antes de dar as notas. O CRM continua calculando a temperatura.

const NOMES = ['Desqualificado', 'Desconfiado', 'Frio', 'Qualificado', 'Quente'];
const CORES = [
  '#C9BBA9', // Desqualificado
  '#8C7B69', // Desconfiado
  TEMPERATURA_VISUAL.Frio.ponto,
  TEMPERATURA_VISUAL.Qualificado.ponto,
  TEMPERATURA_VISUAL.Quente.ponto,
];
const EFEITOS = [
  'Conclui sozinho e libera o número. Só aparece nas estatísticas.',
  'Conclui sozinho e libera o número. Só aparece nas estatísticas.',
  'Vai para Qualificados, no fim da fila.',
  'Vai para Qualificados, no meio da fila.',
  'Vai para Qualificados, no topo da fila.',
];
const PADRAO = [3, 5, 7, 9];
const PRESETS: { chave: 'flexivel' | 'padrao' | 'rigoroso'; nome: string; cortes: number[]; ajuda: string }[] = [
  { chave: 'flexivel', nome: 'Flexível', cortes: [2, 4, 6, 8], ajuda: 'Exige menos para subir de classificação: mais leads chegam a Qualificado e Quente.' },
  { chave: 'padrao', nome: 'Padrão', cortes: PADRAO, ajuda: 'Faixas originais do CRM.' },
  { chave: 'rigoroso', nome: 'Rigoroso', cortes: [4, 6, 8, 9.5], ajuda: 'Exige mais para subir de classificação: só os casos mais fortes chegam a Quente.' },
];
const MAX_REGRA = 1500;

const arredonda = (n: number) => Math.round(n * 10) / 10;
const fmt = (n: number) => arredonda(n).toFixed(1).replace('.', ',');
const iguais = (a: number[], b: number[]) => a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) < 0.001);

export function ClassificacoesTab({ api, company, canEdit, onSalvo }: { api: Api; company: Company; canEdit: boolean; onSalvo: (c: Company) => void }) {
  const inicial = (company.classificacao_cortes?.length === 4 ? company.classificacao_cortes : PADRAO).map(arredonda);
  const kanbanInicial = Math.min(4, Math.max(0, company.classificacao_kanban_a_partir_de ?? 2));
  const [cortes, setCortes] = useState<number[]>(inicial);
  const [regra, setRegra] = useState(company.classificacao_regra ?? '');
  const [salvo, setSalvo] = useState({ cortes: inicial, regra: company.classificacao_regra ?? '', kanbanDe: kanbanInicial });
  const [kanbanDe, setKanbanDe] = useState(kanbanInicial);
  const [teste, setTeste] = useState('7.4');
  const [saving, setSaving] = useState(false);
  const [erro, setErro] = useState('');
  const [aviso, setAviso] = useState('');
  const [afetadas, setAfetadas] = useState<LeadAfetada[]>([]);
  const [alteradas, setAlteradas] = useState<LeadAfetada[]>([]);
  const totalImpacto = afetadas.length + alteradas.length;
  const [impactoAberto, setImpactoAberto] = useState(false);

  const limites = useMemo(() => [0, ...cortes, 10], [cortes]);
  const presetAtual = PRESETS.find((p) => iguais(p.cortes, cortes))?.chave ?? 'personalizado';
  const alterado = !iguais(cortes, salvo.cortes) || regra.trim() !== salvo.regra.trim() || kanbanDe !== salvo.kanbanDe;

  // Simulação: quais leads de Classificados sairiam do Kanban com as faixas em edição (não grava nada).
  const mudouFaixas = !iguais(cortes, salvo.cortes) || kanbanDe !== salvo.kanbanDe;
  useEffect(() => {
    if (!canEdit || !mudouFaixas) {
      setAfetadas([]);
      setAlteradas([]);
      return;
    }
    let ativo = true;
    const timer = setTimeout(() => {
      api(`/companies/${company.id}/classificacao/impacto/`, { method: 'POST', body: JSON.stringify({ classificacao_cortes: cortes, classificacao_kanban_a_partir_de: kanbanDe }) })
        .then((d: { afetadas: LeadAfetada[]; alteradas: LeadAfetada[] }) => {
          if (!ativo) return;
          setAfetadas(d.afetadas ?? []);
          setAlteradas(d.alteradas ?? []);
        })
        .catch(() => {
          if (!ativo) return;
          setAfetadas([]);
          setAlteradas([]);
        });
    }, 350);
    return () => {
      ativo = false;
      clearTimeout(timer);
    };
  }, [api, company.id, canEdit, mudouFaixas, cortes, kanbanDe]);
  useEffect(() => {
    if (!totalImpacto) setImpactoAberto(false);
  }, [totalImpacto]);

  function mudar(i: number, bruto: string | number) {
    let v = typeof bruto === 'number' ? bruto : parseFloat(String(bruto).replace(',', '.'));
    if (Number.isNaN(v)) return;
    const min = i === 0 ? 0.1 : cortes[i - 1] + 0.1;
    const max = i === 3 ? 9.9 : cortes[i + 1] - 0.1;
    v = Math.min(max, Math.max(min, arredonda(v)));
    setCortes((c) => c.map((x, j) => (j === i ? arredonda(v) : x)));
    setAviso('');
  }

  // Marcar uma classificação marca também todas acima dela; desmarcar desmarca também todas abaixo (a fila é contínua).
  function alternarKanban(i: number) {
    setKanbanDe(i >= kanbanDe ? Math.min(4, i + 1) : i);
    setAviso('');
  }

  const media = parseFloat(teste.replace(',', '.'));
  const indiceTeste = Number.isNaN(media) ? -1 : Math.min(4, cortes.filter((c) => media >= c).length);
  const posTeste = Number.isNaN(media) ? null : Math.min(10, Math.max(0, media)) / 10;

  async function salvar() {
    const concluidas = afetadas.length;
    setImpactoAberto(false);
    setSaving(true);
    setErro('');
    setAviso('');
    try {
      const c: Company = await api(`/companies/${company.id}/`, { method: 'PATCH', body: JSON.stringify({ classificacao_cortes: cortes, classificacao_regra: regra.trim(), classificacao_kanban_a_partir_de: kanbanDe }) });
      onSalvo(c);
      setSalvo({ cortes: (c.classificacao_cortes ?? cortes).map(arredonda), regra: c.classificacao_regra ?? regra.trim(), kanbanDe: c.classificacao_kanban_a_partir_de ?? kanbanDe });
      setAfetadas([]);
      setAlteradas([]);
      setAviso(`Alterações salvas. O agente usa as novas faixas e a regra a partir da próxima conversa; as leads de Classificados foram reavaliadas${concluidas ? ` e ${concluidas} concluíram como desqualificadas` : ''}.`);
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="classif">
      <section className="classif-card" aria-labelledby="classif-faixas">
        <div className="classif-topo">
          <div>
            <h2 id="classif-faixas">Faixas de classificação</h2>
            <p>
              O agente dá notas de 0 a 10 por pergunta. O CRM tira a média ponderada pelos pesos e a classificação sai da faixa em que a média cai.
              Arraste os botões ou digite os valores.
            </p>
          </div>
          <div>
            <span className="classif-rotulo" id="classif-rig">Rigorosidade</span>
            <div className="segmentado" role="group" aria-labelledby="classif-rig">
              {PRESETS.map((p) => (
                <button key={p.chave} type="button" aria-pressed={presetAtual === p.chave} title={p.ajuda} disabled={!canEdit} onClick={() => { setCortes(p.cortes); setAviso(''); }}>
                  {p.nome}
                </button>
              ))}
              <button type="button" aria-pressed={presetAtual === 'personalizado'} disabled tabIndex={-1} title="Aparece quando você ajusta as faixas manualmente">
                Personalizado
              </button>
            </div>
          </div>
        </div>

        <ul className="classif-legenda" aria-label="Legenda das classificações">
          {NOMES.map((nome, i) => (
            <li key={nome} title={EFEITOS[i]}>
              <span className="classif-nome">
                <span className="classif-cor" style={{ background: CORES[i] }} aria-hidden="true" />
                {nome}
              </span>
              <label className="classif-kanban">
                <input type="checkbox" checked={i >= kanbanDe} disabled={!canEdit || i === 4} onChange={() => alternarKanban(i)} />
                Vai para o Kanban
              </label>
              <span className="classif-faixa">
                <span>de {fmt(limites[i])}</span>
                {i < 4 ? (
                  <label>
                    até
                    <input
                      type="number"
                      min={0}
                      max={10}
                      step={0.1}
                      aria-label={`Nota final de ${nome}`}
                      disabled={!canEdit}
                      value={cortes[i]}
                      onChange={(e) => mudar(i, e.target.value)}
                    />
                  </label>
                ) : (
                  <span>até 10,0</span>
                )}
              </span>
            </li>
          ))}
        </ul>

        <div className="classif-linha" style={{ ['--n' as string]: 0 }}>
          {cortes.map((v, i) => (
            <span key={i} className="classif-balao" style={{ left: `calc(14px + (100% - 28px) * ${v / 10})` }} aria-hidden="true">
              <span>{fmt(v)}</span>
              <svg width="10" height="6" viewBox="0 0 10 6"><path d="M0 0h10L5 6z" fill="currentColor" /></svg>
            </span>
          ))}
          <div className="classif-trilho">
            <div className="classif-trechos">
              {NOMES.map((nome, i) => (
                <span key={nome} style={{ flex: `${Math.max(0.0001, limites[i + 1] - limites[i])} 1 0`, background: CORES[i] }} />
              ))}
            </div>
            {cortes.map((v, i) => (
              <input
                key={i}
                className="classif-alca"
                type="range"
                min={0}
                max={10}
                step={0.1}
                value={v}
                disabled={!canEdit}
                aria-label={`Divisão entre ${NOMES[i]} e ${NOMES[i + 1]}`}
                onChange={(e) => mudar(i, e.target.value)}
              />
            ))}
          </div>
          <div className="classif-escala" aria-hidden="true">
            {[0, 2, 4, 6, 8, 10].map((n) => (
              <span key={n}>{n}</span>
            ))}
          </div>
          {posTeste !== null && (
            <svg className="classif-marcador" width="12" height="8" viewBox="0 0 12 8" aria-hidden="true" style={{ left: `calc(14px + (100% - 28px) * ${posTeste})`, color: CORES[indiceTeste] }}>
              <path d="M6 0l6 8H0z" fill="currentColor" />
            </svg>
          )}
        </div>

        <div className="classif-teste">
          <label>
            Testar uma média
            <input type="number" min={0} max={10} step={0.1} value={teste} onChange={(e) => setTeste(e.target.value)} />
          </label>
          {indiceTeste >= 0 && (
            <span>
              cai em{' '}
              <strong>
                <span className="classif-cor" style={{ background: CORES[indiceTeste] }} aria-hidden="true" />
                {NOMES[indiceTeste]}
              </strong>
            </span>
          )}
          <small>Só simula; não altera nenhum lead.</small>
          <div className="classif-kanban-lista">
            <span>Vão para o Kanban:</span>
            {NOMES.map((nome, i) => i >= kanbanDe && (
              <span key={nome} className="classif-kanban-chip">
                <span className="classif-cor" style={{ background: CORES[i] }} aria-hidden="true" />
                {nome}
              </span>
            ))}
            {kanbanDe > 0 && <small>{NOMES.slice(0, kanbanDe).join(' e ')} concluem sozinhos, fora do Kanban.</small>}
          </div>
        </div>
      </section>

      <section className="classif-card" aria-labelledby="classif-regra">
        <div>
          <h2 id="classif-regra">Regra de classificação</h2>
          <p>
            Texto que o agente lê antes de dar as notas e classificar. Descreva o que deve pesar mais ou menos no caso desta empresa. A classificação final
            continua sendo calculada pelo CRM com as faixas acima.
          </p>
        </div>
        <label className="classif-regra">
          Critério para o agente
          <textarea
            rows={6}
            maxLength={MAX_REGRA}
            disabled={!canEdit}
            value={regra}
            placeholder="Ex.: dê nota alta a quem tem prazo judicial correndo ou benefício cortado; nota baixa a quem só quer saber se tem direito, sem situação concreta."
            onChange={(e) => { setRegra(e.target.value); setAviso(''); }}
          />
        </label>
        <div className="classif-rodape-regra">
          <small>{regra.length} / {MAX_REGRA} caracteres. Evite dados pessoais de clientes.</small>
          <small>Vale para todas as áreas.</small>
        </div>
      </section>

      {erro && <p role="alert" className="error">{erro}</p>}
      {canEdit && (
        <div className="classif-acoes">
          <button type="button" disabled={saving || !alterado} onClick={() => (totalImpacto ? setImpactoAberto(true) : salvar())}>
            {saving && <Spinner />}
            Salvar alterações
          </button>
          <button type="button" className="secondary" disabled={saving} onClick={() => { setCortes(PADRAO); setRegra(''); setKanbanDe(2); setAviso(''); }}>
            Restaurar padrão
          </button>
          {aviso && <span role="status" className="classif-aviso">{aviso}</span>}
        </div>
      )}
      {/* Portal no body: o botão é fixo na tela (canto inferior direito), sem acompanhar a rolagem nem o contêiner animado da página. */}
      {totalImpacto > 0 &&
        createPortal(
          <SaidaAnimada>
            <button
              type="button"
              className="impacto-fab"
              aria-haspopup="dialog"
              aria-label={`${totalImpacto} lead${totalImpacto === 1 ? ' seria afetada' : 's seriam afetadas'} pelas novas faixas. Ver lista.`}
              title={`${totalImpacto} lead${totalImpacto === 1 ? ' afetada' : 's afetadas'}`}
              onClick={() => setImpactoAberto(true)}
            >
              <svg width="26" height="26" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">{ICONE_ALERTA}</svg>
            </button>
          </SaidaAnimada>,
          document.body,
        )}
      {impactoAberto && totalImpacto > 0 && (
        <ImpactoClassificacaoDialog afetadas={afetadas} alteradas={alteradas} cores={Object.fromEntries(NOMES.map((n, i) => [n, CORES[i]]))} saving={saving} onVoltar={() => setImpactoAberto(false)} onSalvar={salvar} />
      )}
    </div>
  );
}
