import { AuthShell } from "./AuthCard";

export function Terms() {
  return (
    <AuthShell title="Terms and Conditions">
      <h1 className="text-3xl font-semibold tracking-tight text-ink">Terms and Conditions</h1>
      <div className="mt-6 flex flex-col gap-4 text-sm leading-6 text-ink-secondary">
        <p>This is a local demo. Scans run only on approved sample repositories.</p>
        <p>Use the workspace accounts provided for the demo. Do not point a scan at a repository you are not allowed to test.</p>
        <p>Results, patches, and logs from a scan are for review inside this workspace.</p>
      </div>
    </AuthShell>
  );
}

export function Privacy() {
  return (
    <AuthShell title="Privacy Policy">
      <h1 className="text-3xl font-semibold tracking-tight text-ink">Privacy Policy</h1>
      <div className="mt-6 flex flex-col gap-4 text-sm leading-6 text-ink-secondary">
        <p>Account, scan, and log data stay in the database on this machine.</p>
        <p>Sign-in uses a session cookie for this site so you can stay signed in.</p>
        <p>This demo does not sell that data or send it to another service from these pages.</p>
      </div>
    </AuthShell>
  );
}
