import { JsonTable } from "@/components/JsonTable";
import { apiGet } from "@/lib/api";

export default async function StockReceiptsPage() {
  let rows: Record<string, unknown>[] = [];
  let err: string | null = null;
  try {
    rows = (await apiGet<Record<string, unknown>[]>("/api/v1/stock-receipts")) as Record<
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
      <h1 className="text-xl font-semibold">Stock receipts</h1>
      <div className="mt-4">
        <JsonTable
          rows={rows}
          columns={[
            { key: "id", label: "ID" },
            { key: "product_id", label: "Product" },
            { key: "po_id", label: "PO" },
            { key: "quantity", label: "Qty" },
            { key: "selling_price", label: "Selling" },
          ]}
        />
      </div>
    </div>
  );
}
