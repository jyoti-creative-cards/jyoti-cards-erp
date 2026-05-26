import { JsonTable } from "@/components/JsonTable";
import { apiGet } from "@/lib/api";

export default async function ArPage() {
  let rows: Record<string, unknown>[] = [];
  let err: string | null = null;
  try {
    rows = await apiGet<Record<string, unknown>[]>("/api/v1/accounting/ar/ledger");
  } catch (e) {
    err = e instanceof Error ? e.message : "Error";
  }
  if (err) return <p className="text-amber-200">{err}</p>;

  const cols =
    rows[0] != null
      ? Object.keys(rows[0]).map((k) => ({ key: k, label: k }))
      : [];

  return (
    <div>
      <h1 className="text-xl font-semibold">Accounts receivable (AR)</h1>
      <p className="mt-1 text-sm text-slate-400">
        Same ledger as Streamlit → Accounts → AR.
      </p>
      <div className="mt-4">
        <JsonTable rows={rows} columns={cols} />
      </div>
    </div>
  );
}
