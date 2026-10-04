import { useEffect, useRef, useState } from 'react';
import type { Api } from '../api';
import type { Question } from '../types';

/** Gravação própria de uma pergunta do roteiro: substitui o TTS automático em "Mensagens via áudio". */
export function AudioDaPergunta({ api, companyId, question, canEdit, onChange }: {
  api: Api;
  companyId: number;
  question: Question;
  canEdit: boolean;
  onChange: (q: Question) => void;
}) {
  const [gravando, setGravando] = useState(false);
  const [busy, setBusy] = useState(false);
  const [erro, setErro] = useState('');
  const [versao, setVersao] = useState(0);
  const recorder = useRef<MediaRecorder | null>(null);
  const partes = useRef<Blob[]>([]);
  const arquivoRef = useRef<HTMLInputElement>(null);
  const url = `/questions/${question.id}/audio/?company=${companyId}`;
  const temPlaceholder = /\{\w+\}/.test(question.text || '');

  useEffect(() => () => recorder.current?.stream.getTracks().forEach((t) => t.stop()), []);

  async function enviar(blob: Blob, nome: string) {
    setBusy(true);
    setErro('');
    try {
      const form = new FormData();
      form.append('arquivo', blob, nome);
      onChange(await api(url, { method: 'POST', body: form }));
      setVersao(Date.now());
    } catch (err) {
      setErro((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function iniciarGravacao() {
    setErro('');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      partes.current = [];
      rec.ondataavailable = (e) => e.data.size && partes.current.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(partes.current, { type: rec.mimeType || 'audio/webm' });
        enviar(blob, 'gravacao.webm');
      };
      rec.start();
      recorder.current = rec;
      setGravando(true);
    } catch {
      setErro('Não foi possível acessar o microfone.');
    }
  }

  function pararGravacao() {
    recorder.current?.stop();
    recorder.current = null;
    setGravando(false);
  }

  async function remover() {
    setBusy(true);
    setErro('');
    try {
      onChange(await api(url, { method: 'DELETE' }));
    } catch (err) {
      setErro((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const src = question.audio_gravado ? `${question.audio_gravado}${versao ? `?v=${versao}` : ''}` : '';

  return (
    <div className="audio-pergunta" style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 10 }}>
      <span style={{ fontSize: 13, fontWeight: 600 }}>Gravação (substitui a voz automática)</span>
      {src ? (
        <audio controls src={src} style={{ maxWidth: '100%' }} data-testid={`audio-${question.question_id}`} />
      ) : (
        <small style={{ color: 'var(--muted)' }}>Sem gravação: o áudio é gerado automaticamente a partir do texto.</small>
      )}
      {canEdit && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {gravando ? (
            <button type="button" onClick={pararGravacao}>Parar gravação</button>
          ) : (
            <button type="button" className="secondary" disabled={busy} onClick={iniciarGravacao}>Gravar</button>
          )}
          <button type="button" className="secondary" disabled={busy || gravando} onClick={() => arquivoRef.current?.click()}>
            Enviar arquivo
          </button>
          {question.audio_gravado && (
            <button type="button" className="secondary" disabled={busy || gravando} onClick={remover}>Remover</button>
          )}
          <input
            ref={arquivoRef}
            type="file"
            accept="audio/*"
            hidden
            data-testid={`upload-${question.question_id}`}
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = '';
              if (f) enviar(f, f.name);
            }}
          />
        </div>
      )}
      {busy && <small style={{ color: 'var(--muted)' }}>Processando áudio…</small>}
      {temPlaceholder && (
        <small style={{ color: 'var(--warn)' }}>A gravação não inclui dados variáveis como {'{nome}'}.</small>
      )}
      {erro && <small style={{ color: 'var(--danger, #c0392b)' }}>{erro}</small>}
    </div>
  );
}
