import { JsonTable } from "@/components/JsonTable";
import { apiGet } from "@/lib/api";

export default async function InventoryPage() {
  let rows: Record<string, unknown>[] = [];
  let err: string | null = null;
  try {
    rows = (await apiGet<Record<string, unknown>[]>("/api/v1/inventory/aggregated")) as Record<
      string,
      unknown
    >[];
  } catch (e) {
    err = e instanceof Error ? e.message : "Error";
  }

  if (err) {
    return <p className="text-amber-200">{err}</p>;
  }

  const cols = [
    { key: "product_id", label: "Product ID" },
    { key: "our_product_id", label: "SKU" },
    { key: "name", label: "Name" },
    { key: "vendor_name", label: "Vendor" },
    { key: "on_hand", label: "On hand" },
    { key: "committed_qty", label: "Committed" },
    { key: "stock_status", label: "Status" },
    { key: "latest_sell", label: "Latest sell" },
  ];

  return (
    <div>
      <h1 className="text-xl font-semibold">Inventory (aggregated)</h1>
      <div className="mt-4">
        <JsonTable rows={rows} columns={cols} />
      </div>
    </div>
  );
}
