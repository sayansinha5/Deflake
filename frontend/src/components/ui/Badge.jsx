import clsx from "clsx";

const tones = {
  success: "bg-success-subtle text-success",
  danger: "bg-danger-subtle text-danger",
  warning: "bg-warning-subtle text-warning",
  neutral: "bg-sunken text-ink-secondary",
  accent: "bg-ice text-accent-ink",
};

export function Badge({ tone = "neutral", children }) {
  return (
    <span className={clsx("inline-flex items-center rounded-md px-2 py-0.5 text-meta font-medium", tones[tone])}>
      {children}
    </span>
  );
}
