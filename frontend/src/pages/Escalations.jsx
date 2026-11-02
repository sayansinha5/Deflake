import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "../components/layout/PageHeader";
import { Badge } from "../components/ui/Badge";
import { SmartSideModal } from "../components/ui/SmartSideModal";
import { ErrorState } from "../components/ui/States";
import { SkeletonRows, Table } from "../components/ui/Table";
import { Tooltip } from "../components/ui/Tooltip";
import { useToast } from "../components/ui/Toast";
import { api, normalizeError } from "../lib/api";
import { downloadFile } from "../lib/download";
import { exactTime, relativeTime, statusLabel, statusTone } from "../lib/format";

export function Escalations() {
  const { push } = useToast();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const response = await api.get("/escalations");
      setRows(response.data);
    } catch (err) {
      setRows(null);
      setError(err.normalized || normalizeError(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function refresh() {
    if (!open) return;
    setRefreshing(true);
    try {
      const response = await api.post(`/escalations/${open.id}/refresh`);
      setOpen(response.data);
      setRows((current) => (current || []).map((row) => (row.id === response.data.id ? response.data : row)));
      push({ message: "Status refreshed." });
    } catch (err) {
      const normalized = err.normalized || normalizeError(err);
      push({ tone: "error", message: normalized.message });
    } finally {
      setRefreshing(false);
    }
  }

  async function download() {
    try {
      await downloadFile(`/flakes/${open.flake_id}/bundle`, `${open.flake_id}.json`);
    } catch (err) {
      const normalized = err.normalized || normalizeError(err);
      push({ tone: "error", message: normalized.message });
    }
  }

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader title="Escalations" />
      {error ? <ErrorState message={error.message} requestId={error.requestId} onRetry={load} /> : null}
      {!error && rows === null ? <SkeletonRows /> : null}
      {!error && rows && rows.length === 0 ? (
        <div className="rounded-md border border-dashed border-border bg-gradient-to-b from-ice/50 to-surface px-6 py-10 text-center shadow-card">
          <h2 className="mt-2 text-lg font-semibold text-ink">Nobody is waiting</h2>
          <p className="mx-auto mt-8 max-w-xl text-body text-ink-secondary">
            When a flake sits below the confidence, the auto pull request doesn't work.
          </p>
          <p className="mx-auto mt-2 max-w-xl text-body text-ink-secondary">
            Deflake routes it to a person to decide or can be called as escalated for human review.
          </p>
          <p className="mt-8 text-body">
            <Link to="/">Open overview</Link>
            <span className="mx-2 text-ink-muted" aria-hidden>
              ·
            </span>
            <Link to="/repositories">Browse repositories</Link>
          </p>
        </div>
      ) : null}
      {!error && rows && rows.length > 0 ? (
        <Table
          columns={[
            { key: "test", header: "Test", cell: (row) => <span className="font-mono text-meta">{row.test_id}</span> },
            { key: "provider", header: "Provider", cell: (row) => row.provider },
            {
              key: "status",
              header: "Status",
              cell: (row) => <Badge tone={statusTone(row.status)}>{statusLabel(row.status)}</Badge>,
            },
            {
              key: "updated",
              header: "Updated",
              cell: (row) => (
                <Tooltip label={exactTime(row.updated_at)}>
                  <time dateTime={row.updated_at}>{relativeTime(row.updated_at)}</time>
                </Tooltip>
              ),
            },
          ]}
          rows={rows}
          rowKey={(row) => row.id}
          onRow={setOpen}
        />
      ) : null}
      <SmartSideModal
        open={Boolean(open)}
        escalation={open}
        refreshing={refreshing}
        onClose={() => setOpen(null)}
        onRefresh={refresh}
        onDownload={download}
      />
    </div>
  );
}
