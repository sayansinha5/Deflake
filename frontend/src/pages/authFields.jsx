import { useEffect, useRef, useState } from "react";
import { Check, Copy, Eye, EyeOff } from "lucide-react";

export const inputClass = "h-10 w-full rounded-md border border-border bg-white px-3 text-sm text-ink transition-colors hover:border-indigo-300 focus:border-indigo-700 focus:hover:border-indigo-500";

export function EmailInput({ id, className = inputClass, value = "", ...props }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef(null);

  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);

  async function copyEmail() {
    const text = String(value || "").trim();
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "absolute";
      area.style.left = "-9999px";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      document.body.removeChild(area);
    }
    setCopied(true);
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="relative">
      <input
        id={id}
        className={`${className} pr-10`}
        type="email"
        value={value}
        {...props}
      />
      <button
        type="button"
        className={`absolute inset-y-0 right-0 flex w-10 items-center justify-center ${
          copied ? "text-success" : "text-ink-muted hover:text-ink"
        }`}
        aria-label={copied ? "Email copied" : "Copy email"}
        disabled={!String(value || "").trim()}
        onMouseDown={(event) => event.preventDefault()}
        onClick={copyEmail}
      >
        {copied ? (
          <Check size={16} strokeWidth={1.75} aria-hidden="true" />
        ) : (
          <Copy size={16} strokeWidth={1.75} aria-hidden="true" />
        )}
      </button>
    </div>
  );
}

export function PasswordInput({ id, ...props }) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <input
        id={id}
        className={`${inputClass} pr-10`}
        type={show ? "text" : "password"}
        {...props}
      />
      <button
        type="button"
        className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-ink-muted hover:text-ink"
        aria-label={show ? "Hide password" : "Show password"}
        aria-pressed={show}
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => setShow((value) => !value)}
      >
        {show ? <EyeOff size={16} strokeWidth={1.75} aria-hidden="true" /> : <Eye size={16} strokeWidth={1.75} aria-hidden="true" />}
      </button>
    </div>
  );
}
