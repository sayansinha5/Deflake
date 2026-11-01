import { useEffect, useMemo, useState } from "react";
import { ArrowRightIcon, Check } from "lucide-react";
import { useNavigate } from "react-router-dom";
import clsx from "clsx";

import { Mark } from "../components/layout/Mark";
import { Button } from "../components/ui/Button";
import { Dialog } from "../components/ui/Dialog";
import { useAuth } from "../hooks/useAuth";
import { api, normalizeError } from "../lib/api";
import { apiBaseUrl, appName } from "../lib/config";
import { EmailInput, inputClass } from "./authFields";

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const DRAFT_KEY = "deflake.onboarding.draft";

const STEPS = [
  {
    id: "workspace",
    label: "Workspace",
    blurb:
      "Name the place where your teams repositories, scans, and flakes live. Need one workspace to run your first scan.",
    title: "Create your workspace",
    subtitle: (
      <>
        Organises scans, flakes, and members inside a workspace.
      </>
    ),
  },
  {
    id: "team",
    label: "Invite Team",
    blurb:
      "Add teammates by email so they can join this workspace. Email identifies each invite.",
    title: "Invite Team",
    subtitle: (
      <div className="flex items-center space-x-2">
        <span>You can invite people later from </span><strong className="flex items-center space-x-2"><span>Settings</span> <ArrowRightIcon size={14} /> <span>Members</span></strong>.
      </div>
    ),
  },
  {
    id: "github",
    label: "GitHub",
    blurb:
      "Connect GitHub to browse public and private repos and open pull requests.",
    title: "Connect GitHub",
    subtitle: (
      <div className="flex items-center space-x-2">
        <span>You can connect later from </span><strong className="flex items-center space-x-2"><span>Settings</span> <ArrowRightIcon size={14} /> <span>Integration</span></strong>.
      </div>
    ),
  },
];

const emptyDraft = () => ({ first_name: "", last_name: "", email: "" });

function inviteDisplayName(row) {
  const name = [row.first_name, row.last_name].map((part) => (part || "").trim()).filter(Boolean).join(" ");
  return name || row.email.split("@")[0] || "Invite";
}

