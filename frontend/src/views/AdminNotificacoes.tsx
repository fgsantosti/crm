import { useCallback, useEffect, useState } from 'react';
import { fetchTodasAsPaginas, type Api } from '../api';
import type { ChavesGestor, ConfigNotificacao, Gestor, NotificacaoItem } from '../types';
import { Spinner } from '../components/Skeleton';

// Painel Admin → Notificações: chaves de API, e-mail avulso aos gestores e os avisos automáticos (cobrança, teste, atraso, chave).
const dataBr = (iso: string | null | undefined) => (iso ? iso.slice(0, 10).split('-').reverse().join('/') : '—');
const quando = (iso: string) => new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
const SITUACAO: Record<string, { rotulo: string; fundo: string; cor: string }> = {
  valida: { rotulo: 'Válida', fundo: '#EEF7F1', cor: '#245F46' },
  expira: { rotulo: 'Expira em breve', fundo: '#FBF0D8', cor: '#7A4F0E' },
  expirada: { rotulo: 'Expirada', fundo: '#FBE6E3', cor: '#A3271C' },
  sem_chave: { rotulo: 'Sem chave', fundo: '#F1E8DB', cor: '#4E4136' },
  sem_validade: { rotulo: 'Sem validade', fundo: '#EEF7F1', cor: '#245F46' },
};
const MODELOS: { chave: keyof ConfigNotificacao; nome: string; assunto: string; exigeAnexo?: boolean }[] = [
  { chave: 'texto_cobranca', nome: 'Lembrete de cobrança', assunto: 'Lembrete: mensalidade vence em {vencimento}', exigeAnexo: true },
  { chave: 'texto_atraso', nome: 'Cobrança em atraso', assunto: 'Mensalidade em atraso desde {vencimento}', exigeAnexo: true },
  { chave: 'texto_teste', nome: 'Fim do teste', assunto: 'O teste de {empresa} termina em {fim_do_teste}' },
  { chave: 'texto_chave', nome: 'Chave expirando', assunto: 'A chave de API do agente {agente} expira em {chave_expira_em}', exigeAnexo: true },
];

function Chave({ ligado, aoAlternar, nome }: { ligado: boolean; aoAlternar: () => void; nome: string }) {
  return (
    <button type="button" role="switch" aria-checked={ligado} aria-label={nome} className={`chave-switch${ligado ? ' ligada' : ''}`} onClick={aoAlternar}>
      <span />
    </button>
  );
}

