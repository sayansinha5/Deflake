import { useState, useEffect } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Button } from "../components/ui/Button";
import { Dialog } from "../components/ui/Dialog";
import { useAuth } from "../hooks/useAuth";
import { safeNext } from "../lib/api";
import { AuthCard } from "./AuthCard";
import { inputClass, PasswordInput } from "./authFields";

const DEMOS = [
  { label: "Owner", email: "owner@deflake.local", password: "Owner2026" },
  { label: "Judge", email: "judge@deflake.local", password: "Judge2026" },
];

export function SignIn() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [forgot, setForgot] = useState(false);
  const [expired] = useState(() => sessionStorage.getItem("deflake.expired") === "1");

  useEffect(() => {
    sessionStorage.removeItem("deflake.expired");
  }, []);

  async function onSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await signIn(email, password);
      navigate(safeNext(params.get("next")), { replace: true });
    } catch (err) {
      setError(err.message || "Email or password is incorrect.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="Sign in"
      heading="Welcome back"
      subtitle="Continue with your work email."
    >
      {expired ? (
        <p className="mb-4 rounded-md border border-warning bg-warning-subtle px-3 py-2 text-sm text-ink" role="status">
          Your session expired. Sign in to continue.
        </p>
      ) : null}
      <form className="flex flex-col gap-4" onSubmit={onSubmit}>
        <label className="flex flex-col gap-1.5 text-sm text-ink-secondary">
          Email
          <input
            className={inputClass}
            type="email"
            name="email"
            autoComplete="username"
            placeholder="Email address"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1.5 text-sm text-ink-secondary">
          Password
          <PasswordInput
            name="password"
            autoComplete="current-password"
            placeholder="Password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <div className="flex justify-end">
          <button type="button" className="text-sm font-medium text-accent-ink" onClick={() => setForgot(true)}>
            Forgot password?
          </button>
        </div>
        {error ? (
          <p className="text-sm text-danger" role="alert">
            {error}
          </p>
        ) : null}
        <Button type="submit" busy={busy} className="w-full">
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-ink-secondary">
        Need an account? <Link to="/create-account">Create one</Link>
      </p>
      <div className="mt-6 flex items-center gap-3">
        <span className="h-px flex-1 bg-border" />
        <span className="text-xs font-medium text-ink-muted">OR DEMO LOGIN</span>
        <span className="h-px flex-1 bg-border" />
      </div>
      <div className="mt-4 flex gap-2">
        {DEMOS.map((account) => (
          <Button
            key={account.label}
            variant="secondary"
            className="flex-1"
            onClick={() => {
              setEmail(account.email);
              setPassword(account.password);
              setError("");
            }}
          >
            {account.label}
          </Button>
        ))}
      </div>
      <Dialog
        open={forgot}
        onOpenChange={setForgot}
        title="Reset your password"
        description="Password reset by email isn't available in this demo. Ask the workspace owner to reset it."
        footer={
          <Button variant="secondary" onClick={() => setForgot(false)}>
            Close
          </Button>
        }
      />
    </AuthCard>
  );
}
