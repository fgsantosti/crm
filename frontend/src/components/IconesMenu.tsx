import type { ReactNode } from 'react';

// Ícones de traço da navegação (cor = texto do item, respeita a identidade visual da empresa).
const ICONES: Record<string, ReactNode> = {
  dashboard: <><rect x="2" y="2" width="5" height="6" rx="1.5" /><rect x="9" y="2" width="5" height="4" rx="1.5" /><rect x="2" y="10" width="5" height="4" rx="1.5" /><rect x="9" y="8" width="5" height="6" rx="1.5" /></>,
  leads: <><rect x="2" y="2.5" width="3.2" height="11" rx="1" /><rect x="6.4" y="2.5" width="3.2" height="7" rx="1" /><rect x="10.8" y="2.5" width="3.2" height="9" rx="1" /></>,
  especiais: <><circle cx="8" cy="8" r="6" /><path d="M8 5v3l2 1.5" strokeLinecap="round" /></>,
  pendencias: <><path d="M8 2.5l5.5 10h-11z" strokeLinejoin="round" /><path d="M8 6.5v2.5" strokeLinecap="round" /></>,
  humano: <><circle cx="8" cy="5.5" r="2.5" /><path d="M3 13.5c.8-2.4 2.7-3.6 5-3.6s4.2 1.2 5 3.6" strokeLinecap="round" /></>,
  blacklist: <><circle cx="8" cy="8" r="6" /><path d="M4 12L12 4" /></>,
  roteiro: <path d="M3 3h10M3 8h10M3 13h6" strokeLinecap="round" />,
  'dados-empresa': <><rect x="3" y="2" width="10" height="12" rx="2" /><path d="M6 6h4M6 9h4" strokeLinecap="round" /></>,
  equipe: <><circle cx="6" cy="6" r="2.5" /><path d="M1.5 13c.6-2.3 2.4-3.5 4.5-3.5s3.9 1.2 4.5 3.5" strokeLinecap="round" /><circle cx="11.5" cy="5.5" r="2" /></>,
  painel: <><rect x="2" y="3" width="12" height="10" rx="2" /><path d="M5 7l2 2-2 2M9 11h2" strokeLinecap="round" strokeLinejoin="round" /></>,
  gestores: <><circle cx="8" cy="5.5" r="2.5" /><path d="M3 13.5c.8-2.4 2.7-3.6 5-3.6s4.2 1.2 5 3.6" strokeLinecap="round" /></>,
  faturamento: <><circle cx="8" cy="8" r="6" /><path d="M8 4.5v7M10 6.2c-.5-.6-1.2-.9-2-.9-1.1 0-2 .6-2 1.5s.9 1.3 2 1.5 2 .6 2 1.5-.9 1.5-2 1.5c-.8 0-1.5-.3-2-.9" strokeLinecap="round" /></>,
  notificacoes: <><path d="M4 11V7a4 4 0 018 0v4l1 1.5H3z" strokeLinejoin="round" /><path d="M6.5 14a1.7 1.7 0 003 0" strokeLinecap="round" /></>,
  cobrancas: <><path d="M2.5 8.5V3.5h5l6 6-5 5z" strokeLinejoin="round" /><circle cx="5.5" cy="6.5" r=".9" fill="currentColor" stroke="none" /></>,
  identidade: <><circle cx="8" cy="8" r="6" /><circle cx="6" cy="6.5" r=".6" /><circle cx="10" cy="6.5" r=".6" /><circle cx="8" cy="10.5" r=".6" /></>,
};


export function IconeMenu({ nome }: { nome: string }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      {ICONES[nome]}
    </svg>
  );
}
