// Identidade visual da empresa (barra lateral): gradiente de duas cores e texto sempre legível.

export type IdentidadeVisual = {
  nome: string;
  logo_url: string | null;
  cor_principal: string | null;
  cor_contraste: string | null;
};

export type PaletaBarra = {
  /** CSS do fundo (gradiente das duas cores). */
  fundo: string;
  /** true quando o texto é claro (fundo escuro). */
  textoClaro: boolean;
  /** Variáveis CSS lidas pela barra lateral (ver style.css). */
  vars: Record<string, string>;
};

const TEXTO_CLARO = '#F3E9DD';
const TEXTO_ESCURO = '#241A12';

function canal(v: number) {
  const c = v / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

/** Luminância relativa (WCAG) de uma cor #RRGGBB, de 0 (preto) a 1 (branco). */
export function luminancia(hex: string): number {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return 0;
  const n = parseInt(m[1], 16);
  return 0.2126 * canal((n >> 16) & 255) + 0.7152 * canal((n >> 8) & 255) + 0.0722 * canal(n & 255);
}

/** Razão de contraste (WCAG) entre duas cores #RRGGBB, de 1 a 21. */
export function contraste(a: string, b: string): number {
  const [claro, escuro] = [luminancia(a), luminancia(b)].sort((x, y) => y - x);
  return (claro + 0.05) / (escuro + 0.05);
}

/** Pior contraste (o menor) do texto contra as duas pontas do gradiente. */
function piorContraste(texto: string, c1: string, c2: string) {
  return Math.min(contraste(texto, c1), contraste(texto, c2));
}

/** Gradiente das duas cores e a paleta de texto/botões da barra, escolhida pelo melhor contraste. */
export function paletaDaIdentidade(principal: string, contrasteCor: string): PaletaBarra {
  const textoClaro = piorContraste(TEXTO_CLARO, principal, contrasteCor) >= piorContraste(TEXTO_ESCURO, principal, contrasteCor);
  const vars = textoClaro
    ? {
        '--sb-fg': TEXTO_CLARO, '--sb-fg-suave': '#E4D6C8', '--sb-mudo': '#D3C3B3',
        '--sb-pilula-bg': 'rgba(255,255,255,.14)', '--sb-pilula-borda': 'rgba(255,255,255,.28)',
        '--sb-ativo-bg': TEXTO_CLARO, '--sb-ativo-fg': TEXTO_ESCURO,
      }
    : {
        '--sb-fg': TEXTO_ESCURO, '--sb-fg-suave': '#3A2B20', '--sb-mudo': '#4F4034',
        '--sb-pilula-bg': 'rgba(36,26,18,.10)', '--sb-pilula-borda': 'rgba(36,26,18,.25)',
        '--sb-ativo-bg': TEXTO_ESCURO, '--sb-ativo-fg': TEXTO_CLARO,
      };
  return { fundo: `linear-gradient(160deg, ${principal} 0%, ${contrasteCor} 100%)`, textoClaro, vars };
}

/** A identidade só vale com as duas cores; sem elas a barra usa o visual padrão Conecta. */
export function paletaDaEmpresa(identidade: IdentidadeVisual | null | undefined): PaletaBarra | null {
  return identidade?.cor_principal && identidade.cor_contraste ? paletaDaIdentidade(identidade.cor_principal, identidade.cor_contraste) : null;
}
