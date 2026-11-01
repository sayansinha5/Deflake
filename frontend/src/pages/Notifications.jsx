import { useCallback, useEffect, useMemo, useState } from "react";

import { PageHeader } from "../components/layout/PageHeader";
import { Button } from "../components/ui/Button";
import { api, normalizeError } from "../lib/api";
import { exactTime } from "../lib/format";

function dayKey(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return date.toLocaleDateString(undefined, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export function Notifications() {
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [accepting, setAccepting] = useState(null);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const response = await api.get("/notifications", { params: { limit: 100, offset: 0 } });
      setItems(response.data.items || []);
    } catch (err) {
      setError((err.normalized || normalizeError(err)).message);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const grouped = useMemo(() => {
    const map = new Map();
    for (const item of items) {
      const key = dayKey(item.created_at);
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(item);
    }
    return [...map.entries()];
  }, [items]);

  async function markRead(id) {
    try {
      await api.post(`/notifications/${id}/read`);
      setItems((current) =>
        current.map((item) =>
          item.id === id ? { ...item, read_at: item.read_at || new Date().toISOString() } : item,
        ),
      );
    } catch {
      /* ignore */
    }
  }

  async function acceptInvite(item) {
    const token = item.data?.invite_token;
    if (!token) return;
    setAccepting(item.id);
    try {
      await api.post("/invites/accept", { token });
      await markRead(item.id);
      await load();
    } catch (err) {
      setError((err.normalized || normalizeError(err)).message);
    } finally {
      setAccepting(null);
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl">
      <PageHeader title="Notifications" />
      <div className="mb-4 flex items-center justify-between gap-3">
        <p className="text-sm text-ink-secondary">Invites and workspace updates, newest first.</p>
        <Button variant="secondary" busy={busy} onClick={load}>Refresh</Button>
      </div>
      {error ? <p className="mb-4 text-sm text-danger" role="alert">{error}</p> : null}
      {!busy && items.length === 0 ? (
        <p className="text-sm text-ink-secondary">No notifications yet.</p>
      ) : null}
      <div className="flex flex-col gap-8">
        {grouped.map(([dateLabel, rows]) => (
          <section key={dateLabel}>
            <h2 className="mb-3 text-sm font-semibold text-ink">{dateLabel}</h2>
            <ul className="flex flex-col gap-2">
              {rows.map((item) => (
                <li
                  key={item.id}
                  className={`rounded-md border border-border px-4 py-3 ${item.read_at ? "bg-surface" : "bg-ice"}`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-ink">{item.title}</p>
                      <p className="mt-1 whitespace-pre-wrap text-sm text-ink-secondary">{item.body}</p>
                      <p className="mt-2 text-xs text-ink-muted">{exactTime(item.created_at)}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      {item.type === "workspace_invite" && item.data?.invite_token ? (
                        <Button busy={accepting === item.id} onClick={() => acceptInvite(item)}>
                          Accept
                        </Button>
                      ) : null}
                      {!item.read_at ? (
                        <Button variant="secondary" onClick={() => markRead(item.id)}>Mark read</Button>
                      ) : null}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
