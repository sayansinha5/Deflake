import clsx from "clsx";

const tones = {
  primary: "border-transparent bg-mint text-ink hover:brightness-95",
  secondary: "border-border bg-white text-ink hover:bg-ice",
  danger: "border-danger/20 bg-danger-subtle text-danger hover:bg-danger hover:text-white",
};

export function Button({
  variant = "primary",
  type = "button",
  busy = false,
  className,
  children,
  disabled,
  ...props
}) {
  return (
    <button
      type={type}
      disabled={disabled || busy}
      className={clsx(
        "inline-flex h-10 items-center justify-center gap-2 rounded-md border px-4 text-body font-medium",
        "disabled:cursor-not-allowed disabled:border-border disabled:bg-sunken disabled:text-ink-muted disabled:hover:brightness-100",
        tones[variant],
        className,
      )}
      {...props}
    >
      {busy ? <span className="inline-block h-3 w-3 animate-spin rounded-md border-2 border-current border-r-transparent" /> : null}
      {children}
    </button>
  );
}
