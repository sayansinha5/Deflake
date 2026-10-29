import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { Check, X } from "lucide-react";

const ToastContext = createContext(null);

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback((id) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (toast) => {
      const id = crypto.randomUUID();
      setToasts((current) => [...current, { id, tone: "success", ...toast }].slice(-3));
      if (toast.tone !== "error") {
        window.setTimeout(() => dismiss(id), 5000);
      }
    },
    [dismiss],
  );

  const value = useMemo(() => ({ push, dismiss }), [push, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="fixed bottom-5 right-5 z-50 flex w-[min(380px,calc(100%-24px))] flex-col gap-2">
        {toasts.map((toast) => {
          const error = toast.tone === "error";
          return (
            <div
              key={toast.id}
              role="status"
              className={
                error
                  ? "flex items-center gap-3 rounded-md border border-danger/30 bg-surface px-4 py-3 text-body text-ink shadow-panel"
                  : "flex items-center gap-3 rounded-md bg-ink px-4 py-3 text-body text-white shadow-panel"
              }
            >
              <span
                className={
                  error
                    ? "flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-danger-subtle text-danger"
                    : "flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-mint text-ink"
                }
              >
                {error ? <X size={14} strokeWidth={2} aria-hidden="true" /> : <Check size={14} strokeWidth={2.5} aria-hidden="true" />}
              </span>
              <p className="min-w-0 flex-1">{toast.message}</p>
              <button
                type="button"
                className={error ? "rounded-md px-2 py-1 text-meta text-ink-secondary" : "rounded-md bg-white/10 px-3 py-1 text-meta text-white"}
                onClick={() => dismiss(toast.id)}
              >
                Close
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast must be used inside ToastProvider");
  return value;
}