export function AdminNotificacoes({ api }: { api: Api }) {
  const [cfg, setCfg] = useState<ConfigNotificacao | null>(null);
  const [chaves, setChaves] = useState<ChavesGestor[]>([]);
  const [historico, setHistorico] = useState<NotificacaoItem[]>([]);
  const [gestores, setGestores] = useState<Gestor[]>([]);
  const [error, setError] = useState('');
  const [aviso, setAviso] = useState('');
  const [salvando, setSalvando] = useState(false);
  const [rodando, setRodando] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [dest, setDest] = useState('todos');
  const [assunto, setAssunto] = useState('');
  const [mensagem, setMensagem] = useState('');
  const [diasTeste, setDiasTeste] = useState('');
  const [diasChave, setDiasChave] = useState('');
  const [anexos, setAnexos] = useState<File[]>([]);
  const [exigeAnexo, setExigeAnexo] = useState(false);

  const carregar = useCallback(() => {
    Promise.all([api('/admin-notificacoes/config/'), api('/admin-notificacoes/chaves/'), api('/admin-notificacoes/historico/'), fetchTodasAsPaginas<Gestor>(api, '/admin-gestores/')])
      .then(([c, k, h, g]) => {
        setCfg(c);
        setDiasTeste((c.teste_dias_avisos ?? []).join(', '));
        setDiasChave((c.chave_dias_avisos ?? []).join(', '));
        setChaves(k.gestores);
        setHistorico(h.itens);
        setGestores(g);
      })
      .catch((e) => setError(e.message));
  }, [api]);
  useEffect(carregar, [carregar]);

  const mudar = <K extends keyof ConfigNotificacao>(k: K, v: ConfigNotificacao[K]) => setCfg((c) => (c ? { ...c, [k]: v } : c));
  const lista = (t: string) => t.split(/[,\s]+/).filter(Boolean).map(Number).filter((n) => !Number.isNaN(n));

  async function salvar() {
    if (!cfg) return;
    setSalvando(true);
    setError('');
    setAviso('');
    try {
      const salvo: ConfigNotificacao = await api('/admin-notificacoes/config/', { method: 'PATCH', body: JSON.stringify({ ...cfg, teste_dias_avisos: lista(diasTeste), chave_dias_avisos: lista(diasChave) }) });
      setCfg(salvo);
      setDiasTeste(salvo.teste_dias_avisos.join(', '));
      setDiasChave(salvo.chave_dias_avisos.join(', '));
      setAviso('Configuração salva.');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSalvando(false);
    }
  }
  async function rodarAgora() {
    setRodando(true);
    setError('');
    setAviso('');
    try {
      const r: Record<string, number> = await api('/admin-notificacoes/processar/', { method: 'POST' });
      const total = Object.values(r).reduce((a, b) => a + b, 0);
      setAviso(total ? `Verificação concluída: ${total} aviso(s) enviado(s) ou registrado(s).` : 'Verificação concluída: nada a enviar hoje.');
      carregar();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRodando(false);
    }
  }
  async function enviar() {
    setEnviando(true);
    setError('');
    setAviso('');
    try {
      const corpo = new FormData();
      corpo.append('gestores', dest === 'todos' ? 'todos' : dest);
      corpo.append('assunto', assunto);
      corpo.append('mensagem', mensagem);
      if (exigeAnexo) corpo.append('exige_anexo', 'true');
      anexos.forEach((a) => corpo.append('anexos', a));
      const r: { enviados: number; resultado: { gestor: string; estado: string; erro: string }[] } = await api('/admin-notificacoes/enviar/', { method: 'POST', body: corpo });
      const falhas = r.resultado.filter((x) => x.estado !== 'enviado');
      setAviso(`${r.enviados} e-mail(s) enviado(s)${falhas.length ? `; ${falhas.length} falhou: ${falhas.map((f) => `${f.gestor} (${f.erro})`).join(', ')}` : ''}.`);
      setAssunto('');
      setMensagem('');
      setAnexos([]);
      setExigeAnexo(false);
      carregar();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setEnviando(false);
    }
  }
  function usarModelo(m: (typeof MODELOS)[number]) {
    if (!cfg) return;
    setAssunto(m.assunto);
    setMensagem(String(cfg[m.chave]));
    setExigeAnexo(!!m.exigeAnexo);
  }

  return (
    <>
      <header className="page-header">
        <div>
          <small className="eyebrow">Plataforma</small>
          <h1>Notificações</h1>
          <p>Controle das chaves de API, e-mails avulsos aos gestores e os avisos automáticos de cobrança, teste, atraso e chave. Os automáticos rodam todo dia às 9h.</p>
        </div>
        <button type="button" className="secondary" disabled={rodando} onClick={rodarAgora}>
          {rodando && <Spinner />}
          Executar verificação agora
        </button>
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

      <section className="dash-card dash-card-tabela" aria-labelledby="not-chaves">
        <div className="dash-card-topo">
          <div>
            <h2 id="not-chaves">Chaves de API</h2>
            <small>Validade da chave do CRM de cada agente e a referência da chave da OpenAI do gestor. O consumo da OpenAI ainda não é medido pelo CRM: confira no painel da OpenAI.</small>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Gestor</th>
                <th>Agente</th>
                <th>Chave do CRM</th>
                <th>Validade</th>
                <th>OpenAI (chave ou plano)</th>
              </tr>
            </thead>
            <tbody>
              {chaves.flatMap((g) =>
                (g.agentes.length ? g.agentes : [null]).map((a, i) => (
                  <tr key={`${g.gestor_id}-${a?.agente ?? i}`}>
                    <td>
                      <strong style={{ display: 'block' }}>{g.gestor}</strong>
                      <small>{g.email || 'sem e-mail'}</small>
                    </td>
                    <td>
                      {a ? (
                        <>
                          <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 13 }}>{a.agente}</span>
                          <small style={{ display: 'block' }}>{a.empresa}</small>
                        </>
                      ) : (
                        <span className="dash-nota">sem agentes</span>
                      )}
                    </td>
                    <td style={{ fontFamily: "'DM Mono',monospace", fontSize: 13 }}>{a?.chave ?? '—'}</td>
                    <td>{a && <span className="dash-selo" style={{ background: SITUACAO[a.situacao].fundo, color: SITUACAO[a.situacao].cor }}>{SITUACAO[a.situacao].rotulo}{a.dias !== null && a.situacao !== 'expirada' ? ` · ${a.dias} dias (${dataBr(a.expira_em)})` : ''}</span>}</td>
                    <td>
                      {g.openai.projeto || g.openai.chave_final || g.openai.modo === 'plano' ? (
                        <>
                          {g.openai.modo === 'plano' ? (
                            <strong style={{ display: 'block' }}>Plano gerido pela Axioma</strong>
                          ) : (
                            <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 13 }}>{g.openai.chave_final ? `sk-••••${g.openai.chave_final}` : '—'}</span>
                          )}
                          <small style={{ display: 'block' }}>{g.openai.projeto}{g.openai.limite_mensal ? ` · limite R$ ${Number(g.openai.limite_mensal).toLocaleString('pt-BR')}` : ''}</small>
                        </>
                      ) : (
                        <span className="dash-nota">não informada</span>
                      )}
                    </td>
                  </tr>
                )),
              )}
              {!chaves.length && (
                <tr>
                  <td colSpan={5}>Nenhum gestor cadastrado.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <div className="dash-duas">
        <section className="dash-card" aria-labelledby="not-env">
          <div>
            <h2 id="not-env">Enviar notificação</h2>
            <small>E-mail avulso para um gestor ou para todos. As variáveis ({'{gestor}'}, {'{empresa}'}, {'{valor}'}, {'{vencimento}'}, {'{fim_do_teste}'}, {'{agente}'}, {'{chave_expira_em}'}) são trocadas pelos dados reais de cada gestor; se faltar o dado, o e-mail não sai e o histórico explica.</small>
          </div>
          <label className="notif-campo">
            Destinatário
            <select value={dest} onChange={(e) => setDest(e.target.value)}>
              <option value="todos">Todos os gestores</option>
              {gestores.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.nome}{g.email ? ` · ${g.email}` : ' · sem e-mail'}
                </option>
              ))}
            </select>
          </label>
          <div className="notif-modelos" role="group" aria-label="Modelos">
            {MODELOS.map((m) => (
              <button key={m.chave} type="button" className="secondary" onClick={() => usarModelo(m)}>
                {m.nome}
              </button>
            ))}
          </div>
          <label className="notif-campo">
            Assunto
            <input value={assunto} onChange={(e) => setAssunto(e.target.value)} />
          </label>
          <label className="notif-campo">
            Mensagem
            <textarea rows={6} value={mensagem} onChange={(e) => setMensagem(e.target.value)} />
          </label>
          <div className="notif-anexos">
            <label className="notif-campo">
              {exigeAnexo ? 'Anexo (obrigatório neste modelo: a cobrança em PDF ou imagem)' : 'Anexos (PDF ou imagem, até 5 MB cada)'}
              <input type="file" multiple accept="application/pdf,image/png,image/jpeg,image/webp" onChange={(e) => { setAnexos((a) => [...a, ...Array.from(e.target.files ?? [])].slice(0, 5)); e.target.value = ''; }} />
            </label>
            {anexos.length > 0 && (
              <ul>
                {anexos.map((a, i) => (
                  <li key={`${a.name}-${i}`}>
                    {a.name}
                    <button type="button" className="secondary" aria-label={`Remover ${a.name}`} onClick={() => setAnexos((x) => x.filter((_, j) => j !== i))}>×</button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="cob-acoes">
            <button type="button" disabled={enviando || !assunto.trim() || !mensagem.trim() || (exigeAnexo && !anexos.length)} onClick={enviar}>
              {enviando && <Spinner />}
              Enviar e-mail
            </button>
          </div>
        </section>

        <section className="dash-card" aria-labelledby="not-cfg">
          <div>
            <h2 id="not-cfg">Avisos automáticos</h2>
            <small>Cada aviso é enviado uma única vez. O desligamento de agentes por atraso ainda não é automático: o CRM só avisa o gestor.</small>
          </div>
          {cfg && (
            <>
              <div className="cob-campos">
                <label className="notif-campo">
                  E-mail remetente
                  <input value={cfg.remetente} placeholder="vazio = remetente padrão do servidor" onChange={(e) => mudar('remetente', e.target.value)} />
                </label>
                <label className="notif-campo">
                  Cópia (financeiro) nas cobranças
                  <input value={cfg.cc} onChange={(e) => mudar('cc', e.target.value)} />
                </label>
              </div>
              <ul className="notif-regras">
                <li>
                  <Chave nome="Lembrete de cobrança" ligado={cfg.lembrete_cobranca_ativo} aoAlternar={() => mudar('lembrete_cobranca_ativo', !cfg.lembrete_cobranca_ativo)} />
                  <span>
                    <strong>Lembrete de cobrança</strong>
                    <small>
                      <input className="notif-num" type="number" min={0} max={60} value={cfg.lembrete_dias_antes} onChange={(e) => mudar('lembrete_dias_antes', Number(e.target.value))} /> dias antes do vencimento (mensal, cópia ao financeiro)
                    </small>
                  </span>
                </li>
                <li>
                  <Chave nome="Fim do teste" ligado={cfg.teste_ativo} aoAlternar={() => mudar('teste_ativo', !cfg.teste_ativo)} />
                  <span>
                    <strong>Fim do teste</strong>
                    <small>
                      Dias antes do fim: <input className="notif-lista" value={diasTeste} onChange={(e) => setDiasTeste(e.target.value)} /> (0 = no dia)
                    </small>
                  </span>
                </li>
                <li>
                  <Chave nome="Atraso curto" ligado={cfg.atraso_f1} aoAlternar={() => mudar('atraso_f1', !cfg.atraso_f1)} />
                  <span>
                    <strong>Atraso curto</strong>
                    <small>Lembrete ao gestor quando a cobrança entra em atraso.</small>
                  </span>
                </li>
                <li>
                  <Chave nome="Atraso médio" ligado={cfg.atraso_f2} aoAlternar={() => mudar('atraso_f2', !cfg.atraso_f2)} />
                  <span>
                    <strong>Atraso médio</strong>
                    <small>Lembrete firme, com cópia ao financeiro.</small>
                  </span>
                </li>
                <li>
                  <Chave nome="Atraso longo" ligado={cfg.atraso_f3} aoAlternar={() => mudar('atraso_f3', !cfg.atraso_f3)} />
                  <span>
                    <strong>Atraso longo</strong>
                    <small>Lembrete e aviso de desligamento dos agentes.</small>
                  </span>
                </li>
                <li>
                  <Chave nome="Chave de API expirando" ligado={cfg.chave_ativo} aoAlternar={() => mudar('chave_ativo', !cfg.chave_ativo)} />
                  <span>
                    <strong>Chave de API expirando</strong>
                    <small>
                      Dias antes de expirar: <input className="notif-lista" value={diasChave} onChange={(e) => setDiasChave(e.target.value)} />
                    </small>
                  </span>
                </li>
              </ul>
              {MODELOS.concat([{ chave: 'texto_desligamento', nome: 'Aviso de desligamento', assunto: '' }]).map((m) => (
                <label key={m.chave} className="notif-campo">
                  Texto: {m.nome}
                  <textarea rows={3} value={String(cfg[m.chave])} onChange={(e) => mudar(m.chave, e.target.value as never)} />
                </label>
              ))}
              <small className="dash-nota">Variáveis: {'{gestor} {empresa} {valor} {vencimento} {fim_do_teste} {agente} {chave_expira_em} {dias_desligamento}'}</small>
              <div className="cob-acoes">
                <button type="button" disabled={salvando} onClick={salvar}>
                  {salvando && <Spinner />}
                  Salvar configuração
                </button>
              </div>
            </>
          )}
        </section>
      </div>

      <section className="dash-card" aria-labelledby="not-his">
        <h2 id="not-his">Histórico de envios</h2>
        <ul className="cob-historico">
          {historico.map((h) => (
            <li key={h.id}>
              <span className="cob-quando">{quando(h.quando)}</span>
              <strong>{h.gestor || '—'}</strong>
              <span>{h.assunto}</span>
              <span>{h.tipo_rotulo}</span>
              <span className="dash-selo" style={h.estado === 'enviado' ? { background: '#EEF7F1', color: '#245F46' } : { background: '#FBE6E3', color: '#A3271C' }} title={h.erro}>
                {h.estado === 'enviado' ? 'Enviado' : `Falhou${h.erro ? `: ${h.erro}` : ''}`}
              </span>
            </li>
          ))}
          {!historico.length && <li className="dash-nota">Nenhum e-mail enviado ainda.</li>}
        </ul>
      </section>
    </>
  );
}
