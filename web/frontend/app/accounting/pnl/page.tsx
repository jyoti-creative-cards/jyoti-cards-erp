import { apiGet } from "@/lib/api";

type Pnl = { revenue: number; expense: number; net_income: number };

export default async function PnlPage({
  searchParams,
}: {
  searchParams: Promise<{ through?: string }>;
}) {
  const sp = await searchParams;
  const through =
    (sp.through && /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(sp.through)
      ? sp.through
      : undefined) || new Date().toISOString().slice(0, 10);

  let data: Pnl | null = null;
  let err: string | null = null;
  try {
    data = await apiGet<Pnl>(
      `/api/v1/accounting/gl/pnl?through=${encodeURIComponent(through)}`,
    );
  } catch (e) {
    err = e instanceof Error ? e.message : "Error";
  }
  if (err) return <p className="text-amber-200">{err}</p>;

  return (
    <div>
      <h1 className="text-xl font-semibold">P&amp;L (GL revenue &amp; expense)</h1>
      <p className="mt-1 text-sm text-slate-400">
        Through date:{" "}
        <code className="rounded bg-slate-800 px-1">{through}</code> — add{" "}
        <code className="rounded bg-slate-800 px-1">?through=YYYY-MM-DD</code>{" "}
        to URL.
      </p>
      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <div className="rounded-lg border border-slate-700 bg-slate-900/80 p-4">
          <div className="text-xs uppercase text-slate-500">Revenue</div>
          <div className="text-2xl font-semibold">{data?.revenue ?? "—"}</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-900/80 p-4">
          <div className="text-xs uppercase text-slate-500">Expense</div>
          <div className="text-2xl font-semibold">{data?.expense ?? "—"}</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-900/80 p-4">
          <div className="text-xs uppercase text-slate-500">Net income</div>
          <div className="text-2xl font-semibold">{data?.net_income ?? "—"}</div>
        </div>
      </div>
    </div>
  );
}
