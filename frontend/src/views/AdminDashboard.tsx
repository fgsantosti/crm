import { useEffect, useState } from 'react';
import type { Api } from '../api';
import type { AdminVisaoGeral } from '../types';
import type { AdminView } from '../components/AdminSidebar';
import { SkeletonTiles } from '../components/Skeleton';
import { NumeroAnimado } from '../components/NumeroAnimado';

// Painel Admin → Visão geral: o que precisa de atenção, quanto a plataforma fatura e onde está o volume.
export const brl = (v: string | number) => `R$ ${Number(v).toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
const quando = (iso: string) => new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
const GRAVIDADE = {
  alta: { fundo: '#FBE6E3', cor: '#A3271C' },
  media: { fundo: '#FBF0D8', cor: '#7A4F0E' },
  baixa: { fundo: '#F1E8DB', cor: '#4E4136' },
};
const SIGLA = { chave: 'Ch', cobranca: 'R$', teste: 'Te', empresa: 'Em', gestor: 'Ge' };
const DESTINO: Record<string, AdminView> = { chave: 'notificacoes', cobranca: 'faturamento', teste: 'cobrancas', empresa: 'painel', gestor: 'gestores' };

export function AdminDashboard({ api, onNavigate }: { api: Api; onNavigate: (v: AdminView) => void }) {
  const [d, setD] = useState<AdminVisaoGeral | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api('/admin-visao-geral/')
      .then(setD)
      .catch((e) => setError(e.message));
  }, [api]);

  const maxVolume = Math.max(1, ...(d?.volume.map((v) => v.leads) ?? [1]));
  const k = d?.kpis;
  return (
    <>
      <header className="page-header">
        <div>
          <small className="eyebrow">Plataforma</small>
          <h1>Visão geral</h1>
          <p>O que precisa da sua atenção hoje, quanto a plataforma fatura e onde está o volume.</p>
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
          <section className="adm-kpis" aria-label="Indicadores">
            <article className="dash-card">
              <small>Mensalidade estimada</small>
              <strong>{brl(k!.mensalidade_estimada)}</strong>
              <small>cobranças do mês corrente</small>
            </article>
            <article className="dash-card">
              <small>Gestores</small>
              <strong><NumeroAnimado valor={k!.gestores} /></strong>
              <small>{k!.gestores_sem_acesso ? `${k!.gestores_sem_acesso} aguardando 1º acesso` : 'todos já acessaram'}</small>
            </article>
            <article className="dash-card">
              <small>Empresas</small>
              <strong><NumeroAnimado valor={k!.empresas} /></strong>
              <small>{k!.empresas_sem_gestor ? `${k!.empresas_sem_gestor} sem gestor` : 'todas com gestor'}</small>
            </article>
            <article className="dash-card">
              <small>Agentes</small>
              <strong><NumeroAnimado valor={k!.agentes} /></strong>
              <small>{k!.agentes_adicionais ? `${k!.agentes_adicionais} adicional(is)` : 'nenhum adicional'}</small>
            </article>
            <article className="dash-card">
              <small>Leads em 30 dias</small>
              <strong><NumeroAnimado valor={k!.leads_30_dias} /></strong>
              <small>somando todas as empresas</small>
            </article>
          </section>

          <div className="dash-duas">
            <section className="dash-card" aria-labelledby="vg-aten">
              <div className="adm-topo">
                <h2 id="vg-aten">Precisa de atenção</h2>
                <span className="dash-selo" style={{ background: '#FBF0D8', color: '#7A4F0E' }}>{d.alertas.length}</span>
              </div>
              <ul className="adm-lista">
                {d.alertas.map((a, i) => (
                  <li key={i}>
                    <span className="adm-sigla" style={{ background: GRAVIDADE[a.gravidade].fundo, color: GRAVIDADE[a.gravidade].cor }} aria-hidden="true">{SIGLA[a.tipo]}</span>
                    <div>
                      <strong>{a.titulo}</strong>
                      <small>{a.detalhe}</small>
                    </div>
                    <button type="button" className="adm-link" onClick={() => onNavigate(DESTINO[a.tipo])}>Resolver →</button>
                  </li>
                ))}
                {!d.alertas.length && <li className="dash-nota">Nada pendente. Tudo em dia.</li>}
              </ul>
            </section>

            <section className="dash-card" aria-labelledby="vg-vol">
              <div>
                <h2 id="vg-vol">Volume de leads por empresa</h2>
                <small>Últimos 30 dias, incluindo os que não prosseguiram</small>
              </div>
              <ul className="adm-barras">
                {d.volume.map((v) => (
                  <li key={v.empresa_id}>
                    <span>{v.empresa}</span>
                    <span className="adm-barra"><span style={{ width: `${Math.max(2, (v.leads / maxVolume) * 100)}%` }} /></span>
                    <strong>{v.leads}</strong>
                  </li>
                ))}
                {!d.volume.length && <li className="dash-nota">Nenhuma empresa cadastrada.</li>}
              </ul>
            </section>
          </div>

          <div className="dash-duas">
            <section className="dash-card dash-card-tabela" aria-labelledby="vg-fat">
              <div>
                <h2 id="vg-fat">Faturamento por gestor</h2>
                <small>Mensalidade do mês corrente</small>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Gestor</th>
                      <th>Empresas</th>
                      <th>Agentes extras</th>
                      <th>Mensalidade</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.faturamento.map((f) => (
                      <tr key={f.gestor_id}>
                        <td><strong>{f.gestor}</strong></td>
                        <td>{f.empresas}</td>
                        <td>{f.extras}</td>
                        <td>{f.total ? brl(f.total) : '—'}</td>
                      </tr>
                    ))}
                    {!d.faturamento.length && (
                      <tr>
                        <td colSpan={4}>Nenhum gestor cadastrado.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="dash-card" aria-labelledby="vg-rec">
              <h2 id="vg-rec">Atividade recente</h2>
              <ul className="adm-lista adm-atividade">
                {d.atividade.map((t, i) => (
                  <li key={i}>
                    <span className="cob-quando">{quando(t.quando)}</span>
                    <span>{t.texto}</span>
                  </li>
                ))}
                {!d.atividade.length && <li className="dash-nota">Sem atividade ainda.</li>}
              </ul>
            </section>
          </div>
        </>
      )}
    </>
  );
}
