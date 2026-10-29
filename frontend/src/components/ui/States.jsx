import { Button } from "./Button";

export function EmptyState({ children, action, onAction }) {
  return (
    <div className="rounded-md border border-border bg-surface px-6 py-8 shadow-card">
      <p className="text-body text-ink">{children}</p>
      {action ? (
        <div className="mt-4">
          <Button variant="secondary" onClick={onAction}>
            {action}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

export function ErrorState({ message, requestId, onRetry }) {
  return (
    <div className="rounded-md border border-danger/30 bg-danger-subtle px-6 py-6" role="alert">
      <p className="text-body text-ink">{message}</p>
      {requestId ? <p className="mt-1 font-mono text-meta text-ink-secondary">Reference {requestId}</p> : null}
      {onRetry ? (
        <div className="mt-4">
          <Button variant="secondary" onClick={onRetry}>
            Retry
          </Button>
        </div>
      ) : null}
    </div>
  );
}
