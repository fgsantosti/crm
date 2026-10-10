import { useLayoutEffect, useRef, type RefObject } from 'react';

// Animação dos cards do Kanban (técnica FLIP): card que muda de coluna ou de posição desliza do lugar antigo
// para o novo, card novo aparece subindo e card que sai (filtro, despacho, fechamento) some com fade.
// Cada card precisa de data-flip-id={lead.id}. "Reduzir movimento" do sistema desliga tudo.

const DURACAO_MOVER = 340;
const DURACAO_ENTRAR = 280;
const DURACAO_SAIR = 200;
const MAX_FANTASMAS = 24;
const reduzir = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

type Foto = { rect: DOMRect; no: HTMLElement };

export function useFlipKanban(ref: RefObject<HTMLElement | null>) {
  const antes = useRef<Map<string, Foto>>(new Map());
  const iniciou = useRef(false);

  const fotografar = (raiz: HTMLElement) => {
    const mapa = new Map<string, Foto>();
    raiz.querySelectorAll<HTMLElement>('[data-flip-id]').forEach((no) => mapa.set(no.dataset.flipId!, { rect: no.getBoundingClientRect(), no }));
    return mapa;
  };

  // Rolagem e redimensionamento mudam as posições sem re-render: a foto "de antes" é refeita para não gerar animação falsa.
  useLayoutEffect(() => {
    let quadro = 0;
    const refazer = () => {
      cancelAnimationFrame(quadro);
      quadro = requestAnimationFrame(() => {
        if (ref.current) antes.current = fotografar(ref.current);
      });
    };
    window.addEventListener('scroll', refazer, true);
    window.addEventListener('resize', refazer);
    return () => {
      cancelAnimationFrame(quadro);
      window.removeEventListener('scroll', refazer, true);
      window.removeEventListener('resize', refazer);
    };
  }, [ref]);

  // Sem lista de dependências de propósito: roda a cada render do Kanban e compara com a foto anterior.
  useLayoutEffect(() => {
    const raiz = ref.current;
    if (!raiz) return;
    const agora = fotografar(raiz);
    if (!reduzir()) {
      let indice = 0;
      agora.forEach(({ rect, no }, id) => {
        const velho = antes.current.get(id);
        if (velho) {
          const dx = velho.rect.left - rect.left;
          const dy = velho.rect.top - rect.top;
          if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
            no.animate([{ transform: `translate(${dx}px, ${dy}px)`, zIndex: 5 }, { transform: 'none', zIndex: 5 }], { duration: DURACAO_MOVER, easing: 'cubic-bezier(.2,.8,.2,1)' });
          }
        } else if (iniciou.current || indice < 40) {
          no.animate([{ opacity: 0, transform: 'translateY(10px) scale(.98)' }, { opacity: 1, transform: 'none' }], {
            duration: DURACAO_ENTRAR,
            delay: iniciou.current ? 0 : Math.min(indice, 12) * 25,
            easing: 'cubic-bezier(.2,.8,.2,1)',
            fill: 'backwards',
          });
          indice += 1;
        }
      });
      // Cards que saíram da tela: um fantasma no lugar antigo some com fade.
      if (iniciou.current) {
        let fantasmas = 0;
        antes.current.forEach(({ rect, no }, id) => {
          if (agora.has(id) || fantasmas >= MAX_FANTASMAS) return;
          if (rect.bottom < 0 || rect.top > window.innerHeight || rect.right < 0 || rect.left > window.innerWidth) return;
          const copia = no.cloneNode(true) as HTMLElement;
          Object.assign(copia.style, { position: 'fixed', left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`, height: `${rect.height}px`, margin: '0', pointerEvents: 'none', zIndex: '60' });
          copia.removeAttribute('data-flip-id');
          copia.setAttribute('aria-hidden', 'true');
          copia.setAttribute('inert', '');
          document.body.appendChild(copia);
          const anim = copia.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'scale(.96)' }], { duration: DURACAO_SAIR, easing: 'ease-in', fill: 'forwards' });
          anim.onfinish = () => copia.remove();
          fantasmas += 1;
        });
      }
    }
    if (agora.size) iniciou.current = true;
    antes.current = agora;
  });
}
