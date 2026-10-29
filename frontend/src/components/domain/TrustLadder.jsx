import { Badge } from "../ui/Badge";

export function TrustLadder({ rungs, onJump }) {
  return (
    <ol className="grid gap-2 sm:grid-cols-4">
      {rungs.map((rung) => (
        <li key={rung.id}>
          <button
            type="button"
            onClick={() => onJump(rung.id)}
            className="h-auto w-full rounded-md border border-border bg-surface px-3 py-3 text-left shadow-card hover:bg-ice/40"
          >
            <span className="block text-meta text-ink-secondary">{rung.label}</span>
            <span className="mt-1 block">
              <Badge tone={rung.tone}>{rung.state}</Badge>
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}
