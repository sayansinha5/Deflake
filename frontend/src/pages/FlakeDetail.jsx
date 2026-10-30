import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Copy as CopyIcon } from "lucide-react";

import { DiffView } from "../components/domain/DiffView";
import { TrustLadder } from "../components/domain/TrustLadder";
import { PageHeader } from "../components/layout/PageHeader";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Dialog } from "../components/ui/Dialog";
import { ErrorState } from "../components/ui/States";
import { SkeletonRows } from "../components/ui/Table";
import { TabPanel, Tabs } from "../components/ui/Tabs";
import { Tooltip } from "../components/ui/Tooltip";
import { useToast } from "../components/ui/Toast";
import { api, normalizeError } from "../lib/api";
import { downloadFile } from "../lib/download";
import {
  categoryLabel,
  formatPercent,
  formatScore,
  routeLabel,
  stateLabel,
  statusLabel,
  statusTone,
} from "../lib/format";

function consensusLabel(value) {
  if (value === "no_consensus") return "No consensus";
  return value || "pending";
}

function sampleText(sample) {
  if (!sample) return "";
  if (typeof sample === "string") return sample;
  return sample.traceback || sample.message || sample.output || JSON.stringify(sample);
}

function rungsFor(flake) {
  const verified = (flake.patches || []).some((patch) => patch.verification && patch.verification.outcome === "verified");
  const underpowered = flake.state === "underpowered" || (flake.patches || []).some((patch) => patch.verification?.outcome === "underpowered");
  const rejected = (flake.patches || []).some((patch) => (patch.violations || []).length > 0);
  let proof = { state: "Waiting", tone: "neutral" };
  if (flake.state === "broken") proof = { state: "Broken, not flaky", tone: "warning" };
  else if (underpowered) proof = { state: "Underpowered", tone: "warning" };
  else if (verified) proof = { state: "Verified", tone: "success" };
  else if (rejected) proof = { state: "Guardrail rejected a patch", tone: "danger" };
  const score = flake.confidence_cal ?? flake.confidence_raw;
  const confidence = score == null
    ? { state: "Not scored", tone: "neutral" }
    : { state: `${formatScore(score)} · ${routeLabel(flake.routing)}`, tone: flake.routing === "auto_pr" ? "success" : "warning" };
  const audit = flake.audit?.consensus
    ? { state: String(flake.audit.consensus), tone: "accent" }
    : { state: "No labels yet", tone: "neutral" };
  const expert = flake.escalation
    ? { state: statusLabel(flake.escalation.status), tone: statusTone(flake.escalation.status) }
    : { state: "Not escalated", tone: "neutral" };
  return [
    { id: "proof", label: "Machine proof", ...proof },
    { id: "confidence", label: "Confidence", ...confidence },
    { id: "audit", label: "Crowd audit", ...audit },
    { id: "expert", label: "Expert", ...expert },
  ];
}

