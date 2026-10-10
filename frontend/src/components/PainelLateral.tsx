import { useCallback, useState } from 'react';

// Painel lateral recolhível (computador): por padrão é uma coluna só de ícones que expande quando o mouse (ou o foco do teclado)
// entra e recolhe quando sai, sobrepondo o conteúdo sem empurrá-lo. O botão de alfinete fixa o painel aberto, como era antes.
// No celular (<= 900 px) o painel continua sendo a faixa do topo e nada disso se aplica. As regras estão em style.css (.sidebar-slot).

const CHAVE = 'conecta.painel-lateral.fixo';

function lerFixa(): boolean {
  try {
    return window.localStorage.getItem(CHAVE) === '1';
  } catch {
    return false;
  }
}

export function useSidebarFixa(): [boolean, () => void] {
  const [fixa, setFixa] = useState(lerFixa);
  const alternar = useCallback(() => {
    setFixa((v) => {
      try {
        window.localStorage.setItem(CHAVE, v ? '0' : '1');
      } catch {
        /* sem armazenamento: vale só nesta sessão */
      }
      return !v;
    });
  }, []);
  return [fixa, alternar];
}

export function BotaoFixarPainel({ fixa, onAlternar }: { fixa: boolean; onAlternar: () => void }) {
  return (
    <button type="button" className="painel-fixar" aria-pressed={fixa} aria-label={fixa ? 'Soltar painel lateral (recolher ao tirar o mouse)' : 'Fixar painel lateral aberto'} title={fixa ? 'Soltar painel' : 'Fixar painel aberto'} onClick={onAlternar}>
      <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M9.5 2.5l4 4-2 .5-2.5 2.5v2.5l-1 1-2.5-2.5-3.5 3.5M7 6.5l-1-1 1-1 1 1" transform={fixa ? undefined : 'rotate(0 8 8)'} />
      </svg>
    </button>
  );
}
