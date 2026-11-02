import { useEffect, useRef, useState } from "react";
import { Check, Copy, Eye, EyeOff } from "lucide-react";

export const inputClass = "h-10 w-full rounded-md border border-border bg-white px-3 text-sm text-ink transition-colors hover:border-indigo-300 focus:border-indigo-700 focus:hover:border-indigo-500";

export function useCopyText() {
  const [copied, setCopied] = useState(false);
  const timer = useRef(null);

  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);

  async function copyText(value) {
    const text = String(value || "").trim();
    if (!text) return false;
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
    return true;
  }

  return { copied, copyText };
}

export function CopyButton({ value, label = "Copy" }) {
  const { copied, copyText } = useCopyText();
  return (
    <button
      type="button"
      className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${
        copied ? "text-success" : "text-ink-muted hover:bg-ice hover:text-ink"
      }`}
      aria-label={copied ? `${label} copied` : label}
      disabled={!String(value || "").trim()}
      onMouseDown={(event) => event.preventDefault()}
      onClick={() => copyText(value)}
    >
      {copied ? (
        <Check size={16} strokeWidth={1.75} aria-hidden="true" />
      ) : (
        <Copy size={16} strokeWidth={1.75} aria-hidden="true" />
      )}
    </button>
  );
}

export function EmailInput({ id, className = inputClass, value = "", ...props }) {
  const { copied, copyText } = useCopyText();

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
        onClick={() => copyText(value)}
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

export function PasswordInput({
  id,
  reveal,
  onRevealChange,
  showToggle = true,
  ...props
}) {
  const [internalShow, setInternalShow] = useState(false);
  const controlled = typeof reveal === "boolean";
  const show = controlled ? reveal : internalShow;

  function toggle() {
    const next = !show;
    if (controlled) onRevealChange?.(next);
    else setInternalShow(next);
  }

  return (
    <div className="relative">
      <input
        id={id}
        className={`${inputClass} ${showToggle ? "pr-10" : ""}`}
        type={show ? "text" : "password"}
        {...props}
      />
      {showToggle ? (
        <button
          type="button"
          className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-ink-muted hover:text-ink"
          aria-label={show ? "Hide password" : "Show password"}
          aria-pressed={show}
          onMouseDown={(event) => event.preventDefault()}
          onClick={toggle}
        >
          {show ? (
            <EyeOff size={16} strokeWidth={1.75} aria-hidden="true" />
          ) : (
            <Eye size={16} strokeWidth={1.75} aria-hidden="true" />
          )}
        </button>
      ) : null}
    </div>
  );
}
