import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { SkeletonRows } from "./components/ui/Table";
import { useAuth } from "./hooks/useAuth";
import { safeNext } from "./lib/api";
import { Calibration } from "./pages/Calibration";
import { CreateAccount } from "./pages/CreateAccount";
import { Escalations } from "./pages/Escalations";
import { FlakeDetail } from "./pages/FlakeDetail";
import { Privacy, Terms } from "./pages/Legal";
import { Overview, Runs } from "./pages/Overview";
import { Repositories } from "./pages/Repositories";
import { RunDetail } from "./pages/RunDetail";
import { Settings, SettingsAccount, SettingsDefaults, SettingsIntegration, SettingsMembers } from "./pages/Settings";
import { SignIn } from "./pages/SignIn";
import { Usage } from "./pages/Usage";

function AuthGate() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <main className="min-h-screen px-6 py-10">
        <SkeletonRows />
      </main>
    );
  }
  if (!user) {
    const next = encodeURIComponent(`${location.pathname}${location.search}`);
    return <Navigate to={`/sign-in?next=${next}`} replace />;
  }
  return <AppShell />;
}

function GuestGate() {
  const { user, loading } = useAuth();
  const params = new URLSearchParams(window.location.search);
  if (loading) {
    return (
      <main className="min-h-screen px-6 py-10">
        <SkeletonRows />
      </main>
    );
  }
  if (user) return <Navigate to={safeNext(params.get("next"))} replace />;
  return <Outlet />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/terms" element={<Terms />} />
      <Route path="/privacy" element={<Privacy />} />
      <Route element={<GuestGate />}>
        <Route path="/sign-in" element={<SignIn />} />
        <Route path="/create-account" element={<CreateAccount />} />
      </Route>
      <Route element={<AuthGate />}>
        <Route path="/" element={<Overview />} />
        <Route path="/repositories" element={<Repositories />} />
        <Route path="/runs" element={<Runs />} />
        <Route path="/runs/:runId" element={<RunDetail />} />
        <Route path="/flakes/:flakeId" element={<FlakeDetail />} />
        <Route path="/escalations" element={<Escalations />} />
        <Route path="/calibration" element={<Calibration />} />
        <Route path="/usage" element={<Usage />} />
        <Route path="/settings" element={<Settings />}>
          <Route index element={<Navigate to="integration" replace />} />
          <Route path="integration" element={<SettingsIntegration />} />
          <Route path="defaults" element={<SettingsDefaults />} />
          <Route path="account" element={<SettingsAccount />} />
          <Route path="members" element={<SettingsMembers />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
