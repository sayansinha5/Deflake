import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";

export const inputClass = "h-10 w-full rounded-md border border-border bg-white px-3 text-sm text-ink transition-colors hover:border-indigo-300 focus:border-indigo-700 focus:hover:border-indigo-500";

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
