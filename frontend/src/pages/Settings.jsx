import { useCallback, useEffect, useState } from "react";
import { ChevronRight, Menu as MenuIcon } from "lucide-react";
import { Link, Navigate, NavLink, Outlet, useLocation, useNavigate, useOutletContext, useParams, useSearchParams } from "react-router-dom";

import { PageHeader } from "../components/layout/PageHeader";
import { useShell } from "../components/layout/shell";
import { NotificationBell } from "../components/layout/NotificationBell";
import { AccountMenu } from "../components/layout/TopBar";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Dialog } from "../components/ui/Dialog";
import { ErrorState } from "../components/ui/States";
import { SkeletonRows } from "../components/ui/Table";
import { useToast } from "../components/ui/Toast";
import { useAuth } from "../hooks/useAuth";
import { api, normalizeError } from "../lib/api";
import { apiBaseUrl } from "../lib/config";
import { formatMoney } from "../lib/format";
import { EmailInput, inputClass } from "./authFields";

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const emptyInviteDraft = () => ({ first_name: "", last_name: "", email: "" });

const GITHUB_BANNER = {
  connected: { tone: "success", message: "GitHub connected." },
  denied: { tone: "warning", message: "GitHub connection was cancelled." },
  error: { tone: "error", message: "GitHub connection could not be completed. Try again." },
};

const STATUS = { configured: "Configured", missing: "Missing", disabled: "Disabled" };

const MENUS = [
  { id: "integration", label: "Integration", to: "/settings/integration" },
  { id: "defaults", label: "Defaults", to: "/settings/defaults" },
  { id: "account", label: "Account", to: "/settings/account" },
  { id: "members", label: "Members", to: "/settings/members" },
];

