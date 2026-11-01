import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Button } from "../components/ui/Button";
import { useAuth } from "../hooks/useAuth";
import { api } from "../lib/api";
import { appName } from "../lib/config";
import { firstName as firstNameOf } from "../lib/format";
import { AuthCard } from "./AuthCard";
import { EmailInput, inputClass, PasswordInput } from "./authFields";

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function composeFullName(first, last) {
  return [first, last].map((part) => (part || "").trim()).filter(Boolean).join(" ");
}

export function CreateAccount() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const inviteToken = params.get("invite") || "";

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [touched, setTouched] = useState({});
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [invite, setInvite] = useState(null);
  const [inviteLoading, setInviteLoading] = useState(Boolean(inviteToken));
  const [inviteError, setInviteError] = useState("");

  const invited = Boolean(inviteToken);
  const locked = invited && invite && invite.status === "pending";

  useEffect(() => {
    if (!inviteToken) return undefined;
    let live = true;
    setInviteLoading(true);
    api
      .get(`/invites/${encodeURIComponent(inviteToken)}`)
      .then((response) => {
        if (!live) return;
        setInvite(response.data);
        setFirstName(response.data.first_name || "");
        setLastName(response.data.last_name || "");
        setEmail(response.data.email || "");
        if (response.data.status !== "pending") {
          setInviteError("This invitation is no longer valid.");
        }
      })
      .catch((err) => {
        if (!live) return;
        setInviteError(err.message || "Invitation not found.");
      })
      .finally(() => {
        if (live) setInviteLoading(false);
      });
    return () => {
      live = false;
    };
  }, [inviteToken]);

  const problems = useMemo(() => ({
    first_name: firstName.trim() || locked ? "" : "Enter your first name.",
    email: EMAIL.test(email) ? "" : "Enter a work email.",
    password: password.length >= 8 ? "" : "At least 8 characters.",
  }), [firstName, email, password, locked]);
  const valid = Object.values(problems).every((problem) => problem === "");
  const closed = error?.code === "signup_closed";

  function blur(field) {
    setTouched((current) => ({ ...current, [field]: true }));
  }

  async function onSubmit(event) {
    event.preventDefault();
    setTouched({ first_name: true, email: true, password: true });
    if (!valid) return;
    if (invited && !locked) return;
    setBusy(true);
    setError(null);
    try {
      const fullName = invited && invite
        ? invite.full_name
        : composeFullName(firstName, lastName);
      const user = await register({
        full_name: fullName,
        email,
        password,
        ...(inviteToken ? { invite_token: inviteToken } : {}),
      });
      const name = firstNameOf(user.full_name);
      if (user.needs_onboarding) {
        navigate("/onboarding", {
          replace: true,
          state: { toast: name ? `Welcome to ${appName}, ${name}.` : `Welcome to ${appName}.` },
        });
      } else {
        navigate("/", {
          replace: true,
          state: {
            toast: invite
              ? `Welcome to ${invite.workspace_name}.`
              : name
                ? `Welcome to ${appName}, ${name}.`
                : `Welcome to ${appName}.`,
          },
        });
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const disabledInput = `${inputClass} bg-sunken text-ink-secondary`;

  return (
    <AuthCard
      title="Create account"
      heading={invited ? "Accept invitation" : "Create account"}
      subtitle={
        invited && invite
          ? `Join ${invite.workspace_name} on ${appName}.`
          : `Join ${appName} and create your workspace.`
      }
    >
      {inviteLoading ? (
        <p className="text-sm text-ink-secondary">Loading invitation…</p>
      ) : inviteError ? (
        <p className="text-sm text-danger" role="alert">{inviteError}</p>
      ) : closed ? (
        <p className="text-sm text-ink">{error.message}</p>
      ) : (
        <form className="flex flex-col gap-4" onSubmit={onSubmit}>
          {error ? (
            <p className="text-center text-sm text-danger" role="alert">
              {error.message}
            </p>
          ) : null}
          {invited && invite ? (
            <div className="rounded-md border border-border bg-ice px-3 py-2 text-sm text-ink-secondary">
              Invited to <span className="font-medium text-ink">{invite.workspace_name}</span>
            </div>
          ) : null}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              id="first-name"
              label="First name"
              required={!locked}
              error={touched.first_name ? problems.first_name : ""}
            >
              <input
                id="first-name"
                className={locked ? disabledInput : inputClass}
                name="given-name"
                autoComplete="given-name"
                value={firstName}
                readOnly={locked}
                disabled={locked}
                onBlur={() => blur("first_name")}
                onChange={(event) => setFirstName(event.target.value)}
              />
            </Field>
            <Field id="last-name" label="Last name">
              <input
                id="last-name"
                className={locked ? disabledInput : inputClass}
                name="family-name"
                autoComplete="family-name"
                value={lastName}
                readOnly={locked}
                disabled={locked}
                onChange={(event) => setLastName(event.target.value)}
              />
            </Field>
          </div>
          <Field id="email" label="Work email" required error={touched.email ? problems.email : ""}>
            <EmailInput
              id="email"
              className={locked ? disabledInput : inputClass}
              name="email"
              autoComplete="email"
              value={email}
              readOnly={locked}
              disabled={locked}
              onBlur={() => blur("email")}
              onChange={(event) => setEmail(event.target.value)}
            />
          </Field>
          <Field
            id="password"
            label="Password"
            required
            hint="At least 8 characters."
            error={touched.password ? problems.password : ""}
          >
            <PasswordInput
              id="password"
              name="password"
              autoComplete="new-password"
              value={password}
              onBlur={() => blur("password")}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>
          <div className="border-y border-dashed border-gray-300 py-2">
            <p className="text-center text-sm leading-7 text-gray-500 break-normal md:break-all">
              By creating an account, you agree to our
            </p>
            <div className="text-center text-sm leading-7 text-gray-500 break-normal md:break-all">
                    <Link to="/terms">Terms & Conditions</Link>
                    {"  "}and{"  "}
                    <Link to="/privacy">Privacy Policy</Link>.
            </div>
          </div>
          <Button type="submit" busy={busy} disabled={!valid || (invited && !locked)} className="w-full">
            {busy ? "Creating…" : invited ? "Join workspace" : "Create account"}
          </Button>
        </form>
      )}
      <p className="mt-6 text-center text-sm text-ink-secondary">
        Already have an account?{" "}
        <Link to={inviteToken ? `/sign-in?invite=${encodeURIComponent(inviteToken)}` : "/sign-in"}>
          Sign in
        </Link>
      </p>
    </AuthCard>
  );
}

function Field({ id, label, hint, error, required = false, children }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="inline-flex items-center space-x-2 text-sm text-ink-secondary">
        <span>{label}</span>
        {required ? <span className="text-danger" aria-hidden="true">*</span> : null}
      </label>
      {children}
      {hint && !error ? <span className="text-xs text-ink-muted">{hint}</span> : null}
      {error ? <span className="text-xs text-danger">{error}</span> : null}
    </div>
  );
}
