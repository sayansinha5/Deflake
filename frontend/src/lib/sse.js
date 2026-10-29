import { apiBaseUrl } from "./config";

const NAMED = [
  "run.status",
  "step.started",
  "step.completed",
  "flake.detected",
  "flake.updated",
  "log.line",
  "usage.updated",
  "run.finished",
];

export function openEvents(path, { onEvent, onStatus, stopOnClose = false } = {}) {
  let source = null;
  let timer = null;
  let closed = false;
  let delay = 1000;

  const stop = () => {
    closed = true;
    window.clearTimeout(timer);
    source?.close();
    onStatus?.("closed");
  };

  const connect = () => {
    if (closed) return;
    onStatus?.("connecting");
    source = new EventSource(`${apiBaseUrl}${path}`, { withCredentials: true });
    source.onopen = () => {
      delay = 1000;
      onStatus?.("open");
    };
    const handle = (event) => {
      let data = {};
      try {
        data = JSON.parse(event.data);
      } catch {
        data = {};
      }
      onEvent?.({ type: event.type, id: event.lastEventId, data });
      if (event.type === "run.finished") stop();
    };
    for (const name of NAMED) source.addEventListener(name, handle);
    source.onerror = () => {
      source?.close();
      if (closed) return;
      if (stopOnClose) {
        stop();
        return;
      }
      onStatus?.("reconnecting");
      timer = window.setTimeout(connect, delay);
      delay = Math.min(delay * 2, 15000);
    };
  };

  connect();
  return stop;
}
