import { useEffect } from "react";
import { Link } from "react-router-dom";

import { Mark } from "../components/layout/Mark";
import { appName } from "../lib/config";

const SEGMENTS = ["#3ECF8E", "#4C8DFF", "#7C5CFF", "#F06292", "#F5A524", "#2EC4B6", "#E06C9F"];

const SAMPLE = [
  { name: "test_batch_codes_are_unique", category: "Randomness", rate: "20.0%", confidence: "0.80", confidenceClass: "text-success", color: "#3ECF8E" },
  { name: "test_concurrent_reservations", category: "Async race", rate: "15.0%", confidence: "0.90", confidenceClass: "text-success", color: "#7C5CFF" },
];

const FEATURES = [
  { title: "Detect", body: "Reruns that fail only sometimes stay in the scan. Tests that fail every time are set aside." },
  { title: "Diagnose", body: "Each flake is named: order, time, randomness, or a race, with the polluter when there is one." },
  { title: "Verify", body: "A patch is checked in the same scan. What a patch cannot fix is sent on for a person." },
];

function AuthShowcase() {
  return (
    <section className="hidden h-screen min-h-0 w-1/2 flex-col overflow-y-auto border-l border-border bg-canvas lg:flex" aria-label="Product sample">
      <div className="m-auto w-full max-w-xl px-10 py-10">
        <p className="text-sm font-medium text-accent-ink">Repository Scan Run</p>
        <h2 className="mt-2 text-3xl font-semibold tracking-tight text-ink">Flakes, named and checked.</h2>
        <p className="mt-2 text-sm leading-6 text-ink-secondary">
          Deflake reruns the suite, separates flakes from broken tests, and checks a fix before anyone reviews it.
        </p>

        <article className="mt-8 rounded-xl border border-border bg-white p-5 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs text-ink-muted">Repository</p>
              <h3 className="text-lg font-semibold text-ink">flaky-shop</h3>
            </div>
            <span className="rounded-md bg-success-subtle px-2 py-1 text-xs font-medium text-success">Completed</span>
          </div>
          <div className="mt-5 flex items-end justify-between gap-4">
            <div>
              <p className="text-4xl font-semibold leading-none tracking-tight text-ink">7</p>
              <p className="mt-2 text-sm text-ink-secondary">flaky tests</p>
            </div>
            <p className="text-sm text-ink-secondary">1 broken, not flaky</p>
          </div>
          <div className="mt-4 flex h-2.5 overflow-hidden rounded-full bg-sunken" aria-hidden="true">
            {SEGMENTS.map((color) => (
              <div key={color} className="h-full flex-1" style={{ backgroundColor: color }} />
            ))}
          </div>

          <h3 className="mt-10 text-lg font-semibold text-ink">Flakes</h3>
          <div className="mt-2 grid grid-cols-2 gap-3">
            {SAMPLE.map((flake) => (
              <div key={flake.name} className="rounded-md border border-border px-3 py-3">
                <p className="flex items-center gap-2 text-sm font-medium text-ink">
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: flake.color }} aria-hidden="true" />
                  <span className="truncate">{flake.name}</span>
                </p>
                <p className="mt-1 truncate text-xs text-ink-secondary">{flake.category}</p>
                <p className="mt-3 text-xl font-semibold leading-none text-ink">{flake.rate}</p>
                <p className={`mt-1 text-xs ${flake.confidenceClass}`}>{flake.confidence} confidence</p>
              </div>
            ))}
          </div>
        </article>

        <div className="mt-3 grid grid-cols-3 gap-3">
          {FEATURES.map((feature) => (
            <article key={feature.title} className="rounded-xl border border-border bg-white p-3 shadow-sm">
              <h3 className="text-sm font-semibold text-ink">{feature.title}</h3>
              <p className="mt-1 text-xs leading-5 text-ink-secondary">{feature.body}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

export function AuthShell({ title, children }) {
  useEffect(() => {
    document.title = `${title} · ${appName}`;
  }, [title]);

  return (
    <div className="flex min-h-screen bg-white">
      <main className="flex h-screen min-h-0 w-full flex-col lg:w-1/2 lg:shrink-0">
        <header className="flex shrink-0 items-center gap-3 px-8 pt-4">
          <Mark />
          <p className="text-lg font-semibold text-ink">{appName}</p>
        </header>
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <div className="m-auto w-full max-w-sm px-6 py-10 sm:px-8">
            {children}
          </div>
        </div>
        <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-border px-8 py-4">
          <p className="text-xs text-ink-muted">© {appName} {new Date().getFullYear()}</p>
          <nav className="flex flex-wrap items-center gap-2 text-xs" aria-label="Legal">
            <Link to="/terms">Terms and Conditions</Link>
            <span className="text-ink-muted" aria-hidden="true">·</span>
            <Link to="/privacy">Privacy Policy</Link>
          </nav>
        </footer>
      </main>
      <AuthShowcase />
    </div>
  );
}

export function AuthCard({ title, heading, subtitle, children }) {
  return (
    <AuthShell title={title}>
      <h1 className="text-2xl font-bold tracking-tight text-ink">{heading}</h1>
      {subtitle ? <p className="mt-2 text-sm leading-6 text-ink-secondary">{subtitle}</p> : null}
      <div className="mt-8">{children}</div>
    </AuthShell>
  );
}
