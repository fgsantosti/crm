import { useLayoutEffect, useRef, type ReactNode, type RefObject } from 'react';

// Saída suave dos popups. A entrada já anima (style.css); aqui o fechamento ganha ~170 ms de fade/descida.
// Dois caminhos, porque os popups fecham de dois jeitos:
//  1. dialog.close() / Esc: close() é adiado até a animação acabar (instalarSaidaDosPopups, chamado uma vez em main.tsx);
//  2. o pai desmonta o popup de uma vez (setState null): um "fantasma" (clone do nó) faz a animação sozinho.
// Respeita "reduzir movimento" do sistema: sem animação, tudo fecha na hora.

const DURACAO_MS = 170;
const ABERTURA_MINIMA_MS = 300; // evita fantasma/atraso no abre-e-fecha do StrictMode (dev) e em cliques duplos

const reduzirMovimento = () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const aberturaDe = (no: HTMLElement) => Number(no.dataset.abertoEm || 0);
const abertoHaPouco = (no: HTMLElement) => performance.now() - aberturaDe(no) < ABERTURA_MINIMA_MS;

let instalado = false;
export function instalarSaidaDosPopups() {
  if (instalado || typeof HTMLDialogElement === 'undefined') return;
  instalado = true;
  const abrir = HTMLDialogElement.prototype.showModal;
  const fechar = HTMLDialogElement.prototype.close;
  HTMLDialogElement.prototype.showModal = function () {
    this.dataset.abertoEm = String(performance.now());
    return abrir.call(this);
  };
  HTMLDialogElement.prototype.close = function (valor?: string) {
    if (!this.open || !this.isConnected || this.dataset.saindo || reduzirMovimento() || abertoHaPouco(this)) return fechar.call(this, valor);
    this.dataset.saindo = '1';
    window.setTimeout(() => {
      delete this.dataset.saindo;
      fechar.call(this, valor);
    }, DURACAO_MS);
  };
  // Esc: o navegador fecharia na hora; fecha pelo close() animado (o React ainda recebe o evento e pode desmontar).
  document.addEventListener(
    'cancel',
    (e) => {
      const alvo = e.target;
      if (alvo instanceof HTMLDialogElement && !reduzirMovimento() && !abertoHaPouco(alvo)) {
        e.preventDefault();
        alvo.close();
      }
    },
    true,
  );
}

/** Clone do popup que ainda está na tela, animado só na saída (o original já está sendo desmontado). */
function fantasma(no: HTMLElement | null) {
  if (!no || !no.isConnected || reduzirMovimento() || abertoHaPouco(no)) return;
  if (no instanceof HTMLDialogElement && !no.open) return;
  const copia = no.cloneNode(true) as HTMLElement;
  copia.dataset.saindo = '1';
  copia.setAttribute('inert', '');
  copia.setAttribute('aria-hidden', 'true');
  copia.style.pointerEvents = 'none';
  if (copia instanceof HTMLDialogElement) {
    copia.removeAttribute('open');
    document.body.appendChild(copia);
    copia.showModal();
  } else {
    document.body.appendChild(copia);
  }
  window.setTimeout(() => copia.remove(), DURACAO_MS + 40);
}

/** Para popups que já têm ref no nó raiz (<dialog>): anima a saída quando o pai desmonta com o popup ainda aberto. */
export function useSaidaDoPopup(ref: RefObject<HTMLElement | null>) {
  useLayoutEffect(() => {
    const no = ref.current;
    if (no && !no.dataset.abertoEm) no.dataset.abertoEm = String(performance.now());
    return () => fantasma(no);
  }, [ref]);
}

/** Para overlays em <div>: envolve o popup e anima a saída quando ele é desmontado. */
export function SaidaAnimada({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useSaidaDoPopup(ref);
  return (
    <div ref={ref} style={{ display: 'contents' }}>
      {children}
    </div>
  );
}
