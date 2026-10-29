import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Button } from "../components/ui/Button";
import { useAuth } from "../hooks/useAuth";
import { appName } from "../lib/config";
import { firstName } from "../lib/format";
import { AuthCard } from "./AuthCard";
import { inputClass, PasswordInput } from "./authFields";

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function CreateAccount() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [touched, setTouched] = useState({});
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const problems = {
    full_name: fullName.trim() ? "" : "Enter your name.",
    email: EMAIL.test(email) ? "" : "Enter a work email.",
    password: password.length >= 8 ? "" : "At least 8 characters.",
  };
  const valid = Object.values(problems).every((problem) => problem === "");
  const closed = error?.code === "signup_closed";

  function blur(field) {
    setTouched((current) => ({ ...current, [field]: true }));
  }

  async function onSubmit(event) {
    event.preventDefault();
    setTouched({ full_name: true, email: true, password: true });
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      const user = await register({
        full_name: fullName.trim(),
        email,
        password,
      });
      const name = firstName(user.full_name);
      navigate("/", {
        replace: true,
        state: { toast: name ? `Welcome to ${appName}, ${name}.` : `Welcome to ${appName}.` },
      });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="Create account"
      heading="Create  account"
      subtitle={`Join ${appName} and start a scan.`}
    >
      {closed ? (
        <p className="text-sm text-ink">{error.message}</p>
      ) : (
        <form className="flex flex-col gap-4" onSubmit={onSubmit}>
          <Field id="full-name" label="Full name" error={touched.full_name ? problems.full_name : ""}>
            <input
              id="full-name"
              className={inputClass}
              name="name"
              autoComplete="name"
              value={fullName}
              onBlur={() => blur("full_name")}
              onChange={(event) => setFullName(event.target.value)}
            />
          </Field>
          <Field id="email" label="Work email" error={touched.email ? problems.email : ""}>
            <input
              id="email"
              className={inputClass}
              type="email"
              name="email"
              autoComplete="email"
              value={email}
              onBlur={() => blur("email")}
              onChange={(event) => setEmail(event.target.value)}
            />
          </Field>
          <Field id="password" label="Password" hint="At least 8 characters." error={touched.password ? problems.password : ""}>
            <PasswordInput
              id="password"
              name="password"
              autoComplete="new-password"
              value={password}
              onBlur={() => blur("password")}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>
          {error ? (
            <p className="text-sm text-danger" role="alert">
              {error.message}
            </p>
          ) : null}
          <Button type="submit" busy={busy} disabled={!valid} className="w-full">
            {busy ? "Creating…" : "Create account"}
          </Button>
        </form>
      )}
      <p className="mt-6 text-center text-sm text-ink-secondary">
        Already have an account? <Link to="/sign-in">Sign in</Link>
      </p>
    </AuthCard>
  );
}

function Field({ id, label, hint, error, children }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm text-ink-secondary">
        {label}
      </label>
      {children}
      {hint && !error ? <span className="text-xs text-ink-muted">{hint}</span> : null}
      {error ? <span className="text-xs text-danger">{error}</span> : null}
    </div>
  );
}
