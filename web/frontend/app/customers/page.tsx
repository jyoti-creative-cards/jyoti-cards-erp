import { JsonTable } from "@/components/JsonTable";
import { apiGet } from "@/lib/api";

export default async function CustomersPage() {
  let rows: Record<string, unknown>[] = [];
  let err: string | null = null;
  try {
    rows = (await apiGet<Record<string, unknown>[]>("/api/v1/customers")) as Record<
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
      <h1 className="text-xl font-semibold">Customers</h1>
      <div className="mt-4">
        <JsonTable
          rows={rows}
          columns={[
            { key: "id", label: "ID" },
            { key: "name", label: "Name" },
            { key: "company_name", label: "Company" },
            { key: "phone", label: "Phone" },
          ]}
        />
      </div>
    </div>
  );
}
