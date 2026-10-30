import { ChartColumn, FolderGit2, Gauge, List, Scale, Settings, Users } from "lucide-react";
import { NavLink } from "react-router-dom";
import clsx from "clsx";

import { appEnv, appName } from "../../lib/config";
import { Mark } from "./Mark";

const GROUPS = [
  {
    label: "Workspace",
    items: [
      { to: "/", label: "Overview", icon: Gauge, end: true },
      { to: "/repositories", label: "Repositories", icon: FolderGit2 },
      { to: "/runs", label: "Runs", icon: List },
    ],
  },
  {
    label: "Review",
    items: [
      { to: "/escalations", label: "Escalations", icon: Users },
      { to: "/calibration", label: "Calibration", icon: Scale },
      { to: "/usage", label: "Usage", icon: ChartColumn },
    ],
  },
  {
    label: "Account",
    items: [{ to: "/settings", label: "Settings", icon: Settings }],
  },
];

export function Sidebar({ collapsed, onNavigate, className }) {
  return (
    <aside
      className={clsx(
        "flex h-full min-h-0 shrink-0 flex-col overflow-hidden bg-ink text-white",
        collapsed ? "w-[76px]" : "w-[248px]",
        className,
      )}
    >
      <div className={clsx("flex h-12 shrink-0 items-center gap-3 border-b border-white/15 px-4", collapsed && "justify-center px-0")}>
        <Mark />
        {collapsed ? <span className="sr-only">{appName}</span> : <span className="text-lg font-semibold">{appName}</span>}
      </div>
      <nav className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-3 py-4" aria-label="Primary">
        {GROUPS.map((group) => (
          <div key={group.label} className="flex flex-col gap-1">
            {collapsed ? null : (
              <p className="px-3 pb-1 text-meta text-white/45">{group.label}</p>
            )}
            {group.items.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  title={item.label}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    clsx(
                      "flex h-10 items-center gap-3 rounded-md px-3 text-body font-medium",
                      collapsed && "justify-center px-0",
                      isActive ? "bg-white/10 text-white hover:bg-white/10 hover:text-white" : "text-white/70 hover:bg-white/5 hover:text-white",
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      <Icon
                        size={18}
                        strokeWidth={1.75}
                        aria-hidden="true"
                        className={isActive ? "text-mint" : "text-current"}
                      />
                      {collapsed ? <span className="sr-only">{item.label}</span> : item.label}
                    </>
                  )}
                </NavLink>
              );
            })}
          </div>
        ))}
      </nav>
    </aside>
  );
}
