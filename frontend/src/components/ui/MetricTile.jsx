export function MetricTile({ label, value, hint }) {
  return (
    <section className="rounded-md border border-border bg-surface p-4 shadow-card">
      <p className="text-meta font-medium text-ink-secondary">{label}</p>
      <p className="mt-2 text-metric font-semibold tracking-tight text-ink">{value}</p>
      {hint ? <p className="mt-1 text-meta text-ink-muted">{hint}</p> : null}
    </section>
  );
}
