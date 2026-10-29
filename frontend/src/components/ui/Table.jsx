export function Table({ columns, rows, rowKey, onRow }) {
  return (
    <div className="overflow-x-auto rounded-md border border-border bg-surface shadow-card">
      <table className="w-full border-collapse text-left">
        <thead className="bg-ice/70 text-meta font-medium text-ink-secondary">
          <tr>
            {columns.map((column) => (
              <th key={column.key} className="px-4 py-3 font-medium">
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
          <tbody className="text-table text-ink">
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              tabIndex={onRow ? 0 : undefined}
              className={onRow ? "cursor-pointer border-t border-border hover:bg-ice/40" : "border-t border-border"}
              onClick={onRow ? () => onRow(row) : undefined}
              onKeyDown={
                onRow
                  ? (event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onRow(row);
                      }
                    }
                  : undefined
              }
            >
              {columns.map((column) => (
                <td key={column.key} className="px-4 py-3 align-middle">
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SkeletonRows({ columns = 4, rows = 4 }) {
  return (
    <div className="overflow-hidden rounded-md border border-border bg-surface shadow-card">
      <div className="bg-ice/70 px-4 py-3">
        <div className="h-3 w-40 rounded-md bg-white/80" />
      </div>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="grid gap-3 border-t border-border px-4 py-4" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>
          {Array.from({ length: columns }, (_, cell) => (
            <div key={cell} className="h-3 rounded-md bg-sunken" />
          ))}
        </div>
      ))}
    </div>
  );
}
