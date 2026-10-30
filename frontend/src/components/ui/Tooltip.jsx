import { useRef, useState } from "react";

export function Tooltip({ label, children }) {
  const anchor = useRef(null);
  const [place, setPlace] = useState(null);

  function show() {
    const rect = anchor.current?.getBoundingClientRect();
    if (!rect) return;
    setPlace({ top: rect.top - 6, left: rect.left + rect.width / 2 });
  }

  return (
    <span
      ref={anchor}
      className="inline-flex"
      onMouseEnter={show}
      onMouseLeave={() => setPlace(null)}
      onFocus={show}
      onBlur={() => setPlace(null)}
    >
      {children}
      {place ? (
        <span
          role="tooltip"
          className="pointer-events-none fixed z-50 max-w-sm -translate-x-1/2 -translate-y-full break-words rounded-md border border-border bg-surface px-2 py-1 text-left text-meta text-ink shadow-menu"
          style={{ top: place.top, left: place.left }}
        >
          {typeof label === "string" ? <span className="whitespace-pre-wrap">{label}</span> : label}
        </span>
      ) : null}
    </span>
  );
}
