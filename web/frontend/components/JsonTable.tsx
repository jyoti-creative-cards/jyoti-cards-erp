export function JsonTable({
  rows,
  columns,
}: {
  rows: Record<string, unknown>[];
  columns: { key: string; label: string }[];
}) {
  if (!rows.length) {
    return <p className="text-sm text-slate-500">No rows.</p>;
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-700">
      <table className="min-w-full text-left text-sm">
        <thead className="border-b border-slate-700 bg-slate-900">
          <tr>
            {columns.map((c) => (
              <th key={c.key} className="px-3 py-2 font-medium text-slate-400">
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-slate-800 hover:bg-slate-900/50">
              {columns.map((c) => (
                <td key={c.key} className="px-3 py-2 text-slate-200">
                  {fmt(row[c.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
