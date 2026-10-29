import clsx from "clsx";

export function Mark({ className }) {
  return (
    <span
      className={clsx(
        "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-mint text-lg font-semibold leading-none text-ink",
        className,
      )}
      aria-hidden="true"
    >
      D
    </span>
  );
}
