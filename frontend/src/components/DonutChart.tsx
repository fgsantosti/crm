type Segment = { label: string; value: number; color: string };

export function DonutChart({ segments, size = 220, thickness = 28 }: { segments: Segment[]; size?: number; thickness?: number }) {
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  const r = (size - thickness) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;
  const gap = segments.length > 1 ? 3 : 0;
  const usable = Math.max(0, circumference - gap * segments.length);
  let acc = 0;
  const arcs = segments.map((s) => {
    const len = total > 0 ? (s.value / total) * usable : 0;
    const offset = -acc;
    acc += len + gap;
    return { ...s, len, offset };
  });

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={`Total ${total}: ${segments.map((s) => `${s.label} ${s.value}`).join(', ')}`}
    >
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="#F4EDE2" strokeWidth={thickness} />
      {arcs.map((a) => (
        <circle
          key={a.label}
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke={a.color}
          strokeWidth={thickness}
          strokeDasharray={`${a.len} ${circumference - a.len}`}
          strokeDashoffset={a.offset}
          transform={`rotate(-90 ${cx} ${cy})`}
        />
      ))}
      <text x={cx} y={cy - 6} textAnchor="middle" fontFamily="'DM Mono', monospace" fontSize={size * 0.136} fontWeight={500} fill="#241A12">
        {total}
      </text>
      <text x={cx} y={cy + 18} textAnchor="middle" fontFamily="'DM Sans', sans-serif" fontSize={12.5} fill="#8A7A68">
        atendimentos
      </text>
    </svg>
  );
}
