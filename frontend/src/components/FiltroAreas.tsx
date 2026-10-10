import { useEffect, useRef, useState } from 'react';

export const SEM_AREA = '__sem_area__';

/** Dropdown com checkbox por área: vazio = todas. Inclui "Sem área" para leads ainda sem classificação. */
export function FiltroAreas({ areas, selecionadas, onChange }: { areas: string[]; selecionadas: string[]; onChange: (v: string[]) => void }) {
  const [aberto, setAberto] = useState(false);
  const raiz = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!aberto) return;
    const fora = (e: MouseEvent) => {
      if (raiz.current && !raiz.current.contains(e.target as Node)) setAberto(false);
    };
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setAberto(false);
    document.addEventListener('mousedown', fora);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', fora);
      document.removeEventListener('keydown', esc);
    };
  }, [aberto]);

  const opcoes = [...areas.map((a) => ({ valor: a, rotulo: a })), { valor: SEM_AREA, rotulo: 'Sem área' }];
  const alterna = (v: string) => onChange(selecionadas.includes(v) ? selecionadas.filter((x) => x !== v) : [...selecionadas, v]);
  const rotulo = !selecionadas.length ? 'Todas as áreas' : selecionadas.length === 1 ? (opcoes.find((o) => o.valor === selecionadas[0])?.rotulo ?? '1 área') : `${selecionadas.length} áreas`;

  return (
    <div className="filtro-areas" ref={raiz}>
      <button type="button" className="filtro-areas-botao" aria-haspopup="true" aria-expanded={aberto} onClick={() => setAberto((v) => !v)}>
        {rotulo}
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M4 6l4 4 4-4" stroke="#6E5F4F" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {aberto && (
        <div className="filtro-areas-menu" role="group" aria-label="Filtrar por área">
          {opcoes.map((o) => (
            <label key={o.valor}>
              <input type="checkbox" checked={selecionadas.includes(o.valor)} onChange={() => alterna(o.valor)} />
              {o.rotulo}
            </label>
          ))}
          {selecionadas.length > 0 && (
            <button type="button" className="filtro-areas-limpar" onClick={() => onChange([])}>
              Limpar seleção
            </button>
          )}
        </div>
      )}
    </div>
  );
}
