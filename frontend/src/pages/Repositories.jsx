import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { MoreVertical } from "lucide-react";

import { PageHeader } from "../components/layout/PageHeader";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Dialog } from "../components/ui/Dialog";
import { EmptyState, ErrorState } from "../components/ui/States";
import { SkeletonRows, Table } from "../components/ui/Table";
import { TabPanel, Tabs } from "../components/ui/Tabs";
import { Tooltip } from "../components/ui/Tooltip";
import { useToast } from "../components/ui/Toast";
import { api, normalizeError } from "../lib/api";
import { validateGithubRepoUrl } from "../lib/githubUrl";
import { exactTime, formatMoney, relativeTime, statusLabel, statusTone } from "../lib/format";

const DETECT = [20, 30, 50];
const VERIFY = [200, 400, 600];
const POLL_MS = 2500;

function Segmented({ legend, name, value, options, onChange }) {
  return (
    <div className="flex items-center justify-between">
      <legend className="w-3/5 text-meta text-ink-secondary">{legend}</legend>
      <div className="w-2/5 mt-1 grid grid-cols-3 gap-1.5 w-full">
        {options.map((option) => (
          <label
            key={option}
            className={`inline-flex h-8 cursor-pointer items-center justify-center rounded-md border px-4 text-body ${
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
    </div>
  );
}

function sourceLabel(row) {
  if (row.source === "demo") return "Demo";
  const base = row.source === "github_private" ? "GitHub · Private" : "GitHub";
  return row.is_personal === false ? `${base} · Workspace` : `${base} · Personal`;
}

function sourceTone(row) {
  if (row.source === "github_private") return "warning";
  if (row.source === "github_public") return "accent";
  return "neutral";
}

function prepareLabel(status) {
  if (status === "preparing" || status === "pending") return "Preparing…";
  if (status === "failed") return "Failed";
  if (status === "needs_reconnect") return "Needs reconnect";
  return "Ready";
}

function prepareTone(status) {
  if (status === "preparing" || status === "pending") return "warning";
  if (status === "failed" || status === "needs_reconnect") return "danger";
  return "success";
}

function shortSha(sha) {
  if (!sha) return "—";
  return sha.slice(0, 7);
}

function displayName(row) {
  if (row.owner && row.source !== "demo") return `${row.owner}/${row.name}`;
  return row.name;
}

function isPreparing(row) {
  return row.prepare_status === "pending" || row.prepare_status === "preparing";
}

function scanInProgress(row) {
  return row.last_result === "queued" || row.last_result === "running";
}

function RowMenu({ row, onSync, onRemove, onDetails, disabled }) {
  const [open, setOpen] = useState(false);
  const [menuPos, setMenuPos] = useState(null);
  const root = useRef(null);
  const buttonRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    function place() {
      const rect = buttonRef.current?.getBoundingClientRect();
      if (!rect) return;
      setMenuPos({
        top: Math.round(rect.bottom + 4),
        right: Math.round(window.innerWidth - rect.right),
      });
    }
    function onDoc(event) {
      if (root.current && !root.current.contains(event.target)) setOpen(false);
    }
    place();
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("resize", place);
    // Capture scroll from the table overflow container too.
    window.addEventListener("scroll", place, true);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open]);

  if (row.source === "demo") return null;

  return (
    <div className="relative" ref={root}>
      <button
        ref={buttonRef}
        type="button"
        className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-border bg-white text-ink hover:bg-ice disabled:cursor-not-allowed disabled:opacity-50"
        aria-label={`Actions for ${displayName(row)}`}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={(event) => {
          event.stopPropagation();
          setOpen((value) => {
            const next = !value;
            if (next && buttonRef.current) {
              const rect = buttonRef.current.getBoundingClientRect();
              setMenuPos({
                top: Math.round(rect.bottom + 4),
                right: Math.round(window.innerWidth - rect.right),
              });
            } else {
              setMenuPos(null);
            }
            return next;
          });
        }}
      >
        <MoreVertical size={16} strokeWidth={1.75} aria-hidden="true" />
      </button>
      {open && menuPos ? (
        <div
          role="menu"
          style={{ top: menuPos.top, right: menuPos.right }}
          className="fixed z-50 min-w-[10rem] rounded-md border border-border bg-surface py-1 shadow-panel"
        >
          <button
            type="button"
            role="menuitem"
            className="block w-full px-3 py-2 text-left text-body text-ink hover:bg-ice"
            onClick={(event) => {
              event.stopPropagation();
              setOpen(false);
              onSync(row);
            }}
          >
            Sync
          </button>
          {row.prepare_status === "failed" ? (
            <button
              type="button"
              role="menuitem"
              className="block w-full px-3 py-2 text-left text-body text-ink hover:bg-ice"
              onClick={(event) => {
                event.stopPropagation();
                setOpen(false);
                onDetails(row);
              }}
            >
              View error
            </button>
          ) : null}
          <button
            type="button"
            role="menuitem"
            disabled={scanInProgress(row)}
            title={scanInProgress(row) ? "Wait until the running scan finishes." : undefined}
            className="block w-full px-3 py-2 text-left text-body text-danger hover:bg-danger-subtle disabled:cursor-not-allowed disabled:opacity-50"
            onClick={(event) => {
              event.stopPropagation();
              if (scanInProgress(row)) return;
              setOpen(false);
              onRemove(row);
            }}
          >
            Remove
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function Repositories() {
  const navigate = useNavigate();
  const { push } = useToast();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [repo, setRepo] = useState(null);
  const [settings, setSettings] = useState(null);
  const [detect, setDetect] = useState(30);
  const [verify, setVerify] = useState(200);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState(null);

  const [addOpen, setAddOpen] = useState(false);
  const [addTab, setAddTab] = useState("public");
  const [importUrl, setImportUrl] = useState("");
  const [importTouched, setImportTouched] = useState(false);
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState(null);
  const [keepPersonal, setKeepPersonal] = useState(true);

  const [ghSearch, setGhSearch] = useState("");
  const [ghPythonOnly, setGhPythonOnly] = useState(true);
  const [ghPage, setGhPage] = useState(1);
  const [ghItems, setGhItems] = useState(null);
  const [ghHasMore, setGhHasMore] = useState(false);
  const [ghLoading, setGhLoading] = useState(false);
  const [ghError, setGhError] = useState(null);
  const [ghImporting, setGhImporting] = useState(null);

  const [removeTarget, setRemoveTarget] = useState(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [details, setDetails] = useState(null);
  const [actionBusy, setActionBusy] = useState(null);

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
    api.get("/settings").then((response) => setSettings(response.data)).catch(() => {});
  }, [load]);

  const needsPoll = useMemo(
    () => Array.isArray(rows) && rows.some(isPreparing),
    [rows],
  );

  useEffect(() => {
    if (!needsPoll) return undefined;
    const id = window.setInterval(() => {
      load();
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [needsPoll, load]);

  const urlCheck = useMemo(() => validateGithubRepoUrl(importUrl), [importUrl]);
  const importEnabled = settings?.github?.import_enabled !== false;
  const oauthEnabled = Boolean(settings?.github?.oauth_enabled);

  function openScan(row) {
    if (row.prepare_status !== "ready") return;
    setRepo(row);
    const detectDefault = settings?.defaults?.detect_reruns;
    const verifyDefault = settings?.defaults?.verify_reruns;
    setDetect(DETECT.includes(detectDefault) ? detectDefault : 30);
    setVerify(VERIFY.includes(verifyDefault) ? verifyDefault : 200);
    setFormError(null);
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

  function openAdd() {
    setAddOpen(true);
    setAddTab("public");
    setImportUrl("");
    setImportTouched(false);
    setImportError(null);
    setKeepPersonal(true);
    setGhSearch("");
    setGhPythonOnly(true);
    setGhPage(1);
    setGhItems(null);
    setGhHasMore(false);
    setGhError(null);
  }

  const githubConnected = Boolean(settings?.github?.connected);

  const loadGithubRepos = useCallback(async (page, search, pythonOnly) => {
    if (!githubConnected) return;
    setGhLoading(true);
    setGhError(null);
    try {
      const response = await api.get("/github/repos", {
        params: {
          page,
          q: search.trim() || undefined,
          python_only: pythonOnly,
        },
      });
      setGhItems(response.data.items || []);
      setGhHasMore(Boolean(response.data.has_more));
      setGhPage(response.data.page || page);
    } catch (err) {
      setGhItems([]);
      setGhError(err.normalized || normalizeError(err));
    } finally {
      setGhLoading(false);
    }
  }, [githubConnected]);

  useEffect(() => {
    if (!addOpen || addTab !== "github" || !githubConnected) return undefined;
    const handle = window.setTimeout(() => {
      loadGithubRepos(1, ghSearch, ghPythonOnly);
    }, ghSearch ? 300 : 0);
    return () => window.clearTimeout(handle);
  }, [addOpen, addTab, githubConnected, ghSearch, ghPythonOnly, loadGithubRepos]);

  async function submitImport() {
    setImportTouched(true);
    setImportError(null);
    if (!urlCheck.ok) return;
    setImportBusy(true);
    try {
      const response = await api.post("/repos/import", {
        url: importUrl.trim(),
        personal: keepPersonal,
      });
      const row = response.data;
      setAddOpen(false);
      await load();
      if (row.already_imported) {
        push({ message: "This repository is already imported." });
      } else {
        push({ message: `Importing ${row.owner}/${row.name}…` });
      }
    } catch (err) {
      setImportError(err.normalized || normalizeError(err));
    } finally {
      setImportBusy(false);
    }
  }

  async function importFromGithub(item) {
    const key = item.full_name;
    setGhImporting(key);
    setGhError(null);
    try {
      const response = await api.post("/repos/import/github", {
        owner: item.owner,
        name: item.name,
        personal: keepPersonal,
      });
      const row = response.data;
      setAddOpen(false);
      await load();
      if (row.already_imported) {
        push({ message: "This repository is already imported." });
      } else {
        push({ message: `Importing ${row.owner}/${row.name}…` });
      }
    } catch (err) {
      setGhError(err.normalized || normalizeError(err));
    } finally {
      setGhImporting(null);
    }
  }

  async function syncRepo(row) {
    setActionBusy(row.id);
    try {
      await api.post(`/repos/${row.id}/sync`);
      push({ message: `Syncing ${displayName(row)}…` });
      await load();
    } catch (err) {
      const normalized = err.normalized || normalizeError(err);
      push({ tone: "error", message: normalized.message });
    } finally {
      setActionBusy(null);
    }
  }

  async function confirmRemove() {
    if (!removeTarget) return;
    setRemoveBusy(true);
    try {
      await api.delete(`/repos/${removeTarget.id}`);
      push({ message: `Removed ${displayName(removeTarget)}.` });
      setRemoveTarget(null);
      await load();
    } catch (err) {
      const normalized = err.normalized || normalizeError(err);
      push({ tone: "error", message: normalized.message });
    } finally {
      setRemoveBusy(false);
    }
  }

  const budget = settings?.defaults?.run_budget_usd;
  const route = settings?.defaults?.escalation_provider || "tendem";
  const fallback = settings?.defaults?.escalation_fallback;

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader title="Repositories" />
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-body text-ink-secondary">
          Import a repository to scan it live. Demo repositories stay available.
        </p>
        {importEnabled ? (
          <Button onClick={openAdd}>Add repository</Button>
        ) : null}
      </div>
      {error ? <ErrorState message={error.message} requestId={error.requestId} onRetry={load} /> : null}
      {!error && rows === null ? <SkeletonRows columns={6} /> : null}
      {!error && rows && rows.length === 0 ? (
        <EmptyState>No repositories are available yet.</EmptyState>
      ) : null}
      {!error && rows && rows.length > 0 ? (
        <Table
          columns={[
            {
              key: "name",
              header: "Repository",
              cell: (row) => {
                const name = displayName(row);
                const tip = (
                  <span className="block">
                    <span className="font-medium text-ink">{name}</span>
                    {row.description ? (
                      <span className="mt-0.5 block text-ink-secondary">{row.description}</span>
                    ) : null}
                  </span>
                );
                return (
                  <Tooltip label={tip}>
                    <div className="min-w-0 max-w-md">
                      <div className="truncate font-medium text-ink">{name}</div>
                      {row.description ? (
                        <div className="mt-0.5 truncate text-meta text-ink-secondary">{row.description}</div>
                      ) : null}
                    </div>
                  </Tooltip>
                );
              },
            },
            {
              key: "source",
              header: "Source",
              cell: (row) => <Badge tone={sourceTone(row)}>{sourceLabel(row)}</Badge>,
            },
            {
              key: "prepare",
              header: "Status",
              cell: (row) => (
                <button
                  type="button"
                  className="text-left"
                  disabled={row.prepare_status !== "failed"}
                  onClick={(event) => {
                    event.stopPropagation();
                    if (row.prepare_status === "failed") setDetails(row);
                  }}
                >
                  <Badge tone={prepareTone(row.prepare_status)}>{prepareLabel(row.prepare_status)}</Badge>
                </button>
              ),
            },
            {
              key: "commit",
              header: "Commit",
              cell: (row) =>
                row.commit_sha ? (
                  <Tooltip label={row.commit_sha}>
                    <code className="text-meta text-ink">{shortSha(row.commit_sha)}</code>
                  </Tooltip>
                ) : (
                  "—"
                ),
            },
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
              key: "action",
              header: "Action",
              cell: (row) => {
                const ready = row.prepare_status === "ready";
                const button = (
                  <Button
                    variant="secondary"
                    disabled={!ready || actionBusy === row.id}
                    onClick={(event) => {
                      event.stopPropagation();
                      openScan(row);
                    }}
                  >
                    Start scan
                  </Button>
                );
                return (
                  <div className="flex items-center space-x-2">
                    {ready ? (
                      button
                    ) : (
                      <Tooltip label={isPreparing(row) ? "Wait until prepare finishes." : "This repository is not ready to scan."}>
                        <span className="inline-flex">{button}</span>
                      </Tooltip>
                    )}
                    <RowMenu
                      row={row}
                      disabled={actionBusy === row.id || isPreparing(row)}
                      onSync={syncRepo}
                      onRemove={setRemoveTarget}
                      onDetails={setDetails}
                    />
                  </div>
                );
              },
            },
          ]}
          rows={rows}
          rowKey={(row) => row.id}
        />
      ) : null}

      <Dialog
        open={Boolean(repo)}
        onOpenChange={(open) => { if (!open) setRepo(null); }}
        title={repo ? `Scan ${displayName(repo)}` : "Scan"}
        description="Reruns the suite with a shuffled order and fresh seeds."
        footer={(
          <>
            <Button variant="secondary" onClick={() => setRepo(null)}>Cancel</Button>
            <Button busy={busy} onClick={startScan}>Start</Button>
          </>
        )}
      >
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-4 my-4 py-4 border-y border-dashed border-gray-400">
          <Segmented legend="Detect reruns" name="detect" value={detect} options={DETECT} onChange={setDetect} />
          <Segmented legend="Verify reruns" name="verify" value={verify} options={VERIFY} onChange={setVerify} />
          </div>
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

      <Dialog
        open={addOpen}
        onOpenChange={setAddOpen}
        title="Add repository"
        description="Import a public GitHub project with pytest tests."
        wide
        footer={(
          <>
            <Button variant="secondary" onClick={() => setAddOpen(false)}>Cancel</Button>
            {addTab === "public" ? (
              <Button
                busy={importBusy}
                disabled={importTouched && !urlCheck.ok}
                onClick={submitImport}
              >
                Import
              </Button>
            ) : null}
          </>
        )}
      >
        <div className="mb-4 rounded-md border border-border bg-white px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium text-ink">Keep it personal</p>
            <button
              type="button"
              role="switch"
              aria-checked={keepPersonal}
              aria-label="Keep it personal"
              onClick={() => setKeepPersonal((value) => !value)}
              className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
                keepPersonal ? "bg-mint" : "bg-border-strong"
              }`}
            >
              <span
                className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                  keepPersonal ? "left-5" : "left-0.5"
                }`}
              />
            </button>
          </div>
          <p className="mt-2 text-xs leading-5 text-ink-secondary">
            {keepPersonal
              ? "Only you can see this repository and its scans. Turn this off to share it with everyone in your workspace."
              : "Shared with your workspace. Teammates can see this repository and run scans on it."}
          </p>
        </div>
        <Tabs
          value={addTab}
          onValueChange={setAddTab}
          tabs={[
            { value: "public", label: "Public URL" },
            { value: "github", label: "From your GitHub" },
          ]}
        >
          <TabPanel value="public">
            <label className="block">
              <span className="text-meta text-ink-secondary">Repository URL</span>
              <input
                className="mt-1 h-10 w-full rounded-md border border-border bg-white px-3 text-body text-ink outline-none focus:border-ink"
                value={importUrl}
                placeholder="https://github.com/owner/repo"
                autoComplete="off"
                spellCheck={false}
                onChange={(event) => {
                  setImportUrl(event.target.value);
                  setImportError(null);
                }}
                onBlur={() => setImportTouched(true)}
              />
            </label>
            <p className="mt-2 text-meta text-ink-secondary">Python projects with pytest tests work best.</p>
            {importTouched && !urlCheck.ok ? (
              <p className="mt-2 text-body text-danger" role="alert">{urlCheck.message}</p>
            ) : null}
            {importError ? (
              <p className="mt-2 text-body text-danger" role="alert">{importError.message}</p>
            ) : null}
          </TabPanel>
          <TabPanel value="github">
            {!githubConnected ? (
              <div className="rounded-md border border-border bg-ice px-4 py-5">
                <p className="text-body text-ink">
                  Connect GitHub to import private repositories.
                </p>
                <p className="mt-2 text-meta text-ink-secondary">
                  {oauthEnabled
                    ? "Use Settings → Integration to connect your GitHub account."
                    : "GitHub OAuth is not enabled in this environment yet."}
                </p>
                <Link
                  to="/settings/integration"
                  className="mt-4 inline-flex h-10 items-center rounded-md border border-border bg-white px-4 text-body font-medium text-ink hover:bg-surface"
                  onClick={() => setAddOpen(false)}
                >
                  Open Settings
                </Link>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                <p className="text-meta text-ink-secondary">
                  Connected as @{settings.github.login}. Choose a repository to import.
                </p>
                <div className="flex flex-wrap items-center gap-3">
                  <label className="min-w-[12rem] flex-1">
                    <span className="sr-only">Search repositories</span>
                    <input
                      className="h-10 w-full rounded-md border border-border bg-white px-3 text-body text-ink outline-none focus:border-ink"
                      value={ghSearch}
                      placeholder="Search by name"
                      autoComplete="off"
                      onChange={(event) => setGhSearch(event.target.value)}
                    />
                  </label>
                  <label className="inline-flex items-center gap-2 text-body text-ink">
                    <input
                      type="checkbox"
                      checked={ghPythonOnly}
                      onChange={(event) => setGhPythonOnly(event.target.checked)}
                      className="h-4 w-4 rounded border-border"
                    />
                    Python only
                  </label>
                </div>
                {ghError ? (
                  <p className="text-body text-danger" role="alert">{ghError.message}</p>
                ) : null}
                {ghLoading && ghItems === null ? (
                  <p className="text-meta text-ink-secondary">Loading repositories…</p>
                ) : null}
                {ghItems && ghItems.length === 0 && !ghLoading ? (
                  <p className="text-body text-ink-secondary">No repositories match these filters.</p>
                ) : null}
                {ghItems && ghItems.length > 0 ? (
                  <ul className="max-h-72 divide-y divide-border overflow-y-auto rounded-md border border-border">
                    {ghItems.map((item) => (
                      <li key={item.full_name} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="truncate text-body font-medium text-ink">{item.full_name}</span>
                            {item.private ? <Badge tone="warning">Private</Badge> : null}
                          </div>
                          <p className="mt-0.5 text-meta text-ink-secondary">
                            {item.updated_at ? `Updated ${relativeTime(item.updated_at)}` : "Updated —"}
                          </p>
                        </div>
                        <Button
                          variant="secondary"
                          busy={ghImporting === item.full_name}
                          disabled={Boolean(ghImporting) || ghLoading}
                          onClick={() => importFromGithub(item)}
                        >
                          Import
                        </Button>
                      </li>
                    ))}
                  </ul>
                ) : null}
                <div className="flex items-center justify-between gap-2">
                  <Button
                    variant="secondary"
                    disabled={ghLoading || ghPage <= 1}
                    onClick={() => loadGithubRepos(ghPage - 1, ghSearch, ghPythonOnly)}
                  >
                    Previous
                  </Button>
                  <span className="text-meta text-ink-secondary">Page {ghPage}</span>
                  <Button
                    variant="secondary"
                    disabled={ghLoading || !ghHasMore}
                    onClick={() => loadGithubRepos(ghPage + 1, ghSearch, ghPythonOnly)}
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}
          </TabPanel>
        </Tabs>
      </Dialog>

      <Dialog
        open={Boolean(removeTarget)}
        onOpenChange={(open) => { if (!open) setRemoveTarget(null); }}
        title="Remove repository"
        description={removeTarget ? `Remove ${displayName(removeTarget)} from Deflake?` : undefined}
        footer={(
          <>
            <Button variant="secondary" onClick={() => setRemoveTarget(null)}>Cancel</Button>
            <Button variant="danger" busy={removeBusy} onClick={confirmRemove}>Remove</Button>
          </>
        )}
      >
        <p className="text-body text-ink-secondary">
          This also deletes every scan of this repository and all of its scan data.
          Prepared files on disk are deleted. A repository cannot be removed while a scan
          is still running. You can import it again later from the same GitHub URL.
        </p>
      </Dialog>

      <Dialog
        open={Boolean(details)}
        onOpenChange={(open) => { if (!open) setDetails(null); }}
        title={details ? `Prepare failed · ${displayName(details)}` : "Prepare failed"}
        footer={<Button variant="secondary" onClick={() => setDetails(null)}>Close</Button>}
      >
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-sunken p-3 text-meta text-ink">
          {details?.prepare_error || "No error details were stored."}
        </pre>
      </Dialog>
    </div>
  );
}
