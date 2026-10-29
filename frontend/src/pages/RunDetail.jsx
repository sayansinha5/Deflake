import { useEffect, useMemo, useRef, useState } from "react";
import { LayoutGrid, Pause, Play, Table2 } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { Stepper } from "../components/domain/Stepper";
import { PageHeader } from "../components/layout/PageHeader";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Dialog } from "../components/ui/Dialog";
import { ErrorState } from "../components/ui/States";
import { SkeletonRows, Table } from "../components/ui/Table";
import { useToast } from "../components/ui/Toast";
import { useRun } from "../hooks/useRun";
import { api, normalizeError } from "../lib/api";
import {
  categoryLabel,
  detectionNote,
  elapsed,
  formatMoney,
  formatPercent,
  formatScore,
  routeLabel,
  stateLabel,
  statusLabel,
  statusTone,
} from "../lib/format";

const SEGMENT_COLORS = ["#3ECF8E", "#4C8DFF", "#7C5CFF", "#F06292", "#F5A524", "#2EC4B6", "#E06C9F"];

function Interval({ low, high, rate }) {
  const left = Math.max(0, Math.min(100, Number(low) * 100));
  const width = Math.max(2, Math.min(100 - left, (Number(high) - Number(low)) * 100));
  return (
    <div className="min-w-[140px]">
      <div className="relative h-2 rounded-md bg-ice" aria-hidden="true">
        <div className="absolute top-0 h-2 rounded-md bg-gradient-to-r from-accent to-mint" style={{ left: `${left}%`, width: `${width}%` }} />
      </div>
      <p className="mt-1 text-meta text-ink">
        {formatPercent(rate)}
        <span className="text-ink-secondary"> ({formatPercent(low)}–{formatPercent(high)})</span>
      </p>
    </div>
  );
}

function testParts(testId) {
  const text = String(testId || "");
  const name = text.split("::").pop() || text;
  const file = text.includes("::") ? text.slice(0, text.lastIndexOf("::")) : "";
  return { name, file };
}

function segmentColor(index) {
  return SEGMENT_COLORS[index % SEGMENT_COLORS.length];
}

