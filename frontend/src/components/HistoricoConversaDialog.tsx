import { useEffect, useRef, useState } from 'react';
import type { Api } from '../api';
import type { Lead } from '../types';

type MensagemConversa = { quem: 'cliente' | 'agente'; texto: string; quando: string; audio?: boolean; entregue?: boolean };

/**
 * Popup (fundo esmaecido) com o histórico de conversa do lead: mensagens do cliente (texto ou transcrição
 * do áudio) e respostas do agente, da primeira mensagem até a que classificou. Só existe para empresas
 * com "Permitir coleta de histórico de conversa" ligado no Admin.
 */
export function HistoricoConversaDialog({ api, companyId, lead, onClose }: { api: Api; companyId: number; lead: Lead; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [mensagens, setMensagens] = useState<MensagemConversa[] | null>(null);
  const [erro, setErro] = useState('');

  useEffect(() => {
    const dialog = ref.current!;
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.showModal();
    return () => {
      dialog.close();
      document.body.style.overflow = previousOverflow;
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, []);

  useEffect(() => {
    let ativo = true;
    setMensagens(null);
    setErro('');
    api(`/leads/${lead.id}/conversa/?company=${companyId}`)
      .then((r: { mensagens: MensagemConversa[] }) => ativo && setMensagens(r.mensagens))
      .catch((e) => ativo && setErro(e.message));
    return () => {
      ativo = false;
    };
  }, [api, companyId, lead.id]);

  return (
    <dialog
      ref={ref}
      className="lead-dialog"
      aria-labelledby="historico-dialog-title"
      onClose={() => {
        // O StrictMode pode enfileirar close durante a montagem e reabrir em seguida.
        if (ref.current && !ref.current.open) onClose();
      }}
      onClick={(e) => {
        if (e.target !== e.currentTarget) return;
        const b = e.currentTarget.getBoundingClientRect();
        if (e.clientX < b.left || e.clientX > b.right || e.clientY < b.top || e.clientY > b.bottom) ref.current?.close();
      }}
    >
      <div className="panel-toolbar">
        <div>
          <h2 id="historico-dialog-title">Histórico de conversa</h2>
          <small>
            {lead.name || 'Sem nome informado'} · {lead.contact}
          </small>
        </div>
        <button type="button" className="secondary" onClick={() => ref.current?.close()}>
          Fechar
        </button>
      </div>
      <div className="lead-dialog-content">
        {erro && (
          <p role="alert" className="error">
            {erro}
          </p>
        )}
        {!erro && mensagens === null && <p style={{ fontSize: 13 }}>Carregando…</p>}
        {mensagens && !mensagens.length && <div className="empty">Nenhuma mensagem registrada para este lead (a coleta só vale para conversas feitas depois que foi ligada).</div>}
        {mensagens && mensagens.length > 0 && (
          <div className="conversa-lista">
            {mensagens.map((m, i) => (
              <div key={i} className={`conversa-msg conversa-${m.quem}`}>
                <small>
                  {m.quem === 'cliente' ? 'Cliente' : 'Agente'}
                  {m.audio ? ' (áudio)' : ''} · {new Date(m.quando).toLocaleString('pt-BR')}
                  {m.entregue === false ? ' · não entregue' : ''}
                </small>
                <p>{m.texto}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </dialog>
  );
}
