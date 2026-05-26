import { apiGet } from "@/lib/api";

type Stats = {
  n_customers?: number;
  n_vendors?: number;
  n_products?: number;
  n_purchase_orders?: number;
  n_customer_orders?: number;
  pipeline_sales_revenue?: number;
  n_sku_low_stock?: number;
  n_sku_out_of_stock?: number;
};

function Tile({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/80 p-4">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-white">{value}</div>
    </div>
  );
}

export default async function DashboardPage() {
  let stats: Stats | null = null;
  let err: string | null = null;
  try {
    stats = await apiGet<Stats>("/api/v1/dashboard/stats");
  } catch (e) {
    err = e instanceof Error ? e.message : "Failed to load";
  }

  if (err) {
    return (
      <div>
        <h1 className="text-xl font-semibold text-white">Dashboard</h1>
        <p className="mt-4 rounded border border-amber-700/50 bg-amber-950/40 p-4 text-amber-100">
          API error: {err}
          <span className="mt-2 block text-sm text-amber-200/80">
            Set NEXT_PUBLIC_API_URL and run FastAPI with DATABASE_URL.
          </span>
        </p>
      </div>
    );
  }

  const s = stats ?? {};
  return (
    <div>
      <h1 className="text-xl font-semibold text-white">Dashboard</h1>
      <p className="mt-1 text-sm text-slate-400">Same stats as Streamlit home.</p>
      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Tile label="Customers" value={s.n_customers ?? "—"} />
        <Tile label="Vendors" value={s.n_vendors ?? "—"} />
        <Tile label="Products" value={s.n_products ?? "—"} />
        <Tile label="Purchase orders" value={s.n_purchase_orders ?? "—"} />
        <Tile label="Customer orders" value={s.n_customer_orders ?? "—"} />
        <Tile
          label="Pipeline revenue"
          value={
            s.pipeline_sales_revenue != null
              ? `₹${s.pipeline_sales_revenue.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`
              : "—"
          }
        />
        <Tile label="SKU low stock" value={s.n_sku_low_stock ?? "—"} />
        <Tile label="SKU out of stock" value={s.n_sku_out_of_stock ?? "—"} />
      </div>
    </div>
  );
}
