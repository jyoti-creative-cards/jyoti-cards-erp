import { JsonTable } from "@/components/JsonTable";
import { apiGet } from "@/lib/api";

export default async function TrialPage() {
  let rows: Record<string, unknown>[] = [];
  let err: string | null = null;
  try {
    rows = await apiGet<Record<string, unknown>[]>("/api/v1/accounting/gl/trial-balance");
  } catch (e) {
    err = e instanceof Error ? e.message : "Error";
  }
  if (err) return <p className="text-amber-200">{err}</p>;

  return (
    <div>
      <h1 className="text-xl font-semibold">Trial balance</h1>
      <div className="mt-4">
        <JsonTable
          rows={rows}
          columns={[
            { key: "code", label: "Code" },
            { key: "name", label: "Account" },
            { key: "acc_type", label: "Type" },
            { key: "balance_debit", label: "Balance (Dr − Cr)" },
          ]}
        />
      </div>
    </div>
  );
}