export function FlakeDetail() {
  const { flakeId } = useParams();
  const { push } = useToast();
  const [flake, setFlake] = useState(null);
  const [repoName, setRepoName] = useState("");
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("diagnosis");
  const [prOpen, setPrOpen] = useState(false);
  const [prPreview, setPrPreview] = useState(null);
  const [prLoading, setPrLoading] = useState(false);
  const [prBusy, setPrBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const response = await api.get(`/flakes/${flakeId}`);
      setFlake(response.data);
    } catch (err) {
      setFlake(null);
      setError(err.normalized || normalizeError(err));
    }
  }, [flakeId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!flake?.run_id) return undefined;
    let live = true;
    api.get(`/runs/${flake.run_id}`).then((response) => {
      if (live) setRepoName(response.data.repo_id || "");
    }).catch(() => {});
    return () => {
      live = false;
    };
  }, [flake?.run_id]);

  async function copyId() {
    try {
      await navigator.clipboard.writeText(flake.test_id);
      push({ message: "Copied" });
    } catch {
      push({ tone: "error", message: "Could not copy the test id." });
    }
  }

  async function download(kind) {
    try {
      await downloadFile(`/flakes/${flake.id}/${kind}`, `${flake.id}.${kind === "patch" ? "diff" : "json"}`);
    } catch (err) {
      const normalized = err.normalized || normalizeError(err);
      push({ tone: "error", message: normalized.message });
    }
  }

  async function openPrModal() {
    setPrOpen(true);
    setPrLoading(true);
    setPrPreview(null);
    try {
      const response = await api.get(`/flakes/${flake.id}/pull-request`);
      setPrPreview(response.data);
    } catch (err) {
      const normalized = err.normalized || normalizeError(err);
      setPrPreview({ can_create: false, disabled_reason: normalized.message });
    } finally {
      setPrLoading(false);
    }
  }

  async function createPullRequest() {
    if (!flake) return;
    setPrBusy(true);
    try {
      const response = await api.post(`/flakes/${flake.id}/pull-request`);
      setPrOpen(false);
      push({ message: `Pull request #${response.data.number} opened.`, tone: "success" });
      if (response.data.html_url) {
        window.open(response.data.html_url, "_blank", "noopener,noreferrer");
      }
    } catch (err) {
      const normalized = err.normalized || normalizeError(err);
      push({ tone: "error", message: normalized.message });
    } finally {
      setPrBusy(false);
    }
  }

  function jump(id) {
    const next = { proof: "patch", confidence: "diagnosis", audit: "references", expert: "escalation" }[id] || "diagnosis";
    setTab(next);
  }

  const diagnosis = flake?.diagnoses?.[flake.diagnoses.length - 1];
  const bisect = flake?.bisection;

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader
        title="Flake"
        crumbs={[
          { label: "Runs", to: "/runs" },
          ...(flake?.run_id && repoName ? [{ label: repoName, to: `/runs/${flake.run_id}` }] : []),
        ]}
      />
      {error ? <ErrorState message={error.message} requestId={error.requestId} onRetry={load} /> : null}
      {!error && !flake ? <SkeletonRows columns={2} rows={4} /> : null}
      {flake ? (
        <div className="flex flex-col gap-6">
          <header>
            <div className="mb-2 flex items-center space-x-2">
            <p className="font-mono text-sm text-ink">{flake.test_id}</p>
              <button type="button" onClick={copyId} className="p-1 text-gray-400 hover:text-gray-700 rounded-sm"><CopyIcon className="h-4 w-4" /></button>
            </div>
            <Badge tone={flake.state === "broken" ? "warning" : statusTone(flake.state)}>{stateLabel(flake.state)}</Badge>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span className="text-body text-ink-secondary">{categoryLabel(flake.category)}</span>
              <span className="text-body text-ink">
                {formatPercent(flake.rate)}
                <span className="text-ink-secondary"> ({formatPercent(flake.ci_low)}–{formatPercent(flake.ci_high)}, {flake.fail_count}/{flake.run_count})</span>
              </span>
            </div>
            <p className="mt-2 text-body text-ink">
              Confidence {formatScore(flake.confidence_cal ?? flake.confidence_raw)} · {routeLabel(flake.routing)}
            </p>
          </header>
          <TrustLadder rungs={rungsFor(flake)} onJump={jump} />
          {flake.state === "broken" ? (
            <p className="rounded-md border border-warning bg-warning-subtle px-3 py-2 text-body text-ink">
              This test fails every time. It is broken, not flaky, and it was not sent for a fix.
            </p>
          ) : null}
          <Tabs
            value={tab}
            onValueChange={setTab}
            tabs={[
              { value: "diagnosis", label: "Diagnosis" },
              { value: "patch", label: "Patch" },
              { value: "evidence", label: "Evidence" },
              { value: "references", label: "References" },
              { value: "escalation", label: "Escalation" },
            ]}
          >
            <TabPanel value="diagnosis">
              {diagnosis ? (
                <div className="flex flex-col gap-3 text-body text-ink">
                  <p><span className="text-ink-secondary">Category. </span>{categoryLabel(diagnosis.category)}</p>
                  <p><span className="text-ink-secondary">Root cause. </span>{diagnosis.root_cause}</p>
                  <p><span className="text-ink-secondary">Mechanism. </span>{diagnosis.mechanism}</p>
                  {diagnosis.culprit ? <p><span className="text-ink-secondary">Culprit. </span><span className="font-mono text-meta">{diagnosis.culprit}</span></p> : null}
                  <p><span className="text-ink-secondary">Fix strategy. </span>{diagnosis.fix_strategy}</p>
                  <p className="text-ink-secondary">
                    Agreement {diagnosis.agreement_k} of {diagnosis.agreement_n}. Model confidence {formatScore(diagnosis.self_confidence)}.
                  </p>
                </div>
              ) : (
                <p className="text-body text-ink-secondary">No diagnosis was produced.</p>
              )}
              {bisect?.status === "isolated" && flake.polluters?.length ? (
                <p className="mt-4 text-body text-ink">
                  Polluter found by bisection: <span className="font-mono text-meta">{flake.polluters.join(", ")}</span>
                </p>
              ) : null}
              {bisect?.status === "polluter_not_isolated" ? (
                <p className="mt-4 text-body text-ink">Polluter not isolated.</p>
              ) : null}
              {bisect?.status === "not_order_dependent" ? (
                <p className="mt-4 text-body text-ink">Bisection did not find an order dependence. This test can fail on its own.</p>
              ) : null}
              {bisect?.status === "skipped" ? (
                <p className="mt-4 text-body text-ink-secondary">Bisection was not run for this category.</p>
              ) : null}
              {bisect?.steps?.length ? (
                <ol className="mt-3 text-meta text-ink-secondary">
                  {bisect.steps.map((step, index) => (
                    <li key={`${step.step}-${index}`}>
                      Step {step.step ?? index + 1}: {step.result || "checked"}
                      {step.failures != null ? `, ${step.failures} failures` : ""}
                    </li>
                  ))}
                </ol>
              ) : null}
            </TabPanel>
            <TabPanel value="patch">
              <div className="mb-3 flex flex-wrap gap-2">
                {(flake.patches || []).length ? <Button variant="secondary" onClick={() => download("patch")}>Download patch</Button> : null}
                {flake.pull_request?.show ? (
                  <Button onClick={openPrModal}>Open pull request</Button>
                ) : null}
                {flake.escalation ? <Button variant="secondary" onClick={() => download("bundle")}>Download bundle</Button> : null}
              </div>
              {(flake.patches || []).length === 0 ? <p className="text-body text-ink-secondary">No patch was proposed.</p> : null}
              {(flake.patches || []).map((patch) => (
                <article key={patch.id} className="mb-6">
                  <p className="mb-2 text-body text-ink">Attempt {patch.attempt}. {patch.summary}</p>
                  {(patch.violations || []).map((violation, index) => (
                    <p key={`${violation.rule}-${index}`} className="mb-2 rounded-md border border-danger bg-danger-subtle px-3 py-2 text-body text-ink">
                      <span className="font-medium">{violation.rule}</span>. {violation.message}
                    </p>
                  ))}
                  <DiffView diff={patch.diff} />
                  {patch.verification ? (
                    <dl className="mt-3 grid gap-2 text-body text-ink sm:grid-cols-2">
                      <div>
                        <dt className="text-meta text-ink-secondary">Before</dt>
                        <dd>{formatPercent(flake.rate)} failure rate</dd>
                      </div>
                      <div>
                        <dt className="text-meta text-ink-secondary">After</dt>
                        <dd>
                          {patch.verification.failures} failures in {patch.verification.reruns} reruns
                          {patch.verification.failures === 0 ? " (0 failures)" : ""}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-meta text-ink-secondary">Full suite</dt>
                        <dd>
                          <Badge tone={patch.verification.full_suite_passed ? "success" : "danger"}>
                            {patch.verification.full_suite_passed ? "Passed" : "Did not pass"}
                          </Badge>
                        </dd>
                      </div>
                      <div>
                        <dt className="text-meta text-ink-secondary">Outcome</dt>
                        <dd>{patch.verification.outcome === "underpowered" ? "Underpowered" : patch.verification.outcome}</dd>
                      </div>
                      {(patch.verification.regressions || []).length ? (
                        <div className="sm:col-span-2">
                          <dt className="text-meta text-ink-secondary">Regression in other tests</dt>
                          <dd className="font-mono text-meta">{patch.verification.regressions.join(", ")}</dd>
                        </div>
                      ) : null}
                    </dl>
                  ) : null}
                </article>
              ))}
            </TabPanel>
            <TabPanel value="evidence">
              <h3 className="text-sm font-medium text-ink">Failing samples</h3>
              {(flake.evidence?.failing_samples || []).slice(0, 3).map((sample, index) => (
                <div key={`fail-${index}`} className="mt-2">
                  <DiffView diff={sampleText(sample)} />
                </div>
              ))}
              {(flake.evidence?.failing_samples || []).length === 0 ? <p className="text-sm text-ink-secondary">None stored.</p> : null}
              <h3 className="mt-4 text-sm font-medium text-ink">Passing samples</h3>
              {(flake.evidence?.passing_samples || []).slice(0, 2).map((sample, index) => (
                <div key={`pass-${index}`} className="mt-2">
                  <DiffView diff={sampleText(sample)} />
                </div>
              ))}
            </TabPanel>
            <TabPanel value="references">
              {(flake.references || []).length === 0 ? (
                <p className="text-body text-ink-secondary">{flake.research_note || "No upstream references found"}</p>
              ) : null}
              <ul className="flex flex-col gap-3">
                {(flake.references || []).map((item) => (
                  <li key={item.url} className="flex justify-between rounded-md border border-border space-x-10 bg-white p-3 max-w-2xl">
                    <div>

                    <a href={item.url} target="_blank" rel="noreferrer">{item.title || item.url}</a>
                    <p className="mt-1 text-meta text-gray-600">{item.site}</p>
                    {item.snippet ? <p className="mt-4 text-sm text-gray-500">{item.snippet}</p> : null}
                    </div>
                    {item.matched ? <span className="ml-2"><Badge tone="accent">Cited</Badge></span> : null}
                  </li>
                ))}
              </ul>
              {flake.audit ? (
                <p className="mt-4 text-body text-ink">
                  Crowd audit consensus: {consensusLabel(flake.audit.consensus)}
                  {flake.audit.agreement != null ? ` (${formatScore(flake.audit.agreement)} agreement)` : ""}.
                </p>
              ) : (
                <p className="mt-4 text-body text-ink-secondary">No crowd-audit labels for this test yet.</p>
              )}
            </TabPanel>
            <TabPanel value="escalation">
              {flake.escalation ? (
                <div className="text-body text-ink">
                  <p>{flake.escalation.provider} · <Badge tone={statusTone(flake.escalation.status)}>{statusLabel(flake.escalation.status)}</Badge></p>
                  <p className="mt-2">{flake.escalation.reason}</p>
                  {flake.escalation.response ? <pre className="mt-3 whitespace-pre-wrap font-mono text-meta">{flake.escalation.response}</pre> : <p className="mt-2 text-ink-secondary">No response yet.</p>}
                  <p className="mt-3"><Link to="/escalations">Open escalations</Link></p>
                </div>
              ) : (
                <p className="text-body text-ink-secondary">This test was not escalated.</p>
              )}
            </TabPanel>
          </Tabs>

          <Dialog
            open={prOpen}
            onOpenChange={(next) => { if (!next && !prBusy) setPrOpen(false); }}
            title="Open pull request"
            description={prPreview?.full_name ? `Target ${prPreview.full_name}` : "Create a pull request on GitHub from the verified patch."}
            footer={(
              <>
                <Button variant="secondary" disabled={prBusy} onClick={() => setPrOpen(false)}>Cancel</Button>
                {prPreview?.can_create ? (
                  <Button busy={prBusy} onClick={createPullRequest}>Create pull request</Button>
                ) : (
                  <Tooltip label={prPreview?.disabled_reason || "Pull request unavailable"}>
                    <span className="inline-flex">
                      <Button disabled>Create pull request</Button>
                    </span>
                  </Tooltip>
                )}
              </>
            )}
          >
            {prLoading ? <p className="text-body text-ink-secondary">Checking GitHub access…</p> : null}
            {!prLoading && prPreview ? (
              <div className="flex flex-col gap-3 text-body text-ink">
                {prPreview.disabled_reason && !prPreview.can_create ? (
                  <p className="rounded-md border border-border bg-sunken px-3 py-2 text-ink" role="alert">
                    {prPreview.disabled_reason}
                  </p>
                ) : null}
                {prPreview.branch ? (
                  <p>
                    <span className="text-ink-secondary">Branch. </span>
                    <code className="text-meta">{prPreview.branch}</code>
                    {prPreview.base_branch ? (
                      <span className="text-ink-secondary"> → {prPreview.base_branch}</span>
                    ) : null}
                  </p>
                ) : null}
                {prPreview.title ? (
                  <p><span className="text-ink-secondary">Title. </span>{prPreview.title}</p>
                ) : null}
                {prPreview.default_moved ? (
                  <p className="text-meta text-ink-secondary">
                    The default branch has moved since the scan. The PR still starts from the scanned commit.
                  </p>
                ) : null}
                {prPreview.body ? (
                  <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-sunken p-3 text-meta text-ink">
                    {prPreview.body}
                  </pre>
                ) : null}
              </div>
            ) : null}
          </Dialog>
        </div>
      ) : null}
    </div>
  );
}