export function Settings() {
  const { user } = useAuth();
  const { openMenu } = useShell();
  const { push } = useToast();
  const location = useLocation();
  const navigate = useNavigate();
  const [view, setView] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);
  const [membersTrail, setMembersTrail] = useState(null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const owner = user?.role === "owner";
  const onMembers = location.pathname === "/settings/members"
    || location.pathname.startsWith("/settings/members/");

  const load = useCallback(async () => {
    setError(null);
    try {
      const response = await api.get("/settings");
      setView(response.data);
    } catch (err) {
      setError(err.normalized || normalizeError(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const message = location.state?.toast;
    if (!message) return;
    push({ message });
    navigate(location.pathname, { replace: true, state: {} });
  }, [location.pathname, location.state, navigate, push]);

  async function test(id) {
    setBusy(id);
    try {
      const response = await api.post(`/settings/test/${id}`);
      push({ message: response.data.message, tone: response.data.ok ? "success" : "error" });
    } catch (err) {
      const normalized = err.normalized || normalizeError(err);
      push({ tone: "error", message: normalized.message });
    } finally {
      setBusy(null);
    }
  }

  async function changePassword(event) {
    event.preventDefault();
    setSaving(true);
    try {
      await api.post("/auth/password", { current_password: currentPassword, new_password: newPassword });
      setCurrentPassword("");
      setNewPassword("");
      push({ message: "Password updated. Other sessions were signed out." });
    } catch (err) {
      const normalized = err.normalized || normalizeError(err);
      push({ tone: "error", message: normalized.message });
    } finally {
      setSaving(false);
    }
  }

  const current = MENUS.find((item) => (
    item.id === "members" ? onMembers : location.pathname === item.to
  )) || MENUS[0];

  useEffect(() => {
    if (!onMembers) setMembersTrail(null);
  }, [onMembers]);

  return (
    <div className="absolute inset-0 flex min-h-0 bg-surface">
      <PageHeader title="Settings" />
      <aside className="flex h-full w-56 shrink-0 flex-col border-r border-border">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-4">
          <button type="button" className="rounded-md p-2 hover:bg-ice md:hidden" onClick={openMenu} aria-label="Open menu">
            <MenuIcon size={18} strokeWidth={1.75} aria-hidden="true" />
          </button>
          <h2 className="text-sm font-semibold text-ink">Settings</h2>
        </header>
        <nav className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto p-2" aria-label="Settings">
          {MENUS.map((item) => (
            <NavLink
              key={item.id}
              to={item.to}
              end={item.id !== "members"}
              className={({ isActive }) => (isActive
                ? "rounded-md bg-ice px-3 py-2 text-left text-sm font-medium !text-ink !no-underline hover:!bg-ice hover:!text-ink"
                : "rounded-md px-3 py-2 text-left text-sm font-medium !text-ink-secondary !no-underline hover:!bg-sunken hover:!text-ink")}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <section className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-border px-4 sm:px-6">
          {membersTrail ? (
            <h2 className="flex min-w-0 items-center gap-1.5 text-sm font-semibold text-ink">
              <Link
                to="/settings/members"
                className="shrink-0 font-medium text-ink-secondary underline decoration-dashed decoration-gray-300 underline-offset-4 hover:text-ink"
              >
                Members
              </Link>
              <ChevronRight size={14} strokeWidth={1.75} className="shrink-0 text-ink-muted" aria-hidden="true" />
              <span className="truncate">{membersTrail}</span>
            </h2>
          ) : (
            <h2 className="truncate text-sm font-semibold text-ink">{current.label}</h2>
          )}
          <div className="flex items-center gap-3">
            <NotificationBell />
            <AccountMenu />
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
          {error ? (
            <div className="w-full max-w-2xl">
              <ErrorState message={error.message} requestId={error.requestId} onRetry={load} />
            </div>
          ) : null}
          {!view && !error ? (
            <div className="w-full max-w-2xl">
              <SkeletonRows columns={2} rows={3} />
            </div>
          ) : null}
          {view ? (
            <Outlet context={{
              view,
              load,
              user,
              owner,
              busy,
              test,
              setMembersTrail,
              currentPassword,
              setCurrentPassword,
              newPassword,
              setNewPassword,
              saving,
              changePassword,
            }}
            />
          ) : null}
        </div>
      </section>
    </div>
  );
}

export function SettingsIntegration() {
  const { view, load, busy, test } = useOutletContext();
  const { push } = useToast();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [connectOpen, setConnectOpen] = useState(false);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [disconnectBusy, setDisconnectBusy] = useState(false);
  const github = view.github || {};
  const [banner, setBanner] = useState(null);

  const githubQuery = searchParams.get("github");
  useEffect(() => {
    if (!githubQuery || !GITHUB_BANNER[githubQuery]) return undefined;
    setBanner(GITHUB_BANNER[githubQuery]);
    load();
    navigate("/settings/integration", { replace: true });
    return undefined;
  }, [githubQuery, load, navigate]);

  async function disconnect() {
    setDisconnectBusy(true);
    try {
      await api.delete("/github/connection");
      setDisconnectOpen(false);
      await load();
      push({ message: "GitHub disconnected.", tone: "success" });
    } catch (err) {
      const normalized = err.normalized || normalizeError(err);
      push({ tone: "error", message: normalized.message });
    } finally {
      setDisconnectBusy(false);
    }
  }

  function continueToGithub() {
    setConnectOpen(false);
    window.location.assign(`${apiBaseUrl}/github/oauth/start`);
  }

  return (
    <div className="flex w-full max-w-2xl flex-col gap-4">
      {banner ? (
        <div
          role="status"
          className={
            banner.tone === "success"
              ? "rounded-md border border-border bg-ice px-4 py-3 text-sm text-ink"
              : banner.tone === "warning"
                ? "rounded-md border border-border bg-sunken px-4 py-3 text-sm text-ink"
                : "rounded-md border border-danger/30 bg-sunken px-4 py-3 text-sm text-danger"
          }
        >
          {banner.message}
        </div>
      ) : null}

      <div className="rounded-md border border-border bg-surface px-4 py-3 shadow-card">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-medium text-ink">GitHub</p>
            {!github.oauth_enabled ? (
              <p className="mt-1 text-xs text-ink-secondary">
                GitHub OAuth is turned off in this environment.
              </p>
            ) : github.connected ? (
              <>
                <p className="mt-1 text-sm text-ink">
                  Connected as <span className="font-medium">@{github.login}</span>
                </p>
                {github.scopes ? (
                  <p className="mt-1 text-xs text-ink-secondary">Scopes: {github.scopes}</p>
                ) : null}
              </>
            ) : (
              <p className="mt-1 text-xs text-ink-secondary">
                Connect to import private repositories and open pull requests.
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Badge tone={github.connected ? "success" : "neutral"}>
              {github.connected ? "Connected" : "Not connected"}
            </Badge>
            {github.oauth_enabled && !github.connected ? (
              <Button onClick={() => setConnectOpen(true)}>Connect GitHub</Button>
            ) : null}
            {github.oauth_enabled && github.connected ? (
              <Button variant="secondary" onClick={() => setDisconnectOpen(true)}>Disconnect</Button>
            ) : null}
          </div>
        </div>
      </div>

      <ul className="flex flex-col gap-2">
        {view.integrations.map((item) => (
          <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-surface px-4 py-3 shadow-card">
            <div>
              <p className="text-sm text-ink">{item.label}</p>
              {item.detail && item.id !== "tendem" ? <p className="text-xs text-ink-secondary">{item.detail}</p> : null}
            </div>
            <div className="flex items-center gap-2">
              <Badge tone={item.status === "configured" ? "success" : item.status === "missing" ? "danger" : "neutral"}>
                {STATUS[item.status] || item.status}
              </Badge>
              <Button variant="secondary" busy={busy === item.id} onClick={() => test(item.id)}>Test</Button>
            </div>
          </li>
        ))}
      </ul>

      <Dialog
        open={connectOpen}
        onOpenChange={setConnectOpen}
        title="Connect GitHub"
        description="Deflake will ask GitHub for access to your repositories. GitHub grants read and write access; Deflake only reads code, and writes only when you click Create pull request."
        footer={(
          <>
            <Button variant="secondary" onClick={() => setConnectOpen(false)}>Cancel</Button>
            <Button onClick={continueToGithub}>Continue to GitHub</Button>
          </>
        )}
      />

      <Dialog
        open={disconnectOpen}
        onOpenChange={(next) => { if (!next && !disconnectBusy) setDisconnectOpen(false); }}
        title="Disconnect GitHub?"
        description="Private repositories will need a reconnect before you can sync or scan them again. Public imports stay available."
        footer={(
          <>
            <Button variant="secondary" disabled={disconnectBusy} onClick={() => setDisconnectOpen(false)}>
              Keep connected
            </Button>
            <Button variant="danger" busy={disconnectBusy} onClick={disconnect}>Disconnect</Button>
          </>
        )}
      />
    </div>
  );
}

const DETECT_CHOICES = [20, 30, 50];
const VERIFY_CHOICES = [200, 400, 600];

const MODEL_TIERS = [
  { key: "fast", label: "Fast" },
  { key: "balanced", label: "Balanced" },
  { key: "reasoning", label: "Reasoning" },
];

function modelCard(id) {
  if (!id) {
    return { company: "—", name: "Not set" };
  }
  const slash = id.indexOf("/");
  if (slash === -1) {
    return { company: "NVIDIA", name: id };
  }
  const vendor = id.slice(0, slash);
  const company = vendor.toLowerCase() === "nvidia" ? "NVIDIA" : vendor;
  return { company, name: id.slice(slash + 1) };
}

function DefaultsRow({ label, children }) {
  return (
    <div className="flex min-h-14 flex-wrap items-center justify-between gap-3 border-b border-dashed border-border py-3 last:border-b-0">
      <div className="min-w-[9rem] text-sm text-ink-secondary">{label}</div>
      <div className="min-w-0 flex-1 sm:flex sm:justify-end">{children}</div>
    </div>
  );
}

function ChoiceGroup({ name, value, options, onChange, disabled }) {
  return (
    <div className="flex flex-wrap justify-end gap-1" role="radiogroup" aria-label={name}>
      {options.map((option) => (
        <label
          key={option}
          className={`inline-flex h-8 cursor-pointer items-center rounded-md border px-4 text-sm ${
            value === option
              ? "border-transparent bg-ink text-white"
              : "border-border bg-white text-ink hover:bg-ice"
          } ${disabled ? "cursor-not-allowed opacity-60" : ""}`}
        >
          <input
            className="sr-only"
            type="radio"
            name={name}
            checked={value === option}
            disabled={disabled}
            onChange={() => onChange(option)}
          />
          {option}
        </label>
      ))}
    </div>
  );
}

export function SettingsDefaults() {
  const { view, load } = useOutletContext();
  const { push } = useToast();
  const defaults = view.defaults;
  const detectChoices = defaults.detect_choices?.length ? defaults.detect_choices : DETECT_CHOICES;
  const verifyChoices = defaults.verify_choices?.length ? defaults.verify_choices : VERIFY_CHOICES;
  const [detect, setDetect] = useState(defaults.detect_reruns);
  const [verify, setVerify] = useState(defaults.verify_reruns);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDetect(defaults.detect_reruns);
    setVerify(defaults.verify_reruns);
  }, [defaults.detect_reruns, defaults.verify_reruns]);

  const dirty = detect !== defaults.detect_reruns || verify !== defaults.verify_reruns;

  async function save() {
    setSaving(true);
    try {
      await api.put("/settings/defaults", {
        detect_reruns: detect,
        verify_reruns: verify,
      });
      await load();
      push({ message: "Defaults saved. New scans use these values." });
    } catch (err) {
      const normalized = err.normalized || normalizeError(err);
      push({ tone: "error", message: normalized.message });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="w-full max-w-3xl">
      <h3 className="text-lg font-medium tracking-wide text-ink">General</h3>
      <div className="mt-4">
        <DefaultsRow label="Detect reruns">
          <ChoiceGroup name="detect-defaults" value={detect} options={detectChoices} onChange={setDetect} disabled={saving} />
        </DefaultsRow>
        <DefaultsRow label="Verify reruns">
          <ChoiceGroup name="verify-defaults" value={verify} options={verifyChoices} onChange={setVerify} disabled={saving} />
        </DefaultsRow>
        <DefaultsRow label="Confidence threshold">
          <span className="text-sm text-ink">{Number(defaults.confidence_threshold).toFixed(2)}</span>
        </DefaultsRow>
        <DefaultsRow label="Run budget">
          <span className="text-sm text-ink">{formatMoney(defaults.run_budget_usd)}</span>
        </DefaultsRow>
        <DefaultsRow label="Escalation">
          <span className="text-sm text-ink">
            {defaults.escalation_provider}, then {defaults.escalation_fallback}
          </span>
        </DefaultsRow>
      </div>
      <div className="mt-4 flex justify-end">
        <Button busy={saving} disabled={!dirty} onClick={save}>Save defaults</Button>
      </div>

      <h3 className="mt-10 text-lg font-medium tracking-wide text-ink">Models</h3>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        {MODEL_TIERS.map((tier) => {
          const card = modelCard(view.models?.[tier.key]);
          return (
            <article
              key={tier.key}
              className="rounded-md border border-border bg-white px-4 py-3"
            >
              <p className="text-xs uppercase tracking-wide text-ink-muted">{tier.label}</p>
              <p className="mt-2 text-sm font-semibold tracking-wide text-gray-600">{card.company}</p>
              <p className="mt-1 break-all font-mono text-xs text-ink-secondary">{card.name}</p>
            </article>
          );
        })}
      </div>
    </div>
  );
}

export function SettingsAccount() {
  const {
    user,
    owner,
    currentPassword,
    setCurrentPassword,
    newPassword,
    setNewPassword,
    saving,
    changePassword,
  } = useOutletContext();
  return (
    <div className="w-full max-w-2xl">
      <p className="text-sm text-ink">{user?.full_name}</p>
      <p className="text-xs text-ink-secondary">{user?.email}</p>
      <div className="mt-2"><Badge tone={owner ? "accent" : "neutral"}>{owner ? "Owner" : "Member"}</Badge></div>
      <form className="mt-6 max-w-md" onSubmit={changePassword}>
        <label className="block text-xs text-ink-secondary" htmlFor="current-password">Current password</label>
        <input id="current-password" type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} className="mt-1 h-10 w-full rounded-md border border-border-strong bg-sunken px-3 text-sm text-ink" />
        <label className="mt-3 block text-xs text-ink-secondary" htmlFor="new-password">New password</label>
        <input id="new-password" type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} className="mt-1 h-10 w-full rounded-md border border-border-strong bg-sunken px-3 text-sm text-ink" />
        <div className="mt-4"><Button type="submit" busy={saving}>Update password</Button></div>
      </form>
    </div>
  );
}

function MemberCard({ member, onRemove }) {
  return (
    <article className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border bg-white px-4 py-3">
      <div className="min-w-0">
        <p className="text-sm font-medium text-ink">{member.full_name}</p>
        <p className="truncate text-xs text-ink-secondary">{member.email}</p>
      </div>
      {onRemove ? (
        <button
          type="button"
          onClick={() => onRemove(member)}
          className="rounded-md bg-red-50 px-3 py-2 text-sm font-medium text-red-400 transition hover:bg-red-100 hover:text-red-700"
        >
          Remove
        </button>
      ) : null}
    </article>
  );
}

function WorkspaceCard({ title, subtitle, onOpen }) {
  if (!onOpen) {
    return (
      <div className="rounded-md border border-border bg-white px-4 py-3">
        <p className="truncate text-sm font-medium text-ink">{title}</p>
        {subtitle ? <p className="mt-0.5 truncate text-xs text-ink-secondary">{subtitle}</p> : null}
      </div>
    );
  }
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group flex w-full cursor-pointer items-center justify-between gap-3 rounded-md border border-border bg-white px-4 py-3 text-left transition hover:border-border-strong hover:bg-ice focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
    >
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-ink group-hover:underline group-hover:decoration-dashed group-hover:underline-offset-4">{title}</p>
        {subtitle ? <p className="mt-0.5 truncate text-xs text-ink-secondary">{subtitle}</p> : null}
      </div>
      <span
        className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-sunken text-ink-muted transition group-hover:bg-border-strong group-hover:text-ink"
        aria-hidden="true"
      >
        <ChevronRight size={16} strokeWidth={1.75} />
      </span>
    </button>
  );
}

export function SettingsMembers() {
  const { user, owner, setMembersTrail } = useOutletContext();
  const { workspaceId } = useParams();
  const navigate = useNavigate();
  const { push } = useToast();
  const [list, setList] = useState(null);
  const [listError, setListError] = useState(null);
  const [workspace, setWorkspace] = useState(null);
  const [workspaceError, setWorkspaceError] = useState(null);
  const [members, setMembers] = useState(null);
  const [memberError, setMemberError] = useState(null);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteDraft, setInviteDraft] = useState(emptyInviteDraft);
  const [inviteDraftError, setInviteDraftError] = useState("");
  const [inviting, setInviting] = useState(false);
  const [leaveOpen, setLeaveOpen] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [removeTarget, setRemoveTarget] = useState(null);
  const [removing, setRemoving] = useState(false);

  const loadList = useCallback(() => {
    setListError(null);
    api.get("/workspaces").then((response) => {
      setList(response.data);
    }).catch((err) => {
      setListError(err.normalized || normalizeError(err));
    });
  }, []);

  useEffect(() => {
    if (workspaceId) return undefined;
    loadList();
    return undefined;
  }, [workspaceId, loadList]);

  useEffect(() => {
    if (!workspaceId) {
      setWorkspace(null);
      setMembers(null);
      setWorkspaceError(null);
      setMemberError(null);
      if (typeof setMembersTrail === "function") setMembersTrail(null);
      return undefined;
    }
    let live = true;
    setWorkspace(null);
    setMembers(null);
    setWorkspaceError(null);
    setMemberError(null);
    api.get(`/workspaces/${workspaceId}`).then((response) => {
      if (!live) return;
      setWorkspace(response.data);
      if (typeof setMembersTrail === "function") setMembersTrail(response.data.name);
    }).catch((err) => {
      if (!live) return;
      setWorkspaceError(err.normalized || normalizeError(err));
      if (typeof setMembersTrail === "function") setMembersTrail(null);
    });
    api.get(`/workspaces/${workspaceId}/members`).then((response) => {
      if (live) setMembers(response.data);
    }).catch((err) => {
      if (live) setMemberError(err.normalized || normalizeError(err));
    });
    return () => {
      live = false;
      if (typeof setMembersTrail === "function") setMembersTrail(null);
    };
  }, [workspaceId, setMembersTrail]);

  function openInviteModal() {
    setInviteDraft(emptyInviteDraft());
    setInviteDraftError("");
    setInviteOpen(true);
  }

  async function sendInvite() {
    if (workspace?.role !== "owner") return;
    const email = inviteDraft.email.trim().toLowerCase();
    if (!EMAIL.test(email)) {
      setInviteDraftError("Enter a valid email.");
      return;
    }
    if ((members || []).some((row) => row.email.toLowerCase() === email)) {
      setInviteDraftError("That person is already in this workspace.");
      return;
    }
    setInviting(true);
    setInviteDraftError("");
    try {
      const response = await api.post("/workspaces/invites", {
        email,
        first_name: inviteDraft.first_name.trim() || null,
        last_name: inviteDraft.last_name.trim() || null,
      });
      push({
        message: `Invite ready for ${response.data.email}. Share the link from your notifications if they are new to Deflake.`,
      });
      setInviteDraft(emptyInviteDraft());
      setInviteOpen(false);
      const refreshed = await api.get(`/workspaces/${workspaceId}/members`);
      setMembers(refreshed.data);
    } catch (err) {
      const normalized = err.normalized || normalizeError(err);
      setInviteDraftError(normalized.message);
    } finally {
      setInviting(false);
    }
  }

  async function confirmLeave() {
    if (!workspaceId) return;
    setLeaving(true);
    try {
      await api.post(`/workspaces/${workspaceId}/leave`);
      setLeaveOpen(false);
      push({ message: `Left ${workspace?.name || "workspace"}.` });
      navigate("/settings/members");
    } catch (err) {
      const normalized = err.normalized || normalizeError(err);
      push({ tone: "error", message: normalized.message });
    } finally {
      setLeaving(false);
    }
  }

  async function confirmRemove() {
    if (!workspaceId || !removeTarget) return;
    setRemoving(true);
    try {
      await api.delete(`/workspaces/${workspaceId}/members/${removeTarget.id}`);
      setMembers((current) => (current || []).filter((row) => row.id !== removeTarget.id));
      push({ message: `${removeTarget.full_name} was removed from the workspace.` });
      setRemoveTarget(null);
    } catch (err) {
      const normalized = err.normalized || normalizeError(err);
      push({ tone: "error", message: normalized.message });
    } finally {
      setRemoving(false);
    }
  }

  if (workspaceId) {
    const owners = (members || []).filter((member) => member.role === "owner");
    const team = (members || []).filter((member) => member.role !== "owner");
    const canManage = workspace?.role === "owner" && owner;
    const canLeave = workspace?.role === "member";

    return (
      <div className="w-full max-w-2xl">
        {workspaceError ? (
          <ErrorState
            message={workspaceError.message}
            requestId={workspaceError.requestId}
            onRetry={() => navigate("/settings/members")}
          />
        ) : null}
        {!workspace && !workspaceError ? <SkeletonRows /> : null}
        {workspace ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="flex items-center space-x-2 text-lg font-semibold text-ink">
                <span>{workspace.name}</span>
                {workspace.role === "owner" ? (
                  <Badge tone="accent" className="text-sm">Owner</Badge>
                ) : null}
              </h3>
              {canLeave ? (
                <button
                  type="button"
                  onClick={() => setLeaveOpen(true)}
                  className="rounded-md bg-red-50 px-3 py-2 text-sm font-medium text-red-400 transition hover:bg-red-100 hover:text-red-700"
                >
                  Leave Workspace
                </button>
              ) : null}
            </div>

            {canManage ? (
              <div className="mt-8 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h4 className="text-sm font-semibold text-ink-secondary">Invite team</h4>
                  <p className="mt-1 text-xs text-ink-secondary">
                    Add teammates by email so they can join this workspace.
                  </p>
                </div>
                <Button type="button" variant="secondary" onClick={openInviteModal}>
                  + New Invite
                </Button>
              </div>
            ) : null}

            {memberError ? (
              <div className="mt-6">
                <ErrorState message={memberError.message} requestId={memberError.requestId} />
              </div>
            ) : null}
            {!members && !memberError ? (
              <div className="mt-6">
                <SkeletonRows />
              </div>
            ) : null}
            {members ? (
              <>
                <h4 className="mt-8 text-sm font-semibold text-ink-secondary">Owner</h4>
                <div className="mt-3 flex flex-col gap-2">
                  {owners.map((member) => <MemberCard key={member.id} member={member} />)}
                  {owners.length === 0 ? (
                    <p className="text-sm text-ink-secondary">No owner listed.</p>
                  ) : null}
                </div>
                <h4 className="mt-8 text-sm font-semibold text-ink-secondary">Members</h4>
                <div className="mt-3 flex flex-col gap-2">
                  {team.length === 0 ? (
                    <p className="text-sm text-ink-secondary">No other members yet.</p>
                  ) : null}
                  {team.map((member) => (
                    <MemberCard
                      key={member.id}
                      member={member}
                      onRemove={
                        canManage && member.id !== user?.id
                          ? setRemoveTarget
                          : null
                      }
                    />
                  ))}
                </div>
              </>
            ) : null}
          </>
        ) : null}

        <Dialog
          open={inviteOpen}
          onOpenChange={(next) => {
            if (inviting) return;
            setInviteOpen(next);
            if (!next) {
              setInviteDraft(emptyInviteDraft());
              setInviteDraftError("");
            }
          }}
          title="New invite"
          footer={(
            <>
              <Button
                type="button"
                variant="secondary"
                disabled={inviting}
                onClick={() => {
                  setInviteOpen(false);
                  setInviteDraft(emptyInviteDraft());
                  setInviteDraftError("");
                }}
              >
                Cancel
              </Button>
              <Button type="button" busy={inviting} onClick={sendInvite}>+ Add person</Button>
            </>
          )}
        >
          <div className="mt-8 flex flex-col gap-3">
            {inviteDraftError ? (
              <p className="text-center text-sm text-danger" role="alert">{inviteDraftError}</p>
            ) : null}
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1.5 text-sm text-ink-secondary">
                First name
                <input
                  className={inputClass}
                  value={inviteDraft.first_name}
                  onChange={(event) => setInviteDraft((current) => ({
                    ...current,
                    first_name: event.target.value,
                  }))}
                />
              </label>
              <label className="flex flex-col gap-1.5 text-sm text-ink-secondary">
                Last name
                <input
                  className={inputClass}
                  value={inviteDraft.last_name}
                  onChange={(event) => setInviteDraft((current) => ({
                    ...current,
                    last_name: event.target.value,
                  }))}
                />
              </label>
            </div>
            <label className="mt-4 flex flex-col gap-1.5 text-sm text-ink-secondary">
              <span className="inline-flex items-center space-x-2">
                <span>Email</span>
                <span className="text-danger" aria-hidden="true">*</span>
              </span>
              <EmailInput
                value={inviteDraft.email}
                onChange={(event) => setInviteDraft((current) => ({
                  ...current,
                  email: event.target.value,
                }))}
                required
              />
            </label>
          </div>
        </Dialog>
        <Dialog
          open={leaveOpen}
          onOpenChange={(next) => { if (!next && !leaving) setLeaveOpen(false); }}
          title="Leave this workspace?"
          description={
            workspace
              ? `You will lose access to “${workspace.name}” and its shared repositories until you are invited again.`
              : ""
          }
          footer={(
            <>
              <Button variant="secondary" disabled={leaving} onClick={() => setLeaveOpen(false)}>Stay</Button>
              <Button variant="danger" busy={leaving} onClick={confirmLeave}>Leave Workspace</Button>
            </>
          )}
        />
        <Dialog
          open={Boolean(removeTarget)}
          onOpenChange={(next) => { if (!next && !removing) setRemoveTarget(null); }}
          title="Remove this member?"
          description={
            removeTarget
              ? `${removeTarget.full_name} will lose access to “${workspace?.name || "this workspace"}” and its shared repositories.`
              : ""
          }
          footer={(
            <>
              <Button variant="secondary" disabled={removing} onClick={() => setRemoveTarget(null)}>Cancel</Button>
              <Button variant="danger" busy={removing} onClick={confirmRemove}>Remove</Button>
            </>
          )}
        />
      </div>
    );
  }

  return (
    <div className="w-full max-w-2xl">
      {listError ? <ErrorState message={listError.message} requestId={listError.requestId} onRetry={loadList} /> : null}
      {!list && !listError ? <SkeletonRows /> : null}
      {list ? (
        <>
          <h3 className="text-lg font-semibold text-ink">Your Workspace</h3>
          <div className="mt-3 flex flex-col gap-2">
            <WorkspaceCard
              title="Personal"
              subtitle="Only you. Personal repositories stay private"
            />
            {list.owned ? (
              <WorkspaceCard
                title={list.owned.name}
                subtitle={`${list.owned.member_count} member${list.owned.member_count === 1 ? "" : "s"}`}
                onOpen={() => navigate(`/settings/members/${list.owned.id}`)}
              />
            ) : (
              <div className="rounded-md border border-dashed border-border bg-white px-4 py-3">
                <p className="text-sm font-medium text-ink">No owned workspace yet</p>
                <p className="mt-0.5 text-xs text-ink-secondary">
                  Finish onboarding to create a workspace you own.
                </p>
              </div>
            )}
          </div>

          <h3 className="mt-8 text-lg font-semibold text-ink">Member of Workspace</h3>
          <div className="mt-3 flex flex-col gap-2">
            {list.member_of.length === 0 ? (
              <p className="text-sm text-ink-secondary">
                You have not joined anyone else’s workspace yet.
              </p>
            ) : null}
            {list.member_of.map((row) => (
              <WorkspaceCard
                key={row.id}
                title={row.name}
                subtitle={`${row.member_count} member${row.member_count === 1 ? "" : "s"}`}
                onOpen={() => navigate(`/settings/members/${row.id}`)}
              />
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}
