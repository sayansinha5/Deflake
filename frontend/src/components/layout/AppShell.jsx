import { useEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";

import { api } from "../../lib/api";
import { ShellProvider } from "./shell";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

function useMinWidth(width) {
  const query = `(min-width: ${width}px)`;
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const onChange = () => setMatches(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

export function AppShell() {
  const desktop = useMinWidth(1024);
  const tablet = useMinWidth(768);
  const [title, setTitle] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [settings, setSettings] = useState(null);
  const [activeRun, setActiveRun] = useState(null);
  const location = useLocation();
  const mainRef = useRef(null);

  useEffect(() => {
    let live = true;
    api.get("/settings").then((response) => {
      if (live) setSettings(response.data);
    }).catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    let live = true;
    async function tick() {
      try {
        const response = await api.get("/runs", { params: { limit: 8 } });
        const found = response.data.items.find((row) => row.status === "queued" || row.status === "running");
        if (live) setActiveRun(found || null);
      } catch {
        if (live) setActiveRun(null);
      }
    }
    tick();
    const timer = window.setInterval(tick, 15000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    setMenuOpen(false);
    if (mainRef.current) mainRef.current.scrollTop = 0;
  }, [location.pathname]);

  const collapsed = tablet && !desktop;
  const settingsPage = location.pathname === "/settings" || location.pathname.startsWith("/settings/");

  return (
    <ShellProvider value={{ setTitle, openMenu: () => setMenuOpen(true) }}>
      <div className="flex h-screen overflow-hidden bg-surface">
        {tablet ? <Sidebar collapsed={collapsed} /> : null}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {settingsPage ? null : (
            <TopBar
              title={title}
              onMenu={() => setMenuOpen(true)}
              activeRun={activeRun}
              tokenFactory={settings ? settings.using_token_factory : true}
            />
          )}
          <main
            ref={mainRef}
            className={settingsPage
              ? "relative min-h-0 flex-1 overflow-hidden"
              : "relative min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6 lg:px-8"}
          >
            <Outlet />
          </main>
        </div>
        {!tablet && menuOpen ? (
          <div className="fixed inset-0 z-40 flex bg-ink/40">
            <Sidebar onNavigate={() => setMenuOpen(false)} />
            <button type="button" className="flex-1" aria-label="Close menu" onClick={() => setMenuOpen(false)} />
          </div>
        ) : null}
      </div>
    </ShellProvider>
  );
}
