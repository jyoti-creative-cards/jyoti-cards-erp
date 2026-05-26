import { JsonTable } from "@/components/JsonTable";
import { apiGet } from "@/lib/api";

export default async function DocsVbPage() {
  let rows: Record<string, unknown>[] = [];
  let err: string | null = null;
  try {
    rows = await apiGet<Record<string, unknown>[]>("/api/v1/documents/vendor-bills");
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
      <h1 className="text-xl font-semibold">Vendor bills</h1>
      <div className="mt-4">
        <JsonTable rows={rows} columns={cols} />
      </div>
    </div>
  );
}
