import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Menu as MenuIcon } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../../hooks/useAuth";
import { Badge } from "../ui/Badge";

function initials(name) {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() || "")
    .join("");
}

export function AccountMenu() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    function onPointer(event) {
      if (!menuRef.current?.contains(event.target)) setOpen(false);
    }
    function onKey(event) {
      if (event.key === "Escape") setOpen(false);
    }
    window.addEventListener("pointerdown", onPointer);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onPointer);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function onSignOut() {
    setOpen(false);
    await signOut();
    navigate("/sign-in", { replace: true });
  }

  if (!user) return null;

  const role = user.role === "owner" ? "Owner" : "Member";

  return (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        className="flex h-8 items-center gap-2 rounded-md border border-border bg-white py-0.5 pl-0.5 pr-2 text-sm font-medium text-ink"
        aria-label={`${user.full_name}, account menu`}
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((current) => !current)}
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-accent text-xs font-medium text-white">
          {initials(user.full_name)}
        </span>
        <span className="hidden max-w-[140px] truncate sm:inline">{user.full_name}</span>
        <ChevronDown size={14} strokeWidth={1.75} aria-hidden="true" className="text-ink-secondary" />
      </button>
      {open ? (
        <div role="menu" className="absolute right-0 z-50 mt-2 w-64 rounded-md border border-border bg-surface p-2 shadow-lg">
          <div className="px-2 py-2">
            <p className="font-medium text-ink">{user.full_name}</p>
            <p className="text-sm text-ink-secondary">{user.email}</p>
            <div className="mt-2">
              <Badge tone={user.role === "owner" ? "accent" : "neutral"}>{role}</Badge>
            </div>
          </div>
          <Link
            to="/settings/account"
            role="menuitem"
            className="block rounded-md px-2 py-2 text-sm text-ink hover:bg-ice"
            onClick={() => setOpen(false)}
          >
            Account settings
          </Link>
          <button
            type="button"
            role="menuitem"
            className="block w-full rounded-md px-2 py-2 text-left text-sm text-ink hover:bg-ice"
            onClick={onSignOut}
          >
            Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function TopBar({ title, onMenu, activeRun, tokenFactory = true }) {
  return (
    <header className="z-30 flex h-12 shrink-0 items-center justify-between gap-4 border-b border-border bg-surface px-4 sm:px-6">
      <div className="flex min-w-0 items-center gap-2">
        <button type="button" className="rounded-md p-2 hover:bg-ice md:hidden" onClick={onMenu} aria-label="Open menu">
          <MenuIcon size={18} strokeWidth={1.75} aria-hidden="true" />
        </button>
        {title && typeof title === "object" ? (
          <h1 className="flex min-w-0 items-center gap-1.5 text-section font-semibold tracking-tight text-ink">
            {title.crumbs.map((crumb) => (
              <span key={`${crumb.to}-${crumb.label}`} className="flex shrink-0 items-center gap-1.5">
                <Link
                  to={crumb.to}
                  className="font-medium text-ink-secondary underline decoration-dashed decoration-gray-300 underline-offset-4 hover:text-ink"
                >
                  {crumb.label}
                </Link>
                <ChevronRight size={14} strokeWidth={1.75} className="text-ink-muted" aria-hidden="true" />
              </span>
            ))}
            <span className="truncate">{title.title}</span>
          </h1>
        ) : (
          <h1 className="truncate text-section font-semibold tracking-tight text-ink">{title}</h1>
        )}
      </div>
      <div className="flex min-w-0 items-center gap-3">
        {activeRun ? (
          <Link to={`/runs/${activeRun.id}`} className="hidden items-center gap-2 truncate rounded-md bg-ice px-3 py-1.5 text-meta text-ink sm:inline-flex">
            <span className="h-1.5 w-1.5 shrink-0 rounded-md bg-mint" aria-hidden="true" />
            Scan running · {activeRun.repo_id}
          </Link>
        ) : null}
        {tokenFactory ? null : <Badge tone="warning">Not using Nebius Token Factory</Badge>}
        <AccountMenu />
      </div>
    </header>
  );
}
