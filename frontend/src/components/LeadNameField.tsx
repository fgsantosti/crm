import { useState } from 'react';
import type { Api } from '../api';
import type { Lead } from '../types';

export function LeadNameField({ lead, api, onUpdated }: { lead: Lead; api: Api; onUpdated: (lead: Lead) => void }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  async function save() {
    setSaving(true);
    setError('');
    try {
      const updated: Lead = await api(`/leads/${lead.id}/?company=${lead.company}`, {
        method: 'PATCH', body: JSON.stringify({ name: name.trim() }),
      });
      onUpdated(updated);
      setEditing(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <label style={{ margin: 0 }}>
        Nome
        <input
          readOnly={!editing} disabled={saving} maxLength={160}
          value={editing ? name : lead.name} placeholder="Sem nome informado"
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        {editing ? <>
          <button type="button" disabled={saving} onClick={save}>{saving ? 'Salvando…' : 'Salvar nome'}</button>
          <button type="button" className="secondary" disabled={saving} onClick={() => { setEditing(false); setError(''); }}>Cancelar</button>
        </> : <button type="button" className="secondary" onClick={() => { setName(lead.name); setEditing(true); setError(''); }}>Editar nome</button>}
      </div>
      {error && <p role="alert" className="error">{error}</p>}
    </div>
  );
}
