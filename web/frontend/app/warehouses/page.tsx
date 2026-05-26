import { JsonTable } from "@/components/JsonTable";
import { apiGet } from "@/lib/api";

export default async function WarehousesPage() {
  let rows: Record<string, unknown>[] = [];
  let err: string | null = null;
  try {
    rows = await apiGet<Record<string, unknown>[]>("/api/v1/warehouses");
  } catch (e) {
    err = e instanceof Error ? e.message : "Error";
  }
  if (err) return <p className="text-amber-200">{err}</p>;

  return (
    <div>
      <h1 className="text-xl font-semibold">Warehouses</h1>
      <div className="mt-4">
        <JsonTable
          rows={rows}
          columns={[
            { key: "id", label: "ID" },
            { key: "code", label: "Code" },
            { key: "name", label: "Name" },
            { key: "is_default", label: "Default" },
          ]}
        />
      </div>
    </div>
  );
}
