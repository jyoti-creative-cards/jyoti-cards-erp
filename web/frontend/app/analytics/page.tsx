import { JsonTable } from "@/components/JsonTable";
import { apiGet } from "@/lib/api";

function rangeFromSearch(sp: { start?: string; end?: string }) {
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - 30);
  const defStart = start.toISOString().slice(0, 10);
  const defEnd = end.toISOString().slice(0, 10);
  const re = /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/;
  return {
    start: sp.start && re.test(sp.start) ? sp.start : defStart,
    end: sp.end && re.test(sp.end) ? sp.end : defEnd,
  };
}

export default async function AnalyticsPage({
  searchParams,
}: {
  searchParams: Promise<{ start?: string; end?: string }>;
}) {
  const sp = await searchParams;
  const { start, end } = rangeFromSearch(sp);
  const q = `start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;

  let series: Record<string, unknown>[] = [];
  let cats: Record<string, unknown>[] = [];
  let prods: Record<string, unknown>[] = [];
  let err: string | null = null;
  try {
    [series, cats, prods] = await Promise.all([
      apiGet<Record<string, unknown>[]>(`/api/v1/analytics/sales-revenue-series?${q}&grain=day`),
      apiGet<Record<string, unknown>[]>(`/api/v1/analytics/top-categories?${q}&n=10`),
      apiGet<Record<string, unknown>[]>(`/api/v1/analytics/top-products?${q}&n=10`),
    ]);
  } catch (e) {
    err = e instanceof Error ? e.message : "Error";
  }
  if (err) return <p className="text-amber-200">{err}</p>;

  return (
    <div>
      <h1 className="text-xl font-semibold">Sales analytics</h1>
      <p className="mt-1 text-sm text-slate-400">
        Range <code className="rounded bg-slate-800 px-1">{start}</code> →{" "}
        <code className="rounded bg-slate-800 px-1">{end}</code>. Use{" "}
        <code className="rounded bg-slate-800 px-1">?start=&amp;end=</code> (YYYY-MM-DD).
      </p>

      <h2 className="mt-8 text-lg font-medium text-slate-200">Revenue by day</h2>
      <div className="mt-2">
        <JsonTable
          rows={series}
          columns={[
            { key: "period", label: "Period" },
            { key: "revenue", label: "Revenue" },
          ]}
        />
      </div>

      <h2 className="mt-8 text-lg font-medium text-slate-200">Top categories</h2>
      <div className="mt-2">
        <JsonTable
          rows={cats}
          columns={[
            { key: "category", label: "Category" },
            { key: "revenue", label: "Revenue" },
          ]}
        />
      </div>

      <h2 className="mt-8 text-lg font-medium text-slate-200">Top products</h2>
      <div className="mt-2">
        <JsonTable
          rows={prods}
          columns={[
            { key: "label", label: "Product" },
            { key: "revenue", label: "Revenue" },
          ]}
        />
      </div>
    </div>
  );
}
