import { JsonTable } from "@/components/JsonTable";
import { apiGet } from "@/lib/api";

export default async function VendorsPage() {
  let rows: Record<string, unknown>[] = [];
  let err: string | null = null;
  try {
    rows = (await apiGet<Record<string, unknown>[]>("/api/v1/vendors")) as Record<
      string,
      unknown
    >[];
  } catch (e) {
    err = e instanceof Error ? e.message : "Error";
  }

  if (err) {
    return <p className="text-amber-200">{err}</p>;
  }

  return (
    <div>
      <h1 className="text-xl font-semibold">Vendors</h1>
      <div className="mt-4">
        <JsonTable
          rows={rows}
          columns={[
            { key: "id", label: "ID" },
            { key: "person_name", label: "Person" },
            { key: "company_name", label: "Company" },
            { key: "primary_phone", label: "Phone" },
          ]}
        />
      </div>
    </div>
  );
}