function FlakeSummary({ rows, brokenCount }) {
  const label = rows.map((row) => `${testParts(row.test_id).name} ${formatPercent(row.rate)}`).join(", ");
  return (
    <section className="rounded-xl border border-border bg-white p-5">
      <div className="flex items-start justify-between gap-6">
        <div>
          <h2 className="text-lg font-semibold text-ink">Flaky tests</h2>
          <p className="mt-1 text-sm text-ink-secondary">Failure rates in this scan</p>
        </div>
        <div className="text-right">
          <p className="text-4xl font-semibold leading-none tracking-tight text-ink">{rows.length}</p>
          <p className="mt-2 text-sm text-ink-secondary">{brokenCount} broken, not flaky</p>
        </div>
      </div>
      {rows.length ? (
        <div className="mt-5 flex h-2.5 overflow-hidden rounded-full bg-sunken" role="img" aria-label={label}>
          {rows.map((row, index) => (
            <div
              key={row.id}
              title={`${testParts(row.test_id).name} ${formatPercent(row.rate)}`}
              style={{
                flexGrow: Math.max(Number(row.rate) || 0, 0.04),
                flexBasis: 0,
                backgroundColor: segmentColor(index),
              }}
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}

function LayoutToggle({ value, onChange }) {
  return (
    <div className="mt-8 mx-1 flex items-center justify-between">
      <h3 className="text-lg text-gray-600 font-semibold">Flakes Details</h3>
      <div className="inline-flex rounded-md border border-gray-200 p-0.5 space-x-0.5" role="group" aria-label="Flake layout">
        {[{ id: "cards", label: "Cards", icon: LayoutGrid }, { id: "table", label: "Table", icon: Table2 }].map((option) => {
          const Icon = option.icon;
          const selected = value === option.id;
          return (
            <button
              key={option.id}
              type="button"
              aria-label={option.label}
              aria-pressed={selected}
              title={option.label}
              className={`bg-white rounded-md p-1.5 ${selected ? "bg-gray-200 text-gray-500" : "text-gray-300 hover:bg-gray-200 hover:text-accent"}`}
              onClick={() => onChange(option.id)}
            >
              <Icon size={16} strokeWidth={1.75} aria-hidden="true" />
            </button>
          );
        })}
      </div>
    </div>
  );
}

function FlakeCard({ row, color }) {
  const { name, file } = testParts(row.test_id);
  const score = row.confidence_cal ?? row.confidence_raw;
  const scoreTone = score == null ? "text-ink-secondary" : score >= 0.8 ? "text-success" : score >= 0.5 ? "text-warning" : "text-danger";
  const polluter = row.polluters?.length ? row.polluters[0].split("::").pop() : null;
  return (
    <Link
      to={`/flakes/${row.id}`}
      title={row.test_id}
      className="flex flex-col rounded-xl border border-border bg-white p-4 text-ink no-underline hover:border-border-strong hover:text-ink"
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: color }} aria-hidden="true" />
        <p className="truncate text-sm font-medium">{name}</p>
      </div>
      <p className="mt-2 line-clamp-2 min-h-10 text-xs leading-5 text-ink-secondary">
        {categoryLabel(row.category)}
        {file ? ` · ${file}` : ""}. Failed {row.fail_count} of {row.run_count}
        {polluter ? `. Polluter ${polluter}` : ""}.
      </p>
      <div className="mt-4 flex items-end gap-2">
        <p className="text-3xl font-semibold leading-none tracking-tight text-ink">{formatPercent(row.rate)}</p>
        <p className={`mb-0.5 text-sm font-medium ${scoreTone}`}>{formatScore(score)} confidence</p>
      </div>
    </Link>
  );
}

function eventText(event) {
  const data = event.data || {};
  if (data.message) return data.message;
  const bits = [event.type];
  for (const key of ["step", "status", "test_id"]) {
    if (data[key] != null && data[key] !== "") bits.push(String(data[key]));
  }
  return bits.join(" · ");
}

export function RunDetail() {
  const { runId } = useParams();
  const { run, events, connection, error, loading, reload } = useRun(runId);
  const { push } = useToast();
  const [flakes, setFlakes] = useState(null);
  const [flakeError, setFlakeError] = useState(null);
  const [flakeLayout, setFlakeLayout] = useState("cards");
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [showWarnings, setShowWarnings] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [paused, setPaused] = useState(false);
  const logRef = useRef(null);
  const live = run && (run.status === "queued" || run.status === "running");

  useEffect(() => {
    if (!runId) return undefined;
    let current = true;
    api.get(`/runs/${runId}/flakes`).then((response) => {
      if (current) {
        setFlakes(response.data);
        setFlakeError(null);
      }
    }).catch((err) => {
      if (current) setFlakeError(err.normalized || normalizeError(err));
    });
    return () => {
      current = false;
    };
  }, [runId, run?.status, run?.flake_count]);

  useEffect(() => {
    const log = logRef.current;
    if (!paused && log) log.scrollTop = log.scrollHeight;
  }, [events, paused]);

  const flaky = useMemo(() => (flakes || []).filter((row) => row.state !== "broken"), [flakes]);
  const broken = useMemo(() => (flakes || []).filter((row) => row.state === "broken"), [flakes]);
  const shown = events.filter((event) => {
    if (!showWarnings && !showErrors) return true;
    const level = event.data?.level;
    const isWarning = level === "warning";
    const isError = level === "error" || event.data?.status === "failed";
    return (showWarnings && isWarning) || (showErrors && isError);
  });

  async function resumeScan() {
    try {
      await api.post(`/runs/${runId}/resume`);
      push({ message: "Scan resumed." });
      reload();
    } catch (err) {
      const normalized = err.normalized || normalizeError(err);
      push({ tone: "error", message: normalized.message });
    }
  }

  async function cancelScan() {
    setCancelling(true);
    try {
      await api.post(`/runs/${runId}/cancel`);
      setCancelOpen(false);
      push({ message: "Cancel requested." });
      reload();
    } catch (err) {
      const normalized = err.normalized || normalizeError(err);
      push({ tone: "error", message: normalized.message });
    } finally {
      setCancelling(false);
    }
  }

  const columns = [
    {
      key: "test",
      header: "Test",
      cell: (row) => <Link to={`/flakes/${row.id}`} className="font-mono text-meta">{row.test_id}</Link>,
    },
    {
      key: "rate",
      header: "Failure rate",
      cell: (row) => <Interval low={row.ci_low} high={row.ci_high} rate={row.rate} />,
    },
    { key: "category", header: "Category", cell: (row) => categoryLabel(row.category) },
    {
      key: "polluter",
      header: "Polluter",
      cell: (row) => (row.polluters?.length ? row.polluters.join(", ") : "—"),
    },
    { key: "score", header: "Confidence", cell: (row) => formatScore(row.confidence_cal ?? row.confidence_raw) },
    { key: "route", header: "Routing", cell: (row) => routeLabel(row.routing) },
    {
      key: "state",
      header: "State",
      cell: (row) => <Badge tone={row.state === "broken" ? "warning" : statusTone(row.state)}>{stateLabel(row.state)}</Badge>,
    },
  ];

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader title={run ? run.repo_id : "Run"} crumbs={[{ label: "Runs", to: "/runs" }]} />
      {run?.status === "interrupted" ? (
        <p className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-warning bg-warning-subtle px-3 py-2 text-body" role="status">
          <span>This scan was interrupted.</span>
          <Button variant="secondary" onClick={resumeScan}>Resume</Button>
        </p>
      ) : null}
      {run?.status === "clean" ? (
        <p className="mb-4 rounded-md border border-border bg-surface px-3 py-2 text-body text-ink" role="status">
          {detectionNote(run.config?.detect_reruns)}
        </p>
      ) : null}
      {run?.status === "failed" && run.error_message ? (
        <p className="mb-4 whitespace-pre-wrap rounded-md border border-danger bg-danger-subtle px-3 py-2 text-body text-ink" role="alert">
          {run.error_message}
        </p>
      ) : null}
      {connection === "reconnecting" ? (
        <p className="mb-4 rounded-md border border-warning bg-warning-subtle px-3 py-2 text-body" role="status">
          Reconnecting…
        </p>
      ) : null}
      {error ? <ErrorState message={error.message} requestId={error.requestId} onRetry={reload} /> : null}
      {loading && !run ? <SkeletonRows columns={2} rows={3} /> : null}
      {run ? (
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
          <aside className="w-full shrink-0 rounded-xl border border-border bg-white p-4 lg:sticky lg:top-0 lg:w-80">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={statusTone(run.status)}>{statusLabel(run.status)}</Badge>
              <span className="text-sm text-ink-secondary">{elapsed(run.started_at || run.created_at, run.finished_at)}</span>
              <span className="text-sm text-ink-secondary">{formatMoney(run.cost_usd)}</span>
            </div>
            <p className="mt-3 break-all font-mono text-xs text-ink-muted">{run.id}</p>
            {live ? <div className="mt-3"><Button variant="danger" onClick={() => setCancelOpen(true)}>Cancel scan</Button></div> : null}
            <Stepper steps={run.steps} />
          </aside>
          <div className="flex min-w-0 flex-1 flex-col gap-4">
          {flakeError ? <ErrorState message={flakeError.message} requestId={flakeError.requestId} /> : null}
          {flakes === null && !flakeError ? <SkeletonRows /> : null}
          {flakes ? (
            <>
              <div className="flex flex-col gap-3">
                <FlakeSummary rows={flaky} brokenCount={broken.length} />
                <LayoutToggle value={flakeLayout} onChange={setFlakeLayout} />
              </div>
              {flakeLayout === "cards" ? (
                flaky.length ? (
                  <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                    {flaky.map((row, index) => (
                      <FlakeCard key={row.id} row={row} color={segmentColor(index)} />
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-ink-secondary">No flaky tests in this scan.</p>
                )
              ) : (
                flaky.length ? (
                  <Table columns={columns} rows={flaky} rowKey={(row) => row.id} />
                ) : (
                  <p className="text-sm text-ink-secondary">No flaky tests in this scan.</p>
                )
              )}
              {broken.length ? (
                <section>
                  <h2 className="text-sm font-semibold text-ink">Broken, not flaky ({broken.length})</h2>
                  <p className="mb-3 mt-1 text-sm text-ink-secondary">These fail every time, so they were not sent for a fix.</p>
                  {flakeLayout === "cards" ? (
                    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                      {broken.map((row) => (
                        <FlakeCard key={row.id} row={row} color="#C9C6D6" />
                      ))}
                    </div>
                  ) : (
                    <Table columns={columns} rows={broken} rowKey={(row) => row.id} />
                  )}
                </section>
              ) : null}
            </>
          ) : null}
          <section>
            <div className="mb-2 mt-8 flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-lg font-semibold text-gray-600">Logs</h3>
              <div className="flex flex-wrap items-center gap-4">
                <button type="button" className="inline-flex items-center gap-2 rounded-md border border-gray-200 bg-transparent px-3 py-1.5 text-sm text-ink hover:bg-gray-50" onClick={() => setPaused((value) => !value)}>
                  {paused ? <Play size={16} strokeWidth={1.75} aria-hidden="true" /> : <Pause size={16} strokeWidth={1.75} aria-hidden="true" />}
                  {paused ? "Resume Scrolling" : "Pause Scrolling"}
                </button>
                <span className="h-4 w-px bg-border" aria-hidden="true" />
                <label className="flex items-center gap-2 text-sm text-ink-secondary">
                  <input
                    type="checkbox"
                    checked={showWarnings}
                    onChange={(event) => setShowWarnings(event.target.checked)}
                    className="h-4 w-4 rounded border-border"
                  />
                  Warnings
                </label>
                <label className="flex items-center gap-2 text-sm text-ink-secondary">
                  <input
                    type="checkbox"
                    checked={showErrors}
                    onChange={(event) => setShowErrors(event.target.checked)}
                    className="h-4 w-4 rounded border-border"
                  />
                  Errors
                </label>
              </div>
            </div>
            <div ref={logRef} className="mb-16 h-96 overflow-auto rounded-md border border-border bg-sunken p-3 font-mono text-meta text-ink">
              {shown.length === 0 ? <p>No log lines yet.</p> : null}
              {shown.map((event) => (
                <p key={`${event.id}-${event.type}`}>
                  <span className="text-ink-secondary">{event.data?.created_at ? String(event.data.created_at).slice(11, 19) : ""}</span>
                  {" "}
                  {eventText(event)}
                </p>
              ))}
            </div>
          </section>
          </div>
        </div>
      ) : null}
      <Dialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        title="Cancel this scan?"
        description="Work done so far is kept."
        footer={(
          <>
            <Button variant="secondary" onClick={() => setCancelOpen(false)}>Keep running</Button>
            <Button variant="danger" busy={cancelling} onClick={cancelScan}>Cancel scan</Button>
          </>
        )}
      />
    </div>
  );
}
