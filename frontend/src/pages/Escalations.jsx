import { useCallback, useEffect, useState } from "react";

import { PageHeader } from "../components/layout/PageHeader";
import { Badge } from "../components/ui/Badge";
import { SmartSideModal } from "../components/ui/SmartSideModal";
import { EmptyState, ErrorState } from "../components/ui/States";
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
      {!error && rows && rows.length === 0 ? <EmptyState>Nothing is waiting for a person.</EmptyState> : null}
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