function readDraft() {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function Onboarding() {
  const { user, refresh } = useAuth();
  const navigate = useNavigate();
  const saved = useMemo(() => readDraft(), []);
  const [step, setStep] = useState(saved?.step ?? 0);
  const [workspaceName, setWorkspaceName] = useState(
    saved?.workspaceName
      || (user?.full_name ? `${user.full_name.split(" ")[0]}'s workspace` : ""),
  );
  const [invites, setInvites] = useState(saved?.invites || []);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [draft, setDraft] = useState(emptyDraft);
  const [draftError, setDraftError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [github, setGithub] = useState(null);

  useEffect(() => {
    document.title = `Set up workspace · ${appName}`;
  }, []);

  useEffect(() => {
    let live = true;
    api.get("/github/connection").then((response) => {
      if (live) setGithub(response.data);
    }).catch(() => {
      if (live) setGithub({ oauth_enabled: false, connected: false });
    });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    sessionStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({ step, workspaceName, invites }),
    );
  }, [step, workspaceName, invites]);

  const nameOk = workspaceName.trim().length > 0;
  const inviteRows = useMemo(
    () => invites.filter((row) => EMAIL.test(row.email.trim())),
    [invites],
  );
  const current = STEPS[step];
  const canContinue = step === 0 ? nameOk : true;

  function clearDraft() {
    sessionStorage.removeItem(DRAFT_KEY);
  }

  function connectGithub() {
    sessionStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({ step: 2, workspaceName, invites }),
    );
    window.location.assign(`${apiBaseUrl}/github/oauth/start`);
  }

  function openInviteModal() {
    setDraft(emptyDraft());
    setDraftError("");
    setInviteOpen(true);
  }

  function addPerson() {
    const email = draft.email.trim().toLowerCase();
    if (!EMAIL.test(email)) {
      setDraftError("Enter a valid email.");
      return;
    }
    if (invites.some((row) => row.email.trim().toLowerCase() === email)) {
      setDraftError("That email is already on the invite list.");
      return;
    }
    setInvites((rows) => [
      ...rows,
      {
        first_name: draft.first_name.trim(),
        last_name: draft.last_name.trim(),
        email,
      },
    ]);
    setDraft(emptyDraft());
    setDraftError("");
    setInviteOpen(false);
  }

  function removeInvite(index) {
    setInvites((rows) => rows.filter((_, i) => i !== index));
  }

  async function finish() {
    setBusy(true);
    setError(null);
    try {
      const payload = {
        name: workspaceName.trim(),
        invites: inviteRows.map((row) => ({
          email: row.email.trim(),
          first_name: row.first_name.trim() || null,
          last_name: row.last_name.trim() || null,
        })),
      };
      await api.post("/workspaces/onboarding", payload);
      clearDraft();
      await refresh();
      navigate("/", {
        replace: true,
        state: {
          toast: github?.connected
            ? "Workspace created."
            : "Workspace created. You can connect GitHub later from Settings → Integration.",
        },
      });
    } catch (err) {
      setError(err.normalized || normalizeError(err));
    } finally {
      setBusy(false);
    }
  }

  function onPrimary() {
    if (step < STEPS.length - 1) {
      if (!canContinue) return;
      setStep((value) => value + 1);
      return;
    }
    finish();
  }

  return (
    <div className="flex h-screen min-h-0 gap-4 bg-white p-3 sm:p-4">
      <aside className="flex h-full w-[30%] shrink-0 flex-col overflow-y-auto rounded-md bg-ink py-8 text-white">
        <div className="flex items-center gap-3 px-8">
          <Mark />
          <span className="text-lg font-semibold">{appName}</span>
        </div>

        <div className="mt-14 flex flex-col gap-10 px-10 pb-4 sm:px-12">
          {STEPS.map((item, index) => {
            const active = index === step;
            const done = index < step;
            const lit = active || done;
            return (
              <div key={item.id} className="mt-8 flex items-start space-x-6">
                <span
                  className={clsx(
                    "flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-sm font-semibold leading-none",
                    done
                      ? "bg-mint text-ink"
                      : active
                        ? "bg-white text-ink"
                        : "bg-white/10 text-white/70",
                  )}
                  aria-hidden="true"
                >
                  {done ? <Check size={14} strokeWidth={2.5} /> : index + 1}
                </span>
                <div className="min-w-0">
                  <h2
                    className={clsx(
                      "text-xl font-semibold leading-7 tracking-tight",
                      lit ? "text-white" : "text-white/45",
                    )}
                  >
                    {item.label}
                  </h2>
                  <p
                    className={clsx(
                      "mt-2 pr-2 text-sm leading-6 sm:pr-4",
                      lit ? "text-white/80" : "text-white/35",
                    )}
                  >
                    {item.blurb}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </aside>

      <section className="flex h-full min-h-0 w-[70%] min-w-0 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-8 sm:px-10 lg:px-14">
          <div className="w-full max-w-4xl">
            <p className="mb-10 text-xs font-medium uppercase tracking-wide text-ink-muted">
              Step {step + 1} of {STEPS.length}
            </p>
            {step === 1 ? (
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h1 className="text-3xl font-semibold tracking-tight text-ink">{current.title}</h1>
                {invites.length > 0 ? (
                  <Button type="button" variant="secondary" onClick={openInviteModal}>
                    + New Invite
                  </Button>
                ) : null}
              </div>
            ) : (
              <h1 className="text-3xl font-semibold tracking-tight text-ink">{current.title}</h1>
            )}
            <div className="mt-2 max-w-2xl text-sm leading-6 text-ink-secondary [&_strong]:font-semibold [&_strong]:text-ink">
              {current.subtitle}
            </div>
            {error ? (
              <p className="mt-4 max-w-2xl text-center text-sm text-danger" role="alert">
                {error.message}
              </p>
            ) : null}

            <div className="mt-8">
              {step === 0 ? (
                <div className="flex max-w-xl flex-col gap-5">
                  <label className="flex flex-col gap-1.5 text-body text-ink-secondary">
                    <span className="inline-flex items-center space-x-2">
                      <span>Workspace name</span>
                      <span className="text-danger" aria-hidden="true">*</span>
                    </span>
                    <input
                      className={inputClass}
                      value={workspaceName}
                      onChange={(event) => setWorkspaceName(event.target.value)}
                      autoFocus
                      required
                    />
                  </label>
                  <div className="rounded-md bg-ice px-4 py-4 text-sm text-ink-secondary">
                    <p className="font-medium text-ink">Why a workspace?</p>
                    <p className="mt-1 leading-6">
                      A workspace holds your repositories, scan history, members, and confidence settings.
                      Every account needs at least one workspace before you can run a scan.
                    </p>
                  </div>
                </div>
              ) : null}

              {step === 1 ? (
                <div className="flex max-w-2xl flex-col gap-3">
                  {invites.length === 0 ? (
                    <article className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-dashed border-border bg-sunken/40 px-4 py-4">
                      <p className="text-sm text-ink-muted/70">Use invite to add teammates</p>
                      <Button type="button" variant="secondary" onClick={openInviteModal}>
                        + New Invite
                      </Button>
                    </article>
                  ) : null}
                  {invites.map((row, index) => (
                    <article
                      key={`${row.email}-${index}`}
                      className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border bg-white px-4 py-3"
                    >
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-ink">{inviteDisplayName(row)}</p>
                        <p className="truncate text-xs text-ink-secondary">{row.email}</p>
                      </div>
                      <Button type="button" variant="secondary" onClick={() => removeInvite(index)}>
                        Remove
                      </Button>
                    </article>
                  ))}
                </div>
              ) : null}

              {step === 2 ? (
                <div className="flex max-w-2xl flex-col gap-4">
                  <div className="rounded-md bg-ice px-4 py-4 text-sm text-ink-secondary">
                    <p className="mt-1 leading-6">
                      Connecting GitHub lets you browse your public and private repos and open pull
                      requests for verified fixes.
                    </p>
                    <p className="mt-4 leading-6">
                      <strong>Note:</strong> You can still scan by pasting a public repository URL each time.
                    </p>
                  </div>
                  <article className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border bg-white px-4 py-4">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-ink">GitHub</p>
                      {!github ? (
                        <p className="mt-1 text-xs text-ink-secondary">Checking connection…</p>
                      ) : !github.oauth_enabled ? (
                        <p className="mt-1 text-xs text-ink-secondary">
                          GitHub OAuth is turned off in this environment.
                        </p>
                      ) : github.connected ? (
                        <p className="mt-1 text-xs text-ink-secondary">
                          Connected as <span className="font-medium text-ink">@{github.login}</span>
                        </p>
                      ) : (
                        <p className="mt-1 text-xs text-ink-secondary">
                          Not connected. Connect to import private repos and open pull requests.
                        </p>
                      )}
                    </div>
                    {github?.oauth_enabled && !github.connected ? (
                      <Button type="button" onClick={connectGithub}>
                        Connect GitHub
                      </Button>
                    ) : null}
                    {github?.connected ? (
                      <span className="rounded-md bg-success-subtle px-2 py-1 text-xs font-medium text-success">
                        Connected
                      </span>
                    ) : null}
                  </article>
                </div>
              ) : null}
            </div>
          </div>
        </div>

        <footer className="flex shrink-0 items-center gap-2 px-6 py-4 sm:px-10 lg:px-14">
          {step > 0 ? (
            <Button type="button" variant="secondary" onClick={() => setStep((value) => value - 1)}>
              Back
            </Button>
          ) : null}
          <Button
            type="button"
            busy={busy}
            disabled={!canContinue}
            onClick={onPrimary}
          >
            {step === STEPS.length - 1 ? "Finish" : "Continue"}
          </Button>
        </footer>
      </section>

      <Dialog
        open={inviteOpen}
        onOpenChange={setInviteOpen}
        title="New invite"
        footer={(
          <>
            <Button type="button" variant="secondary" onClick={() => setInviteOpen(false)}>
              Cancel
            </Button>
            <Button type="button" onClick={addPerson}>+ Add person</Button>
          </>
        )}
      >
        <div className="mt-8 flex flex-col gap-3">
          {draftError ? (
            <p className="text-center text-sm text-danger" role="alert">{draftError}</p>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5 text-sm text-ink-secondary">
              First name
              <input
                className={inputClass}
                value={draft.first_name}
                onChange={(event) => setDraft((current) => ({ ...current, first_name: event.target.value }))}
              />
            </label>
            <label className="flex flex-col gap-1.5 text-sm text-ink-secondary">
              Last name
              <input
                className={inputClass}
                value={draft.last_name}
                onChange={(event) => setDraft((current) => ({ ...current, last_name: event.target.value }))}
              />
            </label>
          </div>
          <label className="mt-4 flex flex-col gap-1.5 text-sm text-ink-secondary">
            <span className="inline-flex items-center space-x-2">
              <span>Email</span>
              <span className="text-danger" aria-hidden="true">*</span>
            </span>
            <EmailInput
              value={draft.email}
              onChange={(event) => setDraft((current) => ({ ...current, email: event.target.value }))}
              required
            />
          </label>
        </div>
      </Dialog>
    </div>
  );
}
