import { JsonTable } from "@/components/JsonTable";
import { apiGet } from "@/lib/api";

export default async function JournalsPage() {
  let rows: Record<string, unknown>[] = [];
  let err: string | null = null;
  try {
    rows = await apiGet<Record<string, unknown>[]>("/api/v1/accounting/gl/journals?limit=300");
  } catch (e) {
    err = e instanceof Error ? e.message : "Error";
  }
  if (err) return <p className="text-amber-200">{err}</p>;

  return (
    <div>
      <h1 className="text-xl font-semibold">Journal register</h1>
      <div className="mt-4">
        <JsonTable
          rows={rows}
          columns={[
            { key: "id", label: "ID" },
            { key: "entry_date", label: "Date" },
            { key: "description", label: "Description" },
            { key: "ref_type", label: "Ref type" },
            { key: "ref_id", label: "Ref ID" },
            { key: "total_dr", label: "Total Dr" },
          ]}
        />
      </div>
    </div>
  );
}
