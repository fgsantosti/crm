export function Logo({ size = 38 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 44 44" fill="none" aria-hidden="true" style={{ flex: 'none' }}>
      <rect x="2" y="3" width="40" height="30" rx="11" fill="#D9531A" />
      <path d="M11 33 L11 41 L20 33 Z" fill="#D9531A" />
      <circle cx="22" cy="18" r="9" fill="none" stroke="#241A12" strokeWidth="5" strokeDasharray="40 17" strokeLinecap="round" />
    </svg>
  );
}
