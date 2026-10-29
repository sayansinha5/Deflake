const STATUS = {
  queued: "Queued",
  running: "Running",
  clean: "Clean",
  completed: "Completed",
  cancelled: "Cancelled",
  failed: "Failed",
  interrupted: "Interrupted",
  stopped_budget: "Stopped: cost budget reached",
  stopped_time: "Stopped: time budget reached",
  submitted: "Submitted",
  in_progress: "In progress",
  resolved: "Resolved",
};

export function statusLabel(status) {
  return STATUS[status] || "Unknown";
}

export function statusTone(status) {
  if (status === "resolved" || status === "completed" || status === "clean") return "success";
  if (status === "failed") return "danger";
  if (status === "cancelled") return "neutral";
  return "warning";
}

export function relativeTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const abs = Math.abs(seconds);
  const format = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (abs < 60) return format.format(seconds, "second");
  if (abs < 3600) return format.format(Math.round(seconds / 60), "minute");
  if (abs < 86400) return format.format(Math.round(seconds / 3600), "hour");
  return format.format(Math.round(seconds / 86400), "day");
}

export function exactTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function formatCount(value) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(value ?? 0);
}

export function formatPercent(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

export function firstName(fullName) {
  return (fullName || "").trim().split(/\s+/)[0] || "";
}

const CATEGORY = {
  order_dependent: "Order-dependent",
  time_dependent: "Time-dependent",
  async_race: "Async race",
  randomness: "Randomness",
  shared_resource: "Shared resource",
  hash_order: "Hash order",
  environment: "Environment",
  needs_human: "Needs a person",
};

const STATE = {
  broken: "Broken, not flaky",
  verified: "Verified",
  escalated: "Escalated",
  underpowered: "Underpowered",
  inconclusive: "Inconclusive",
  auto_pr: "Auto-PR",
  classified: "Classified",
  diagnosing: "Diagnosing",
  patching: "Patching",
  verifying: "Verifying",
};

const ROUTE = {
  auto_pr: "Auto-PR",
  escalate: "Escalate",
};

export function categoryLabel(value) {
  if (!value) return "—";
  return CATEGORY[value] || value.replaceAll("_", " ");
}

export function stateLabel(value) {
  return STATE[value] || statusLabel(value);
}

export function routeLabel(value) {
  if (!value) return "—";
  return ROUTE[value] || value;
}

export function formatScore(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(2);
}

export function formatMoney(value) {
  const number = Number(value || 0);
  if (!number) return "$0.00";
  return `$${number.toFixed(number >= 1 ? 2 : 4)}`;
}

export function detectionNote(reruns) {
  const count = Number(reruns) || 30;
  const rate = 1 - 0.05 ** (1 / count);
  const oneIn = Math.max(1, Math.round(1 / rate));
  return `A test failing less than about 1 in ${oneIn} runs may not be detected with ${count} reruns.`;
}

export function elapsed(start, end) {
  if (!start) return "—";
  const finish = end ? new Date(end) : new Date();
  const ms = Math.max(0, finish - new Date(start));
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.floor((ms % 60000) / 1000);
  return `${minutes} min ${seconds} s`;
}
