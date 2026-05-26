import { JsonTable } from "@/components/JsonTable";
import { apiGet } from "@/lib/api";

export default async function PurchaseOrdersPage() {
  let rows: Record<string, unknown>[] = [];
  let err: string | null = null;
  try {
    rows = (await apiGet<Record<string, unknown>[]>("/api/v1/purchase-orders")) as Record<
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
      <h1 className="text-xl font-semibold">Purchase orders</h1>
      <div className="mt-4">
        <JsonTable
          rows={rows}
          columns={[
            { key: "id", label: "ID" },
            { key: "vendor_id", label: "Vendor" },
            { key: "product_id", label: "Product" },
            { key: "quantity", label: "Qty" },
            { key: "unit_cost", label: "Unit cost" },
            { key: "status", label: "Status" },
          ]}
        />
      </div>
    </div>
  );
}
