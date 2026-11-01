import { useCallback, useEffect, useState } from "react";
import { Bell } from "lucide-react";

import { api, normalizeError } from "../../lib/api";
import { NotificationsSideModal } from "../ui/NotificationsSideModal";

const POLL_MS = 30000;

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [acceptingId, setAcceptingId] = useState(null);

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) setRefreshing(true);
    try {
      const response = await api.get("/notifications", { params: { limit: 20, offset: 0 } });
      setItems(response.data.items || []);
      setUnread(response.data.unread || 0);
    } catch {
      /* keep last good state */
    } finally {
      if (!quiet) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load({ quiet: true });
    const timer = window.setInterval(() => load({ quiet: true }), POLL_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (open) load({ quiet: true });
  }, [open, load]);

  async function markRead(id) {
    try {
      await api.post(`/notifications/${id}/read`);
      await load({ quiet: true });
    } catch {
      /* ignore */
    }
  }

  async function markAllRead() {
    try {
      await api.post("/notifications/read-all");
      await load({ quiet: true });
    } catch {
      /* ignore */
    }
  }

  async function acceptInvite(item) {
    const token = item.data?.invite_token;
    if (!token) return;
    setAcceptingId(item.id);
    try {
      await api.post("/invites/accept", { token });
      await load({ quiet: true });
    } catch (err) {
      window.alert((err.normalized || normalizeError(err)).message);
    } finally {
      setAcceptingId(null);
    }
  }

  return (
    <>
      <button
        type="button"
        className="relative flex h-8 w-8 items-center justify-center rounded-md border border-border bg-white text-ink-secondary hover:bg-ice hover:text-ink"
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        onClick={() => setOpen(true)}
      >
        <Bell size={16} strokeWidth={1.75} aria-hidden="true" />
        {unread > 0 ? (
          <span
            className="absolute right-1 top-1 h-2 w-2 rounded-full bg-orange-500"
            aria-hidden="true"
          />
        ) : null}
      </button>
      <NotificationsSideModal
        open={open}
        items={items}
        unread={unread}
        refreshing={refreshing}
        acceptingId={acceptingId}
        onClose={() => setOpen(false)}
        onRefresh={() => load()}
        onMarkRead={markRead}
        onMarkAllRead={markAllRead}
        onAcceptInvite={acceptInvite}
      />
    </>
  );
}
