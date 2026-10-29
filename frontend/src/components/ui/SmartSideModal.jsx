import { useEffect, useId, useRef, useState } from "react";
import { X as XIcon } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "./Badge";
import { Button } from "./Button";
import { statusLabel, statusTone } from "../../lib/format";

const MOTION_MS = 200;
const MOTION = `${MOTION_MS}ms ease-in-out`;

function bundleText(bundle) {
  try {
    return JSON.stringify(bundle || {}, null, 2);
  } catch {
    return "";
  }
}

export function SmartSideModal({ open, escalation, refreshing = false, onClose, onRefresh, onDownload }) {
  const titleId = useId();
  const [mounted, setMounted] = useState(false);
  const [shown, setShown] = useState(false);
  const snapshot = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  if (open && escalation) snapshot.current = escalation;

  useEffect(() => {
    if (!open) return undefined;
    function onKey(event) {
      if (event.key === "Escape") onCloseRef.current();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (open) {
      setMounted(true);
      return undefined;
    }
    setShown(false);
    if (!mounted) return undefined;
    const timer = window.setTimeout(() => setMounted(false), MOTION_MS);
    return () => window.clearTimeout(timer);
  }, [open, mounted]);

  useEffect(() => {
    if (!open || !mounted) return undefined;
    let second = 0;
    const first = window.requestAnimationFrame(() => {
      second = window.requestAnimationFrame(() => setShown(true));
    });
    return () => {
      window.cancelAnimationFrame(first);
      window.cancelAnimationFrame(second);
    };
  }, [open, mounted]);

  if (!mounted || !snapshot.current) return null;

  const view = snapshot.current;

  return (
    <div className="fixed inset-0 z-40">
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-ink/40"
        style={{
          opacity: shown ? 1 : 0,
          transition: `opacity ${MOTION}`,
        }}
      />
      <div
        className="absolute inset-y-0 right-0 h-full"
        style={{
          transform: shown ? "translateX(0)" : "translateX(100%)",
          transition: `transform ${MOTION}`,
        }}
      >
        <aside
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          className="flex h-full w-[560px] max-w-full flex-col border-l border-border bg-surface"
        >
          <header className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-border px-4 sm:px-6">
            <h2 id={titleId} className="truncate text-sm font-semibold text-ink">Escalation Details</h2>
            <button
              type="button"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-ink-secondary hover:bg-ice hover:text-ink"
              aria-label="Close"
              onClick={onClose}
            >
              <XIcon className="h-4 w-4" strokeWidth={1.75} />
            </button>
          </header>
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
            <div className="flex h-full min-h-full flex-col">
              <div className="shrink-0 space-y-3 px-4 py-4 text-sm text-ink sm:px-6">
                <p className="font-mono text-xs">{view.test_id}</p>
                <p>
                  {view.provider} · <Badge tone={statusTone(view.status)}>{statusLabel(view.status)}</Badge>
                </p>
                <p>{view.reason}</p>
                {view.external_ref ? <p className="font-mono text-xs text-ink-secondary">{view.external_ref}</p> : null}
                {view.response ? (
                  <pre className="whitespace-pre-wrap font-mono text-xs">{view.response}</pre>
                ) : (
                  <p className="text-ink-secondary">No response yet.</p>
                )}
              </div>
              <div className="flex min-h-0 flex-1 flex-col px-4 pb-4 sm:px-6">
                <h3 className="shrink-0 text-sm font-semibold text-ink">Evidence bundle</h3>
                <pre className="mt-2 min-h-0 flex-1 overflow-auto rounded-md border border-border bg-sunken p-3 font-mono text-xs leading-5 text-ink">
                  {bundleText(view.bundle)}
                </pre>
              </div>
            </div>
          </div>
          <footer className="flex shrink-0 items-center justify-between gap-3 border-t border-border px-4 py-3 sm:px-6">
            <Link to={`/flakes/${view.flake_id}`} className="inline-flex h-10 items-center rounded-md px-3 font-medium text-accent-ink">
              Open flake
            </Link>
            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="secondary" busy={refreshing} onClick={onRefresh}>Refresh status</Button>
              <Button variant="secondary" onClick={onDownload}>Download bundle</Button>
            </div>
          </footer>
        </aside>
      </div>
    </div>
  );
}
