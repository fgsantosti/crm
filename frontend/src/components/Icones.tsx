/** Logo do WhatsApp, sem fundo (aparece ao lado dos botões "Conversar"). */
export function IconeWhatsapp({ size = 34 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden="true" style={{ flex: 'none', display: 'block' }}>
      <path
        d="M32 4C47 4 60 16 60 31C60 46 47 58 32 58C27.2 58 22.7 56.8 18.7 54.7L5 59L9.6 46C6.4 41.8 4 36.7 4 31C4 16 17 4 32 4Z"
        fill="#254A40"
        stroke="#3FAE4F"
        strokeWidth="3"
        strokeLinejoin="round"
      />
      <circle cx="32" cy="31" r="21" fill="#5DB865" />
      <path
        transform="translate(20.5 19.5) scale(0.96)"
        fill="#fff"
        d="M6.62 10.79c1.44 2.83 3.76 5.14 6.59 6.59l2.2-2.2c.27-.27.67-.36 1.02-.24 1.12.37 2.33.57 3.57.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1-9.39 0-17-7.61-17-17 0-.55.45-1 1-1h3.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.25 1.02l-2.2 2.2z"
      />
    </svg>
  );
}
