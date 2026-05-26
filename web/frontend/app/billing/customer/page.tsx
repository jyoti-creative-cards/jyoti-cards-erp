import { JsonTable } from "@/components/JsonTable";
import { apiGet } from "@/lib/api";

export default async function CustomerBillingPage() {
  let rows: Record<string, unknown>[] = [];
  let err: string | null = null;
  try {
    rows = await apiGet<Record<string, unknown>[]>("/api/v1/billing/customer-order-billings");
  } catch (e) {
    err = e instanceof Error ? e.message : "Error";
  }
  if (err) return <p className="text-amber-200">{err}</p>;

  const cols =
    rows[0] != null
      ? Object.keys(rows[0])
          .filter((k) => !k.includes("snap_") && k !== "password_hash")
          .slice(0, 14)
          .map((k) => ({ key: k, label: k }))
      : [];

  return (
    <div>
      <h1 className="text-xl font-semibold">Customer billing (sales PDFs)</h1>
      <div className="mt-4">
        <JsonTable rows={rows} columns={cols} />
      </div>
    </div>
  );
}
