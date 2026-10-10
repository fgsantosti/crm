import { useEffect, useState } from 'react';
import { fetchTodasAsPaginas, type Api } from '../api';
import type { Area } from '../types';

/** Área do lead no Despacho: só as áreas cadastradas pela empresa (nunca texto livre). */
export function AreaSelect({ api, companyId, value, onChange }: { api: Api; companyId: number; value: string; onChange: (v: string) => void }) {
  const [areas, setAreas] = useState<Area[]>([]);

  useEffect(() => {
    let active = true;
    fetchTodasAsPaginas<Area>(api, `/areas/?company=${companyId}`)
      .then((todas) => active && setAreas(todas.filter((a) => !a.fixa))) // despacho humano não usa "Fora de escopo"
      .catch(() => undefined);
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  const conhecida = areas.some((a) => a.name === value);

  return (
    <label style={{ margin: 0 }}>
      Área do atendimento
      <select value={conhecida ? value : ''} onChange={(e) => onChange(e.target.value)}>
        <option value="">{value && !conhecida ? `Manter atual (${value})` : 'Manter sem alteração'}</option>
        {areas.map((a) => (
          <option key={a.id} value={a.name}>
            {a.name}
          </option>
        ))}
      </select>
    </label>
  );
}
