import { Badge } from "../ui/Badge";

const STEPS = ["detect", "classify", "research", "diagnose", "patch", "verify", "route", "escalate"];
const LABEL = {
  detect: "Detect",
  classify: "Classify",
  research: "Research",
  diagnose: "Diagnose",
  patch: "Patch",
  verify: "Verify",
  route: "Route",
  escalate: "Escalate",
};

function tone(status) {
  if (status === "done") return "success";
  if (status === "failed") return "danger";
  if (status === "running") return "warning";
  return "neutral";
}

function label(status) {
  if (status === "done") return "Done";
  if (status === "running") return "Running";
  if (status === "failed") return "Failed";
  if (status === "skipped") return "Skipped";
  if (!status || status === "waiting") return "Waiting";
  return status;
}

export function Stepper({ steps }) {
  return (
    <ol className="mt-4">
      {STEPS.map((name, index) => {
        const step = (steps || {})[name] || {};
        const first = index === 0;
        const last = index === STEPS.length - 1;
        return (
          <li key={name} className={`flex items-center justify-between gap-3 border-dashed border-border py-2.5 ${first ? "border-t" : ""} ${last ? "" : "border-b"}`} title={step.started_at || ""}>
            <span className="text-sm text-ink">{LABEL[name]}</span>
            <Badge tone={tone(step.status)}>{step.status === "running" && step.progress ? step.progress : label(step.status)}</Badge>
          </li>
        );
      })}
    </ol>
  );
}
