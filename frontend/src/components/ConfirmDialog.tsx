import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { useSaidaDoPopup } from '../popupSaida';

export type TomConfirmacao = 'neutro' | 'atencao' | 'perigo';
export type IconeConfirmacao = 'sair' | 'lixeira' | 'chave' | 'pessoa' | 'aviso' | 'email';

export type OpcoesConfirmacao = {
  titulo: string;
  mensagem?: ReactNode;
  /** Quem/o que será afetado (pessoa, chave, lead...), em um quadro sob a mensagem. */
  detalhe?: ReactNode;
  /** neutro (laranja), atencao (âmbar) ou perigo (vermelho; o foco inicial vai para Cancelar). */
  tom?: TomConfirmacao;
  icone?: IconeConfirmacao;
  confirmar?: string;
  cancelar?: string;
};

const ICONES: Record<IconeConfirmacao, ReactNode> = {
  sair: (
    <>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="M16 17l5-5-5-5" />
      <path d="M21 12H9" />
    </>
  ),
  lixeira: (
    <>
      <path d="M3 6h18" />
      <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
    </>
  ),
  chave: (
    <>
      <circle cx="7.5" cy="15.5" r="4.5" />
      <path d="M10.7 12.3L21 2" />
      <path d="M17 6l3 3" />
      <path d="M14 9l2 2" />
    </>
  ),
  pessoa: (
    <>
      <path d="M12 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8z" />
      <path d="M4 21a8 8 0 0 1 16 0" />
      <path d="M19 8v6" />
      <path d="M16 11h6" />
    </>
  ),
  aviso: (
    <>
      <path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
    </>
  ),
  email: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 7l9 6 9-6" />
    </>
  ),
};

type Pendente = { opcoes: OpcoesConfirmacao; resolver: (ok: boolean) => void };
type Confirmar = (opcoes: OpcoesConfirmacao) => Promise<boolean>;

const ConfirmContext = createContext<Confirmar | null>(null);

/** Troca o confirm() do navegador por um popup no padrão visual do Conecta: `if (!(await confirmar({...}))) return;` */
export function useConfirmar(): Confirmar {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error('useConfirmar precisa estar dentro de <ConfirmProvider>.');
  return ctx;
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pendente, setPendente] = useState<Pendente | null>(null);
  const pendenteRef = useRef<Pendente | null>(null);

  const confirmar = useCallback<Confirmar>((opcoes) => {
    return new Promise<boolean>((resolver) => {
      // Uma confirmação nova cancela a que ainda estiver aberta.
      pendenteRef.current?.resolver(false);
      const nova = { opcoes, resolver };
      pendenteRef.current = nova;
      setPendente(nova);
    });
  }, []);

  function responder(ok: boolean) {
    const atual = pendenteRef.current;
    if (!atual) return;
    pendenteRef.current = null;
    setPendente(null);
    atual.resolver(ok);
  }

  return (
    <ConfirmContext.Provider value={confirmar}>
      {children}
      {pendente && <ConfirmDialog key={pendente.opcoes.titulo + pendente.opcoes.confirmar} opcoes={pendente.opcoes} onResponder={responder} />}
    </ConfirmContext.Provider>
  );
}

function ConfirmDialog({ opcoes, onResponder }: { opcoes: OpcoesConfirmacao; onResponder: (ok: boolean) => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useSaidaDoPopup(ref);
  const cancelarRef = useRef<HTMLButtonElement>(null);
  const confirmarRef = useRef<HTMLButtonElement>(null);
  const tom = opcoes.tom ?? 'neutro';
  const icone = opcoes.icone ?? (tom === 'perigo' ? 'lixeira' : tom === 'atencao' ? 'aviso' : 'pessoa');

  useEffect(() => {
    const dialog = ref.current!;
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.showModal();
    // Ação destrutiva ou delicada: o foco inicial fica em Cancelar (Enter não confirma sem querer).
    (tom === 'neutro' ? confirmarRef : cancelarRef).current?.focus();
    return () => {
      dialog.close();
      document.body.style.overflow = previousOverflow;
      if (previousFocus?.isConnected) previousFocus.focus();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <dialog
      ref={ref}
      className="confirm-dialog"
      data-tom={tom}
      role="alertdialog"
      aria-labelledby="confirm-titulo"
      aria-describedby={opcoes.mensagem ? 'confirm-corpo' : undefined}
      onCancel={(e) => {
        // Esc: cancela por aqui (o React também recebe o fechamento nativo logo depois).
        e.preventDefault();
        onResponder(false);
      }}
      onClick={(e) => {
        if (e.target !== e.currentTarget) return;
        const b = e.currentTarget.getBoundingClientRect();
        if (e.clientX < b.left || e.clientX > b.right || e.clientY < b.top || e.clientY > b.bottom) onResponder(false);
      }}
    >
      <div className="confirm-faixa">
        <div className="confirm-icone">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {ICONES[icone]}
          </svg>
        </div>
      </div>
      <div className="confirm-corpo">
        <h2 id="confirm-titulo">{opcoes.titulo}</h2>
        {opcoes.mensagem && (
          <p id="confirm-corpo" className="confirm-mensagem">
            {opcoes.mensagem}
          </p>
        )}
        {opcoes.detalhe && <div className="confirm-detalhe">{opcoes.detalhe}</div>}
        <div className="confirm-acoes">
          <span className="confirm-dica">
            <kbd>Esc</kbd> cancela
          </span>
          <div className="confirm-botoes">
            <button ref={cancelarRef} type="button" className="secondary" onClick={() => onResponder(false)}>
              {opcoes.cancelar ?? 'Cancelar'}
            </button>
            <button ref={confirmarRef} type="button" className="confirm-ok" onClick={() => onResponder(true)}>
              {opcoes.confirmar ?? 'Confirmar'}
            </button>
          </div>
        </div>
      </div>
    </dialog>
  );
}

/** Quadro de detalhe com uma pessoa (ou lead): iniciais, nome, linha de apoio e um selo opcional. */
export function ConfirmPessoa({ nome, sub, selo, chips }: { nome: string; sub?: string; selo?: string; chips?: string[] }) {
  const iniciais = (nome || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join('').toUpperCase() || '?';
  return (
    <div className="confirm-pessoa">
      <div className="confirm-avatar" aria-hidden="true">
        {iniciais}
      </div>
      <div className="confirm-pessoa-texto">
        <strong>{nome}</strong>
        {sub && <small>{sub}</small>}
      </div>
      {selo && <span className="confirm-selo">{selo}</span>}
      {chips?.map((c) => (
        <span key={c} className="confirm-chip">
          {c}
        </span>
      ))}
    </div>
  );
}

/** Confirmação padrão de "Sair da conta" (barras laterais e popup de perfil). */
export function confirmarSaida(confirmar: Confirmar, me: { display_name: string; username: string; email: string }): Promise<boolean> {
  return confirmar({
    titulo: 'Sair da conta?',
    mensagem: 'Você será desconectado e precisará entrar de novo com seu e-mail e senha.',
    detalhe: <ConfirmPessoa nome={me.display_name || me.username} sub={me.email || me.username} />,
    icone: 'sair',
    confirmar: 'Sair da conta',
  });
}
