import { useCallback, useEffect, useState } from "react";
import { Menu as MenuIcon } from "lucide-react";
import { NavLink, Outlet, useLocation, useNavigate, useOutletContext, useSearchParams } from "react-router-dom";

import { PageHeader } from "../components/layout/PageHeader";
import { useShell } from "../components/layout/shell";
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
  const [view, setView] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);
  const [members, setMembers] = useState(null);
  const [memberError, setMemberError] = useState(null);
  const [target, setTarget] = useState(null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const owner = user?.role === "owner";

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
    if (!owner) return undefined;
    let live = true;
    api.get("/members").then((response) => {
      if (live) setMembers(response.data);
    }).catch((err) => {
      if (live) setMemberError(err.normalized || normalizeError(err));
    });
    return () => {
      live = false;
    };
  }, [owner]);

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

  async function deactivate() {
    if (!target) return;
    try {
      const response = await api.post(`/members/${target.id}/deactivate`);
      setMembers((current) => (current || []).map((row) => (row.id === response.data.id ? response.data : row)));
      setTarget(null);
      push({ message: "Member deactivated." });
    } catch (err) {
      const normalized = err.normalized || normalizeError(err);
      push({ tone: "error", message: normalized.message });
    }
  }

  const current = MENUS.find((item) => location.pathname === item.to) || MENUS[0];

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
          <h2 className="truncate text-sm font-semibold text-ink">{current.label}</h2>
          <AccountMenu />
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
              members,
              memberError,
              setTarget,
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
      <Dialog
        open={Boolean(target)}
        onOpenChange={(next) => { if (!next) setTarget(null); }}
        title="Deactivate this member?"
        description={target ? `${target.full_name} will not be able to sign in.` : ""}
        footer={(
          <>
            <Button variant="secondary" onClick={() => setTarget(null)}>Keep active</Button>
            <Button variant="danger" onClick={deactivate}>Deactivate</Button>
          </>
        )}
      />
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

function MemberCard({ member, onDeactivate }) {
  return (
    <article className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border bg-white px-4 py-3">
      <div className="min-w-0">
        <p className="text-sm font-medium text-ink">{member.full_name}</p>
        <p className="truncate text-xs text-ink-secondary">{member.email}</p>
      </div>
      <div className="flex items-center gap-2">
        <Badge tone={member.is_active ? "success" : "neutral"}>{member.is_active ? "Active" : "Inactive"}</Badge>
        {onDeactivate ? <Button variant="danger" onClick={() => onDeactivate(member)}>Deactivate</Button> : null}
      </div>
    </article>
  );
}

export function SettingsMembers() {
  const { user, owner, members, memberError, setTarget } = useOutletContext();
  if (!owner) {
    return <p className="w-full max-w-2xl text-sm text-ink-secondary">Only the owner can manage members.</p>;
  }
  const owners = (members || []).filter((member) => member.role === "owner");
  const team = (members || []).filter((member) => member.role !== "owner");
  return (
    <div className="w-full max-w-2xl">
      {memberError ? <ErrorState message={memberError.message} requestId={memberError.requestId} /> : null}
      {!members && !memberError ? <SkeletonRows /> : null}
      {members ? (
        <>
          <h3 className="text-lg font-semibold text-gray-600">Owner</h3>
          <div className="mt-3 flex flex-col gap-2">
            {owners.map((member) => <MemberCard key={member.id} member={member} />)}
          </div>
          <h3 className="mt-8 text-lg font-semibold text-gray-600">Teams</h3>
          <div className="mt-3 flex flex-col gap-2">
            {team.map((member) => (
              <MemberCard
                key={member.id}
                member={member}
                onDeactivate={member.id !== user?.id && member.is_active ? setTarget : null}
              />
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}
