import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { PageHeader } from "../components/layout/PageHeader";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { MetricTile } from "../components/ui/MetricTile";
import { EmptyState, ErrorState } from "../components/ui/States";
import { SkeletonRows, Table } from "../components/ui/Table";
import { Tooltip } from "../components/ui/Tooltip";
import { api, normalizeError } from "../lib/api";
import { exactTime, formatMoney, relativeTime, statusLabel, statusTone } from "../lib/format";

export function runColumns() {
  return [
    { key: "repo", header: "Repository", cell: (row) => row.repo_id },
    {
      key: "status",
      header: "Status",
      cell: (row) => <Badge tone={statusTone(row.status)}>{statusLabel(row.status)}</Badge>,
    },
    {
      key: "when",
      header: "Started",
      cell: (row) => {
        const value = row.started_at || row.created_at;
        return (
          <Tooltip label={exactTime(value)}>
            <time dateTime={value}>{relativeTime(value)}</time>
          </Tooltip>
        );
      },
    },
    { key: "flakes", header: "Flaky tests", cell: (row) => row.flake_count },
  ];
}

export function useRuns(limit) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const response = await api.get("/runs", { params: { limit } });
      setRows(response.data.items);
    } catch (err) {
      setRows(null);
      setError(err.normalized || normalizeError(err));
    }
  }, [limit]);

  useEffect(() => {
    load();
  }, [load]);

  return { rows, error, load };
}

export function RunTable({ rows, empty }) {
  const navigate = useNavigate();
  if (!rows.length) return <EmptyState>{empty}</EmptyState>;
  return (
    <Table
      columns={runColumns()}
      rows={rows}
      rowKey={(row) => row.id}
      onRow={(row) => navigate(`/runs/${row.id}`)}
    />
  );
}

export function Overview() {
  const { rows, error, load } = useRuns(8);
  const [spend, setSpend] = useState(null);
  const [routed, setRouted] = useState(null);
  const [hideStart, setHideStart] = useState(() => window.localStorage.getItem("deflake.hide-start") === "1");
  const latest = rows?.[0];

  useEffect(() => {
    let live = true;
    api.get("/usage").then((response) => {
      if (!live) return;
      const total = (response.data.runs || []).reduce((sum, row) => sum + Number(row.cost_usd || 0), 0);
      setSpend(total);
    }).catch(() => {
      if (live) setSpend(null);
    });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (!latest) return undefined;
    let live = true;
    api.get(`/runs/${latest.id}/flakes`).then((response) => {
      if (!live) return;
      const flaky = response.data.filter((row) => row.state !== "broken");
      setRouted({
        auto: flaky.filter((row) => row.routing === "auto_pr").length,
        escalate: flaky.filter((row) => row.routing === "escalate").length,
      });
    }).catch(() => {});
    return () => {
      live = false;
    };
  }, [latest]);

  function dismissStart() {
    window.localStorage.setItem("deflake.hide-start", "1");
    setHideStart(true);
  }

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader title="Overview" />
      {error ? <ErrorState message={error.message} requestId={error.requestId} onRetry={load} /> : null}
      {!error && rows === null ? <SkeletonRows /> : null}
      {!error && rows && rows.length === 0 && !hideStart ? (
        <section className="mb-6 rounded-md border border-border bg-gradient-to-r from-ice/80 to-white p-5 shadow-card">
          <h2 className="text-section font-semibold text-ink">Start with a demo repository</h2>
          <p className="mt-1 text-body text-ink-secondary">
            Open Repositories and scan an approved demo. The suite is rerun with a shuffled order and fresh seeds.
          </p>
          <div className="mt-4 flex gap-2">
            <Link to="/repositories" className="inline-flex h-10 items-center rounded-md bg-mint px-4 text-body font-medium text-ink hover:brightness-95">
              Go to repositories
            </Link>
            <Button variant="secondary" onClick={dismissStart}>Dismiss</Button>
          </div>
        </section>
      ) : null}
      {!error && latest ? (
        <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <MetricTile label="Flaky tests" value={latest.flake_count} hint={latest.repo_id} />
          <MetricTile label="Broken, not flaky" value={latest.broken_count} hint="Fails every time" />
          <MetricTile
            label="Routing"
            value={routed ? `${routed.auto} auto-PR` : "—"}
            hint={routed ? `${routed.escalate} escalated` : "Latest scan"}
          />
          <MetricTile label="Spend, 7 days" value={spend == null ? "—" : formatMoney(spend)} hint="Model calls" />
        </div>
      ) : null}
      {!error && rows ? (
        <RunTable rows={rows} empty="No scans yet. Start one from Repositories." />
      ) : null}
    </div>
  );
}

export function Runs() {
  const { rows, error, load } = useRuns(20);
  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader title="Runs" />
      {error ? <ErrorState message={error.message} requestId={error.requestId} onRetry={load} /> : null}
      {!error && rows === null ? <SkeletonRows /> : null}
      {!error && rows ? (
        <RunTable rows={rows} empty="No scans yet. Start one from Repositories." />
      ) : null}
    </div>
  );
}
