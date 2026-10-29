import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { PageHeader } from "../components/layout/PageHeader";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Dialog } from "../components/ui/Dialog";
import { EmptyState, ErrorState } from "../components/ui/States";
import { SkeletonRows, Table } from "../components/ui/Table";
import { Tooltip } from "../components/ui/Tooltip";
import { api, normalizeError } from "../lib/api";
import { exactTime, formatMoney, relativeTime, statusLabel, statusTone } from "../lib/format";

const DETECT = [20, 30, 50];
const VERIFY = [200, 400, 600];

function Segmented({ legend, name, value, options, onChange }) {
  return (
    <fieldset>
      <legend className="text-meta text-ink-secondary">{legend}</legend>
      <div className="mt-1 flex gap-1">
        {options.map((option) => (
          <label
            key={option}
            className={`inline-flex h-10 cursor-pointer items-center rounded-md border px-4 text-body ${
              value === option ? "border-transparent bg-ink text-white" : "border-border bg-white text-ink hover:bg-ice"
            }`}
          >
            <input
              className="sr-only"
              type="radio"
              name={name}
              checked={value === option}
              onChange={() => onChange(option)}
            />
            {option}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function Repositories() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [repo, setRepo] = useState(null);
  const [settings, setSettings] = useState(null);
  const [detect, setDetect] = useState(30);
  const [verify, setVerify] = useState(200);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const response = await api.get("/repos");
      setRows(response.data);
    } catch (err) {
      setRows(null);
      setError(err.normalized || normalizeError(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function openScan(row) {
    setRepo(row);
    setDetect(30);
    setVerify(200);
    setFormError(null);
    api.get("/settings").then((response) => setSettings(response.data)).catch(() => {});
  }

  async function startScan() {
    if (!repo) return;
    setBusy(true);
    setFormError(null);
    try {
      const response = await api.post(`/repos/${repo.id}/runs`, {
        detect_reruns: detect,
        verify_reruns: verify,
      });
      setRepo(null);
      navigate(`/runs/${response.data.run_id}`);
    } catch (err) {
      setFormError(err.normalized || normalizeError(err));
    } finally {
      setBusy(false);
    }
  }

  const budget = settings?.defaults?.run_budget_usd;
  const route = settings?.defaults?.escalation_provider || "tendem";
  const fallback = settings?.defaults?.escalation_fallback;

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader title="Repositories" />
      {error ? <ErrorState message={error.message} requestId={error.requestId} onRetry={load} /> : null}
      {!error && rows === null ? <SkeletonRows columns={4} /> : null}
      {!error && rows && rows.length === 0 ? (
        <EmptyState>No approved repositories are available.</EmptyState>
      ) : null}
      {!error && rows && rows.length > 0 ? (
        <Table
          columns={[
            { key: "name", header: "Repository", cell: (row) => row.name },
            { key: "description", header: "Description", cell: (row) => row.description },
            { key: "tests", header: "Tests", cell: (row) => row.test_count },
            {
              key: "last",
              header: "Last scan",
              cell: (row) =>
                row.last_scan_at ? (
                  <Tooltip label={exactTime(row.last_scan_at)}>
                    <time dateTime={row.last_scan_at}>{relativeTime(row.last_scan_at)}</time>
                  </Tooltip>
                ) : (
                  "—"
                ),
            },
            {
              key: "result",
              header: "Last result",
              cell: (row) =>
                row.last_result ? (
                  <Badge tone={statusTone(row.last_result)}>{statusLabel(row.last_result)}</Badge>
                ) : (
                  "—"
                ),
            },
            {
              key: "scan",
              header: "Scan",
              cell: (row) => (
                <Button variant="secondary" onClick={(event) => { event.stopPropagation(); openScan(row); }}>
                  Start scan
                </Button>
              ),
            },
          ]}
          rows={rows}
          rowKey={(row) => row.id}
        />
      ) : null}
      <Dialog
        open={Boolean(repo)}
        onOpenChange={(open) => { if (!open) setRepo(null); }}
        title={repo ? `Scan ${repo.name}` : "Scan"}
        description="Reruns the suite with a shuffled order and fresh seeds."
        footer={(
          <>
            <Button variant="secondary" onClick={() => setRepo(null)}>Cancel</Button>
            <Button busy={busy} onClick={startScan}>Start</Button>
          </>
        )}
      >
        <div className="flex flex-col gap-4">
          <Segmented legend="Detect reruns" name="detect" value={detect} options={DETECT} onChange={setDetect} />
          <Segmented legend="Verify reruns" name="verify" value={verify} options={VERIFY} onChange={setVerify} />
          <p className="text-body text-ink-secondary">Crowd audit is recorded with the scan. It is not a separate switch.</p>
          <p className="text-body text-ink-secondary">
            Escalation route: {route}{fallback ? `, then ${fallback}` : ""}.
          </p>
          <p className="text-body text-ink">Spend cap {budget == null ? "Up to $2.00" : `Up to ${formatMoney(budget)}`}.</p>
          {formError ? (
            <p className="text-body text-danger" role="alert">
              {formError.message}
              {formError.runId ? (
                <>
                  {" "}
                  <Link to={`/runs/${formError.runId}`}>Open the running scan</Link>
                </>
              ) : null}
            </p>
          ) : null}
        </div>
      </Dialog>
    </div>
  );
}
