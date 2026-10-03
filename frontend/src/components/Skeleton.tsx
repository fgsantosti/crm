export function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

export function SkeletonTiles({ count = 4 }: { count?: number }) {
  return (
    <div className="tiles">
      {Array.from({ length: count }).map((_, i) => (
        <article key={i} className="tile skeleton-tile">
          <div className="skeleton skeleton-line" style={{ width: '60%', height: 11 }} />
          <div className="skeleton skeleton-line" style={{ width: '40%', height: 30, marginTop: 14 }} />
        </article>
      ))}
    </div>
  );
}

export function SkeletonRows({ rows = 4, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, r) => (
        <tr key={r}>
          {Array.from({ length: cols }).map((_, c) => (
            <td key={c}>
              <div className="skeleton skeleton-line" style={{ width: c === 0 ? '70%' : '50%' }} />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

export function SkeletonCards({ count = 3, height = 90 }: { count?: number; height?: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height, borderRadius: 14 }} />
      ))}
    </>
  );
}
