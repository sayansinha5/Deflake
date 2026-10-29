function lineKind(line) {
  const body = line.replace(/^[>E]\s+/, "").trimStart();
  if (body.startsWith("+++") || body.startsWith("---")) return "meta";
  if (body.startsWith("+")) return "add";
  if (body.startsWith("-")) return "remove";
  if (body.startsWith("@@")) return "hunk";
  return "plain";
}

const kinds = {
  add: "bg-success-subtle text-success",
  remove: "bg-danger-subtle text-danger",
  hunk: "text-accent-ink",
  meta: "text-ink-muted",
  plain: "",
};

export function DiffView({ diff }) {
  const lines = String(diff || "").split("\n");
  return (
    <pre className="overflow-auto rounded-md border border-border bg-sunken p-3 font-mono text-xs leading-5 text-ink">
      {lines.map((line, index) => (
        <span key={`${index}-${line.slice(0, 12)}`} className={`block px-2 ${kinds[lineKind(line)]}`}>
          {line || " "}
        </span>
      ))}
    </pre>
  );
}
