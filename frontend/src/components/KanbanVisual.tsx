import type { Lead } from '../types';

// Peças visuais do Kanban (Central de leads e Dashboard da empresa). Cada tela monta o <article>
// do card com os próprios handlers (arrastar, abrir, fechar lead) e usa o conteúdo daqui.

export type ColunaVisual = { key: string; label: string; cor: string; regra: string };

/** Temperatura -> cor do ponto e do selo (selo com texto escuro, contraste AA sobre o fundo claro). */
export const TEMPERATURA_VISUAL: Record<string, { ponto: string; fundo: string; texto: string }> = {
  Quente: { ponto: '#E2574C', fundo: '#FBE6E3', texto: '#A3271C' },
  Qualificado: { ponto: '#D4A72C', fundo: '#FBF0D8', texto: '#7A4F0E' },
  Frio: { ponto: '#2563EB', fundo: '#E3ECFD', texto: '#1D4FBF' },
};

const DESFECHO_VISUAL: Record<string, { rotulo: string; fundo: string; texto: string }> = {
  encerrado: { rotulo: 'Encerrado', fundo: '#EEF7F1', texto: '#245F46' },
  comprometido: { rotulo: 'Comprometido', fundo: '#FCF4E4', texto: '#7A4F0E' },
  falha: { rotulo: 'Falha', fundo: '#FBEDEA', texto: '#93251B' },
};

function horaMinuto(d: Date) {
  return d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

/** "hoje, 09:14" / "ontem, 17:02" / "06/10, 10:31". */
export function dataCurta(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  const hoje = new Date();
  const ontem = new Date();
  ontem.setDate(hoje.getDate() - 1);
  if (d.toDateString() === hoje.toDateString()) return `hoje, ${horaMinuto(d)}`;
  if (d.toDateString() === ontem.toDateString()) return `ontem, ${horaMinuto(d)}`;
  return `${d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}, ${horaMinuto(d)}`;
}

/** "agora" / "há 12 min" / "há 3 h" / "há 2 dias". */
export function tempoRelativo(iso: string | null | undefined): string {
  if (!iso) return '';
  const min = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (min < 1) return 'agora';
  if (min < 60) return `há ${min} min`;
  const h = Math.round(min / 60);
  if (h < 24) return `há ${h} h`;
  const dias = Math.round(h / 24);
  return `há ${dias} dia${dias === 1 ? '' : 's'}`;
}

function iniciais(nome: string) {
  const partes = nome.trim().split(/\s+/).filter(Boolean);
  return ((partes[0]?.[0] ?? '') + (partes.length > 1 ? partes[partes.length - 1][0] : '')).toUpperCase() || '?';
}

function rodape(lead: Lead, coluna: string): string {
  if (coluna === 'novos') {
    const lembrete = lead.lembrete_enviado_em;
    if (lembrete && (!lead.last_contact || new Date(lead.last_contact) <= new Date(lembrete))) return `Lembrete enviado ${tempoRelativo(lembrete)}`;
    return lead.last_contact ? `Última mensagem ${tempoRelativo(lead.last_contact)}` : `Chegou ${tempoRelativo(lead.created_at)}`;
  }
  if (coluna === 'despacho' && lead.especialidade) return lead.especialidade;
  return `Chegou ${dataCurta(lead.created_at)}`;
}

/** Cabeçalho da coluna: ponto da etapa, nome, contagem e a regra de ordenação. */
export function KanbanColunaHead({ coluna, total }: { coluna: ColunaVisual; total: number }) {
  return (
    <header className="kb-col-head">
      <div className="kb-col-title">
        <span className="kb-dot" style={{ background: coluna.cor }} aria-hidden="true" />
        <h3>{coluna.label}</h3>
        <span className="kb-count" aria-label={`${total} lead${total === 1 ? '' : 's'}`}>{total}</span>
      </div>
      <small>{coluna.regra}</small>
    </header>
  );
}

/** Miolo do card: nome/telefone com selo, demanda (2 linhas) e rodapé com tempo e responsável. */
export function KanbanCardConteudo({ lead, coluna, meId, compacto = false }: { lead: Lead; coluna: string; meId?: number; compacto?: boolean }) {
  const temp = TEMPERATURA_VISUAL[lead.temperature];
  const desfecho = coluna === 'despacho' ? DESFECHO_VISUAL[lead.desfecho_pendente] : undefined;
  // Novos: a etapa vai numa linha própria (o id da pergunta é longo e cortaria o nome).
  const selo = compacto || coluna === 'novos'
    ? null
    : desfecho
      ? desfecho
      : temp
        ? { rotulo: lead.temperature, fundo: temp.fundo, texto: temp.texto }
        : null;
  const mostrarDono = !!lead.owner && (coluna === 'negociacao' || coluna === 'despacho');
  const ehMeu = mostrarDono && lead.owner === meId;
  return (
    <>
      <div className="kb-card-top">
        <span className="kb-dot kb-dot-card" style={{ background: coluna === 'novos' ? '#2563EB' : temp?.ponto ?? '#B9A893' }} aria-hidden="true" />
        <div className="kb-card-id">
          <strong>{lead.name || 'Sem nome informado'}</strong>
          <small>{lead.contact}</small>
          {coluna === 'novos' && <span className="kb-etapa">{lead.state ? `na pergunta: ${lead.state}` : 'em triagem'}</span>}
          {selo && (
            <span className="kb-etapa" style={{ background: selo.fundo, color: selo.texto }}>
              {selo.rotulo}
            </span>
          )}
        </div>
      </div>
      {!compacto && coluna !== 'novos' && lead.demand && <p className="kb-card-demanda">{lead.demand}</p>}
      {!compacto && (
        <div className="kb-card-foot">
          <small>{rodape(lead, coluna)}</small>
          {mostrarDono && (
            <span className="kb-dono" title={ehMeu ? 'Com você' : `Com ${lead.owner_nome}`}>
              <span className={`kb-avatar${ehMeu ? ' kb-avatar-meu' : ''}`} aria-hidden="true">{iniciais(lead.owner_nome || '?')}</span>
              {ehMeu ? 'Você' : (lead.owner_nome || '').split(/\s+/)[0]}
            </span>
          )}
        </div>
      )}
    </>
  );
}
