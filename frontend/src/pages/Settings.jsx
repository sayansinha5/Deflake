import { useCallback, useEffect, useState } from "react";
import { Menu as MenuIcon } from "lucide-react";
import { NavLink, Outlet, useLocation, useOutletContext } from "react-router-dom";

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
import { formatMoney } from "../lib/format";

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
  const { view, busy, test } = useOutletContext();
  return (
    <ul className="flex w-full max-w-2xl flex-col gap-2">
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
  );
}

export function SettingsDefaults() {
  const { view } = useOutletContext();
  const defaults = view.defaults;
  return (
    <dl className="grid w-full max-w-2xl gap-3 text-sm text-ink">
      <div><dt className="text-xs text-ink-secondary">Detect reruns</dt><dd>{defaults.detect_reruns}</dd></div>
      <div><dt className="text-xs text-ink-secondary">Verify reruns</dt><dd>{defaults.verify_reruns}</dd></div>
      <div><dt className="text-xs text-ink-secondary">Confidence threshold</dt><dd>{Number(defaults.confidence_threshold).toFixed(2)}</dd></div>
      <div><dt className="text-xs text-ink-secondary">Run budget</dt><dd>{formatMoney(defaults.run_budget_usd)}</dd></div>
      <div><dt className="text-xs text-ink-secondary">Escalation</dt><dd>{defaults.escalation_provider}, then {defaults.escalation_fallback}</dd></div>
      <div><dt className="text-xs text-ink-secondary">Models</dt><dd className="font-mono text-xs">{view.models.fast}</dd></div>
    </dl>
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
