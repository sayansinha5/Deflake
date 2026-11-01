import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { X as XIcon } from "lucide-react";

import { Button } from "./Button";
import { exactTime, relativeTime } from "../../lib/format";

const MOTION_MS = 200;
const MOTION = `${MOTION_MS}ms ease-in-out`;

export function NotificationsSideModal({
  open,
  items = [],
  unread = 0,
  refreshing = false,
  acceptingId = null,
  onClose,
  onRefresh,
  onMarkRead,
  onAcceptInvite,
  onMarkAllRead,
}) {
  const titleId = useId();
  const [mounted, setMounted] = useState(false);
  const [shown, setShown] = useState(false);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

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

  if (!mounted) return null;

  return (
    <div className="fixed inset-0 z-40">
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-ink/40"
        style={{ opacity: shown ? 1 : 0, transition: `opacity ${MOTION}` }}
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
          className="flex h-full w-[420px] max-w-full flex-col border-l border-border bg-surface"
        >
          <header className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-border px-4 sm:px-6">
            <h2 id={titleId} className="truncate text-sm font-semibold text-ink">
              Notifications{unread ? ` · ${unread}` : ""}
            </h2>
            <div className="flex items-center gap-1">
              <Button variant="secondary" busy={refreshing} onClick={onRefresh}>
                Refresh
              </Button>
              <button
                type="button"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-ink-secondary hover:bg-ice hover:text-ink"
                aria-label="Close"
                onClick={onClose}
              >
                <XIcon className="h-4 w-4" strokeWidth={1.75} />
              </button>
            </div>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3 sm:px-6">
            {items.length === 0 ? (
              <p className="text-sm text-ink-secondary">No notifications yet.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {items.map((item) => (
                  <li
                    key={item.id}
                    className={`rounded-md border border-border px-3 py-3 ${item.read_at ? "bg-surface" : "bg-ice"}`}
                  >
                    <p className="text-sm font-medium text-ink">{item.title}</p>
                    <p className="mt-1 line-clamp-3 text-sm text-ink-secondary">{item.body}</p>
                    <p className="mt-2 text-xs text-ink-muted" title={exactTime(item.created_at)}>
                      {relativeTime(item.created_at)}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {item.type === "workspace_invite" && item.data?.invite_token ? (
                        <Button
                          busy={acceptingId === item.id}
                          onClick={() => onAcceptInvite?.(item)}
                        >
                          Accept invite
                        </Button>
                      ) : null}
                      {!item.read_at ? (
                        <Button variant="secondary" onClick={() => onMarkRead?.(item.id)}>
                          Mark read
                        </Button>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <footer className="flex shrink-0 items-center justify-between gap-3 border-t border-border px-4 py-3 sm:px-6">
            <Button variant="secondary" onClick={onMarkAllRead}>Mark all read</Button>
            <Link
              to="/notifications"
              className="inline-flex h-10 items-center rounded-md px-3 text-sm font-medium text-accent-ink"
              onClick={onClose}
            >
              Show all notifications
            </Link>
          </footer>
        </aside>
      </div>
    </div>
  );
}
