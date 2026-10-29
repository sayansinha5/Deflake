import { useCallback, useEffect, useState } from "react";

import { PageHeader } from "../components/layout/PageHeader";
import { EmptyState, ErrorState } from "../components/ui/States";
import { SkeletonRows, Table } from "../components/ui/Table";
import { api, normalizeError } from "../lib/api";
import { formatCount, formatMoney } from "../lib/format";

const TIER = { fast: "Nano", balanced: "Super", reasoning: "Ultra" };

export function Usage() {
  const [view, setView] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const response = await api.get("/usage");
      setView(response.data);
    } catch (err) {
      setView(null);
      setError(err.normalized || normalizeError(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const tiers = view?.tiers || [];
  const runs = view?.runs || [];

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader title="Usage" />
      {error ? <ErrorState message={error.message} requestId={error.requestId} onRetry={load} /> : null}
      {!error && !view ? <SkeletonRows /> : null}
      {view && tiers.length === 0 ? (
        <EmptyState>No model calls in the last 7 days.</EmptyState>
      ) : null}
      {tiers.length ? (
        <div className="flex flex-col gap-6">
          <section>
            <h2 className="mb-2 text-section font-semibold text-ink">By tier</h2>
            <Table
              columns={[
                { key: "tier", header: "Tier", cell: (row) => TIER[row.tier] || row.tier },
                { key: "model", header: "Model", cell: (row) => <span className="font-mono text-meta">{row.model}</span> },
                { key: "calls", header: "Calls", cell: (row) => formatCount(row.calls) },
                { key: "in", header: "Input tokens", cell: (row) => formatCount(row.input_tokens) },
                { key: "out", header: "Output tokens", cell: (row) => formatCount(row.output_tokens) },
                { key: "p50", header: "p50", cell: (row) => (row.p50_ms == null ? "—" : `${formatCount(row.p50_ms)} ms`) },
                { key: "p95", header: "p95", cell: (row) => (row.p95_ms == null ? "—" : `${formatCount(row.p95_ms)} ms`) },
                { key: "cost", header: "Estimated cost", cell: (row) => formatMoney(row.cost_usd) },
              ]}
              rows={tiers}
              rowKey={(row) => row.tier}
            />
          </section>
          <section>
            <h2 className="mb-2 text-section font-semibold text-ink">By scan</h2>
            <Table
              columns={[
                { key: "repo", header: "Repository", cell: (row) => row.repo_id || "—" },
                { key: "calls", header: "Calls", cell: (row) => formatCount(row.calls) },
                { key: "tokens", header: "Tokens", cell: (row) => formatCount(row.input_tokens + row.output_tokens) },
                { key: "cost", header: "Estimated cost", cell: (row) => formatMoney(row.cost_usd) },
              ]}
              rows={runs}
              rowKey={(row) => row.run_id}
            />
          </section>
        </div>
      ) : null}
    </div>
  );
}
