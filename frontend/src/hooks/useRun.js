import { useCallback, useEffect, useState } from "react";

import { api, normalizeError } from "../lib/api";
import { openEvents } from "../lib/sse";

const LIVE = new Set(["queued", "running"]);

export function useRun(runId) {
  const [run, setRun] = useState(null);
  const [events, setEvents] = useState([]);
  const [connection, setConnection] = useState("idle");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(Boolean(runId));

  const reload = useCallback(async () => {
    if (!runId) return;
    setLoading(true);
    try {
      const response = await api.get(`/runs/${runId}`);
      setRun(response.data);
      setError(null);
    } catch (err) {
      setError(err.normalized || normalizeError(err));
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    let live = true;
    if (!runId) return undefined;
    setLoading(true);
    api
      .get(`/runs/${runId}`)
      .then((response) => {
        if (live) {
          setRun(response.data);
          setError(null);
        }
      })
      .catch((err) => {
        if (live) setError(err.normalized || normalizeError(err));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [runId]);

  const status = run?.status;
  const live = LIVE.has(status);

  useEffect(() => {
    if (!runId || !status) return undefined;
    return openEvents(`/runs/${runId}/events`, {
      stopOnClose: !live,
      onStatus: setConnection,
      onEvent: (event) => {
        setEvents((current) => [...current, event].slice(-400));
        if (live && (event.type === "run.status" || event.type === "run.finished" || event.type === "flake.updated")) {
          reload();
        }
      },
    });
  }, [runId, status, live, reload]);

  return { run, events, connection, error, loading, reload };
}
