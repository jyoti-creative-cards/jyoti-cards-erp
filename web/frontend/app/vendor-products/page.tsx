import { JsonTable } from "@/components/JsonTable";
import { apiGet } from "@/lib/api";

export default async function VendorProductsPage() {
  let rows: Record<string, unknown>[] = [];
  let err: string | null = null;
  try {
    rows = (await apiGet<Record<string, unknown>[]>("/api/v1/vendor-products")) as Record<
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
      <h1 className="text-xl font-semibold">Vendor products</h1>
      <div className="mt-4">
        <JsonTable
          rows={rows}
          columns={[
            { key: "id", label: "ID" },
            { key: "vendor_id", label: "Vendor" },
            { key: "our_product_id", label: "SKU" },
            { key: "name", label: "Name" },
            { key: "category", label: "Category" },
          ]}
        />
      </div>
    </div>
  );
}
