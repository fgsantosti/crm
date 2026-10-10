import { useEffect, useRef, useState } from 'react';

const reduzir = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Número que "conta" até o novo valor (~550 ms) em vez de trocar de repente. Sem animação com "reduzir movimento". */
export function NumeroAnimado({ valor, duracao = 550 }: { valor: number; duracao?: number }) {
  const [exibido, setExibido] = useState(reduzir() ? valor : 0);
  const atual = useRef(exibido);

  useEffect(() => {
    if (reduzir() || atual.current === valor) {
      atual.current = valor;
      setExibido(valor);
      return;
    }
    const de = atual.current;
    const inicio = performance.now();
    let quadro = 0;
    const passo = (agora: number) => {
      const t = Math.min(1, (agora - inicio) / duracao);
      const suave = 1 - Math.pow(1 - t, 3); // ease-out
      const v = Math.round(de + (valor - de) * suave);
      atual.current = v;
      setExibido(v);
      if (t < 1) quadro = requestAnimationFrame(passo);
    };
    quadro = requestAnimationFrame(passo);
    return () => cancelAnimationFrame(quadro);
  }, [valor, duracao]);

  return <>{exibido}</>;
}
