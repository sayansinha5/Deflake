import { useCallback, useState, useEffect } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { PageHeader } from "../components/layout/PageHeader";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Dialog } from "../components/ui/Dialog";
import { ErrorState } from "../components/ui/States";
import { SkeletonRows, Table } from "../components/ui/Table";
import { Tooltip as Hint } from "../components/ui/Tooltip";
import { useToast } from "../components/ui/Toast";
import { useAuth } from "../hooks/useAuth";
import { api, normalizeError } from "../lib/api";
import { exactTime, formatScore } from "../lib/format";

function ChartTip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-meta text-ink shadow-menu">
      <p>{label}</p>
      {payload.map((item) => (
        <p key={item.dataKey}>
          {item.name}: {item.value == null ? "no labels" : Number(item.value).toFixed(2)}
        </p>
      ))}
    </div>
  );
}

export function Calibration() {
  const { user } = useAuth();
  const { push } = useToast();
  const [view, setView] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(false);
  const [threshold, setThreshold] = useState(0.8);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const owner = user?.role === "owner";

  const load = useCallback(async () => {
    setError(null);
    try {
      const response = await api.get("/calibration");
      setView(response.data);
      setThreshold(Number(response.data.threshold));
    } catch (err) {
      setView(null);
      setError(err.normalized || normalizeError(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function save() {
    setBusy(true);
    try {
      const response = await api.put("/calibration/threshold", { threshold: Number(threshold), reason });
      setView(response.data);
      setOpen(false);
      setReason("");
      push({ message: "Threshold saved." });
    } catch (err) {
      const normalized = err.normalized || normalizeError(err);
      push({ tone: "error", message: normalized.message });
    } finally {
      setBusy(false);
    }
  }

  const points = (view?.reliability || []).map((bin) => ({
    name: `${Number(bin.low).toFixed(2)}–${Number(bin.high).toFixed(2)}`,
    observed: bin.count ? bin.observed : null,
    predicted: bin.count ? bin.mean_predicted : null,
    count: bin.count,
  }));

  const changeButton = (
    <Button variant="secondary" disabled={!owner} onClick={() => setOpen(true)}>
      Change threshold
    </Button>
  );

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader title="Calibration" />
      {error ? <ErrorState message={error.message} requestId={error.requestId} onRetry={load} /> : null}
      {!error && !view ? <SkeletonRows columns={2} rows={3} /> : null}
      {view ? (
        <div className="flex flex-col gap-6">
          <section className="rounded-md border border-border bg-surface p-5 shadow-card">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-body text-ink">{view.message}</p>
                {view.partial ? <p className="mt-1 text-meta text-ink-secondary">Partial result. Empty bins are not filled in.</p> : null}
              </div>
              {owner ? changeButton : (
                <Hint label="Only the workspace owner can change this.">
                  <span className="inline-flex">{changeButton}</span>
                </Hint>
              )}
            </div>
            <dl className="mt-4 grid gap-4 sm:grid-cols-4">
              <div>
                <dt className="text-meta text-ink-secondary">Threshold</dt>
                <dd className="text-metric font-semibold text-ink">{Number(view.threshold).toFixed(2)}</dd>
              </div>
              <div>
                <dt className="text-meta text-ink-secondary">Labels</dt>
                <dd className="text-metric font-semibold text-ink">{view.n_labels}<span className="text-body font-normal text-ink-secondary"> / {view.min_labels}</span></dd>
              </div>
              <div>
                <dt className="text-meta text-ink-secondary">Precision</dt>
                <dd className="text-section font-medium text-ink">{formatScore(view.precision_at)}</dd>
              </div>
              <div>
                <dt className="text-meta text-ink-secondary">Coverage</dt>
                <dd className="text-section font-medium text-ink">{formatScore(view.coverage_at)}</dd>
              </div>
            </dl>
            <div className="mt-4 h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={points}>
                  <CartesianGrid stroke="#E4E2EA" vertical={false} />
                  <XAxis dataKey="name" stroke="#4E5080" tick={{ fill: "#4E5080", fontSize: 12 }} />
                  <YAxis stroke="#4E5080" tick={{ fill: "#4E5080", fontSize: 12 }} domain={[0, 1]} />
                  <Tooltip content={<ChartTip />} cursor={{ fill: "#F0EFF2" }} />
                  <Bar dataKey="predicted" name="Predicted" fill="#1C1C4A" radius={[6, 6, 0, 0]} />
                  <Bar dataKey="observed" name="Observed" fill="#6C78D7" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className="mt-2 text-meta text-ink-secondary">Source {view.source}. Predicted is navy, observed is periwinkle.</p>
          </section>
          <section>
            <h2 className="mb-2 text-section font-semibold text-ink">Batches</h2>
            {(view.batches || []).length === 0 ? <p className="text-body text-ink-secondary">No audit batches yet.</p> : (
              <Table
                columns={[
                  { key: "provider", header: "Provider", cell: (row) => row.provider },
                  { key: "status", header: "Status", cell: (row) => <Badge tone="neutral">{row.status}</Badge> },
                  { key: "items", header: "Items", cell: (row) => `${row.labelled_count} / ${row.item_count}` },
                  { key: "when", header: "Created", cell: (row) => exactTime(row.created_at) },
                ]}
                rows={view.batches}
                rowKey={(row) => row.id}
              />
            )}
          </section>
        </div>
      ) : null}
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title="Change threshold"
        description="The cutoff applies to future scores. Current labels stay as they are."
        footer={(
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
            <Button busy={busy} disabled={!reason.trim()} onClick={save}>Save</Button>
          </>
        )}
      >
        <label className="block text-meta text-ink-secondary" htmlFor="threshold">
          Threshold {Number(threshold).toFixed(2)}
        </label>
        <input
          id="threshold"
          type="range"
          min="0.5"
          max="0.95"
          step="0.05"
          value={threshold}
          onChange={(event) => setThreshold(Number(event.target.value))}
          className="mt-2 w-full"
        />
        <label className="mt-4 block text-meta text-ink-secondary" htmlFor="reason">Reason</label>
        <textarea
          id="reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className="mt-1 h-24 w-full rounded-md border border-border-strong bg-sunken px-3 py-2 text-body text-ink"
        />
        {view ? (
          <p className="mt-3 text-meta text-ink-secondary">
            {view.n_labels} labels in. Precision {formatScore(view.precision_at)}, coverage {formatScore(view.coverage_at)}. {view.message}
          </p>
        ) : null}
      </Dialog>
    </div>
  );
}
