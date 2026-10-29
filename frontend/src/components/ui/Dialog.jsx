import { useEffect, useId } from "react";
import clsx from "clsx";

export function Dialog({ open, onOpenChange, title, description, children, footer, wide = false }) {
  const titleId = useId();

  useEffect(() => {
    if (!open) return undefined;
    function onKey(event) {
      if (event.key === "Escape") onOpenChange(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button type="button" className="absolute inset-0 bg-ink/40" aria-label="Close" onClick={() => onOpenChange(false)} />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={clsx(
          "relative z-10 w-full rounded-md border border-border bg-surface p-6 shadow-panel",
          wide ? "max-w-[720px]" : "max-w-[480px]",
        )}
      >
        <h2 id={titleId} className="text-section font-semibold text-ink">{title}</h2>
        {description ? <p className="mt-1 text-body text-ink-secondary">{description}</p> : null}
        <div className="mt-4">{children}</div>
        {footer ? <div className="mt-6 flex justify-end gap-2">{footer}</div> : null}
      </div>
    </div>
  );
}
