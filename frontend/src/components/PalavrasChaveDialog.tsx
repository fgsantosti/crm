import { useEffect, useRef, useState } from 'react';
import { useSaidaDoPopup } from '../popupSaida';

/** "a, b ,, c" -> ['a', 'b', 'c'] (sem repetir, ignorando maiúsculas). */
export function listaDePalavras(texto: string): string[] {
  const vistas = new Set<string>();
  return (texto || '')
    .split(/[,;\n]/)
    .map((p) => p.trim())
    .filter((p) => {
      const k = p.toLowerCase();
      if (!p || vistas.has(k)) return false;
      vistas.add(k);
      return true;
    });
}

const LIMITE = 500; // Area.palavras_chave

/**
 * Popup "Palavras Chave da Spin" (Opções do agente → Etapa Inicial): palavras que, vistas na primeira
 * mensagem do cliente, levam o atendimento até esta SPIN (somadas à análise do agente).
 */
export function PalavrasChaveDialog({ area, valor, somenteLeitura, salvando, multiplasSpins, onSalvar, onClose }: {
  area: string;
  valor: string;
  somenteLeitura?: boolean;
  salvando?: boolean;
  /** Com uma única SPIN habilitada as palavras não são usadas: o popup avisa. */
  multiplasSpins: boolean;
  onSalvar: (palavras: string) => Promise<boolean>;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useSaidaDoPopup(ref);
  const [palavras, setPalavras] = useState<string[]>(listaDePalavras(valor));
  const [rascunho, setRascunho] = useState('');
  const [erro, setErro] = useState('');

  useEffect(() => {
    const dialog = ref.current!;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.showModal();
    return () => {
      dialog.close();
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  function adicionar(texto: string) {
    const novas = listaDePalavras(texto);
    if (!novas.length) return;
    const juntas = listaDePalavras([...palavras, ...novas].join(','));
    if (juntas.join(', ').length > LIMITE) {
      setErro(`Limite de ${LIMITE} caracteres no total.`);
      return;
    }
    setErro('');
    setPalavras(juntas);
    setRascunho('');
  }

  async function salvar() {
    const pendente = listaDePalavras(rascunho);
    const finais = pendente.length ? listaDePalavras([...palavras, ...pendente].join(',')) : palavras;
    if (finais.join(', ').length > LIMITE) {
      setErro(`Limite de ${LIMITE} caracteres no total.`);
      return;
    }
    if (await onSalvar(finais.join(', '))) ref.current?.close();
  }

  return (
    <dialog
      ref={ref}
      className="lead-dialog"
      aria-labelledby="palavras-titulo"
      onClose={() => {
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
          <h2 id="palavras-titulo">Palavras Chave da Spin</h2>
          <small>{area}</small>
        </div>
        <button type="button" className="secondary" onClick={() => ref.current?.close()} aria-label="Fechar">
          Fechar
        </button>
      </div>
      <div className="lead-dialog-content" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <p style={{ margin: 0, fontSize: 13.5, color: 'var(--muted)' }}>
          Quando a primeira mensagem do cliente tiver uma destas palavras, o atendimento segue para esta SPIN. Elas se somam à análise do agente.
          {!multiplasSpins && ' Hoje só há uma SPIN habilitada, então as palavras passam a valer quando você habilitar outra.'}
        </p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {palavras.map((p) => (
            <span key={p} className="chip chip-neutral" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              {p}
              {!somenteLeitura && (
                <button
                  type="button"
                  aria-label={`Remover ${p}`}
                  onClick={() => setPalavras((v) => v.filter((x) => x !== p))}
                  style={{ all: 'unset', cursor: 'pointer', lineHeight: 1, fontSize: 15 }}
                >
                  ×
                </button>
              )}
            </span>
          ))}
          {!palavras.length && <small style={{ color: 'var(--muted)' }}>Nenhuma palavra-chave ainda.</small>}
        </div>
        {!somenteLeitura && (
          <label style={{ margin: 0 }}>
            Adicionar palavra ou expressão
            <input
              value={rascunho}
              placeholder="Ex.: desconto no benefício, INSS, consignado"
              onChange={(e) => setRascunho(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ',') {
                  e.preventDefault();
                  adicionar(rascunho);
                }
              }}
              onBlur={() => adicionar(rascunho)}
            />
            <small style={{ color: 'var(--muted)' }}>Enter ou vírgula para adicionar.</small>
          </label>
        )}
        {erro && (
          <p role="alert" className="error" style={{ margin: 0 }}>
            {erro}
          </p>
        )}
      </div>
      {!somenteLeitura && (
        <div className="lead-dialog-footer">
          <button type="button" className="secondary" onClick={() => ref.current?.close()}>
            Cancelar
          </button>
          <button type="button" onClick={salvar} disabled={salvando}>
            Salvar
          </button>
        </div>
      )}
    </dialog>
  );
}
