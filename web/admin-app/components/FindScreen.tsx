"use client";

import { useState } from "react";
import { apiUrl, fetchApi } from "@/lib/api";
import type { AuthState } from "@/lib/types";

// ─── Entity / field config ────────────────────────────────────────────────────

type Clause =
  | "contains" | "not_contains"
  | "equals" | "not_equals"
  | "starts_with" | "ends_with"
  | "greater_than" | "less_than" | "between"
  | "is_empty" | "is_not_empty";

const TEXT_CLAUSES: { id: Clause; label: string }[] = [
  { id: "equals",       label: "is equal to" },
  { id: "not_equals",   label: "is not equal to" },
  { id: "contains",     label: "contains" },
  { id: "not_contains", label: "does not contain" },
  { id: "starts_with",  label: "starts with" },
  { id: "ends_with",    label: "ends with" },
  { id: "is_empty",     label: "is empty" },
  { id: "is_not_empty", label: "is not empty" },
];

const NUM_CLAUSES: { id: Clause; label: string }[] = [
  { id: "equals",       label: "is equal to" },
  { id: "not_equals",   label: "is not equal to" },
  { id: "greater_than", label: "is greater than" },
  { id: "less_than",    label: "is less than" },
  { id: "between",      label: "is between" },
];

interface FieldDef {
  id: string;
  label: string;
  type: "text" | "number" | "date";
  accessor: (row: Record<string, unknown>) => string | number | null;
}

interface EntityDef {
  id: string;
  label: string;
  icon: string;
  endpoint: string;
  fields: FieldDef[];
  rowLabel: (row: Record<string, unknown>) => string;
  rowSub: (row: Record<string, unknown>) => string;
}

const ENTITIES: EntityDef[] = [
  {
    id: "customer",
    label: "Customer",
    icon: "👤",
    endpoint: "customers",
    fields: [
      { id: "name",         label: "Name",         type: "text",   accessor: r => String(r.name ?? r.company_name ?? "") },
      { id: "company_name", label: "Company",       type: "text",   accessor: r => String(r.company_name ?? "") },
      { id: "phone",        label: "Phone",         type: "text",   accessor: r => String(r.phone ?? "") },
      { id: "city",         label: "City",          type: "text",   accessor: r => String((r.city as Record<string,unknown>)?.name ?? "") },
      { id: "route",        label: "Route",         type: "text",   accessor: r => String((r.route as Record<string,unknown>)?.name ?? "") },
    ],
    rowLabel: r => String(r.company_name || r.name || ""),
    rowSub:   r => String(r.phone ?? ""),
  },
  {
    id: "bill",
    label: "Bill",
    icon: "🧾",
    endpoint: "customer-bills",
    fields: [
      { id: "bill_no",          label: "Bill number",   type: "text",   accessor: r => String(r.bill_no ?? "") },
      { id: "grand_total",      label: "Grand total",   type: "number", accessor: r => Number((r.totals as Record<string,unknown>)?.grand_total ?? 0) },
      { id: "product",          label: "Product (name/code)", type: "text", accessor: r => {
        const items = Array.isArray(r.items) ? r.items as Record<string,unknown>[] : [];
        return items.map(i => `${i.our_product_id ?? ""} ${i.name ?? ""}`).join(" ").toLowerCase();
      }},
      { id: "narration",        label: "Narration",     type: "text",   accessor: r => String(r.narration ?? "") },
      { id: "gst_enabled",      label: "Has GST",       type: "text",   accessor: r => r.gst_enabled ? "yes" : "no" },
    ],
    rowLabel: r => {
      const b = r.bill_no ? `Bill ${r.bill_no}` : `Bill #${r.id}`;
      const gt = (r.totals as Record<string,unknown>)?.grand_total;
      return gt ? `${b} — ₹${gt}` : b;
    },
    rowSub: r => String(r.created_at ? new Date(String(r.created_at)).toLocaleDateString("en-IN") : ""),
  },
  {
    id: "order",
    label: "Customer Order",
    icon: "📋",
    endpoint: "customer-orders",
    fields: [
      { id: "customer_name",  label: "Customer name",  type: "text",   accessor: r => String(r.customer_name ?? "") },
      { id: "status",         label: "Status",         type: "text",   accessor: r => String(r.status ?? "") },
      { id: "total_amount",   label: "Amount",         type: "number", accessor: r => Number(r.total_amount ?? 0) },
      { id: "product",        label: "Product (name/code)", type: "text", accessor: r => {
        const items = Array.isArray(r.items) ? r.items as Record<string,unknown>[] : [];
        return items.map(i => `${i.our_product_id ?? ""} ${i.name ?? ""}`).join(" ").toLowerCase();
      }},
      { id: "notes",          label: "Notes",          type: "text",   accessor: r => String(r.notes ?? "") },
    ],
    rowLabel: r => `Order #${r.id} — ${r.customer_name ?? ""}`,
    rowSub:   r => `${r.status ?? ""} · ₹${r.total_amount ?? 0}`,
  },
  {
    id: "product",
    label: "Product",
    icon: "📦",
    endpoint: "catalog",
    fields: [
      { id: "our_product_id", label: "Product code",   type: "text",   accessor: r => String(r.our_product_id ?? "") },
      { id: "name",           label: "Name",           type: "text",   accessor: r => String(r.name ?? "") },
      { id: "selling_price",  label: "Selling price",  type: "number", accessor: r => Number(r.selling_price ?? 0) },
      { id: "buying_price",   label: "Buying price",   type: "number", accessor: r => Number(r.buying_price ?? 0) },
      { id: "stock_status",   label: "Stock status",   type: "text",   accessor: r => String(r.stock_status ?? "") },
    ],
    rowLabel: r => String(r.our_product_id ?? r.name ?? ""),
    rowSub:   r => `₹${r.selling_price ?? 0} · ${r.stock_status ?? ""}`,
  },
  {
    id: "vendor",
    label: "Vendor",
    icon: "🏭",
    endpoint: "vendors",
    fields: [
      { id: "company_name",  label: "Company",  type: "text", accessor: r => String(r.company_name ?? "") },
      { id: "person_name",   label: "Contact",  type: "text", accessor: r => String(r.person_name ?? "") },
      { id: "phone",         label: "Phone",    type: "text", accessor: r => String(r.phone ?? "") },
    ],
    rowLabel: r => String(r.company_name || r.person_name || ""),
    rowSub:   r => String(r.phone ?? ""),
  },
];

// ─── Matching engine ──────────────────────────────────────────────────────────

function matches(
  row: Record<string, unknown>,
  field: FieldDef,
  clause: Clause,
  value: string,
  value2: string,
): boolean {
  const raw = field.accessor(row);
  const v = String(raw ?? "").toLowerCase();
  const cmp = value.toLowerCase().trim();

  switch (clause) {
    case "is_empty":     return v === "" || raw === null || raw === undefined;
    case "is_not_empty": return v !== "" && raw !== null && raw !== undefined;
    case "equals":       return v === cmp;
    case "not_equals":   return v !== cmp;
    case "contains":     return v.includes(cmp);
    case "not_contains": return !v.includes(cmp);
    case "starts_with":  return v.startsWith(cmp);
    case "ends_with":    return v.endsWith(cmp);
    case "greater_than": return Number(raw) > Number(value);
    case "less_than":    return Number(raw) < Number(value);
    case "between":      return Number(raw) >= Number(value) && Number(raw) <= Number(value2);
    default:             return false;
  }
}

// ─── Component ────────────────────────────────────────────────────────────────

const INPUT = "rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";

export function FindScreen({ auth }: { auth: AuthState }) {
  const h = (): Record<string, string> => {
    if (auth.type === "admin_key") return { "X-Admin-Key": auth.key };
    if (auth.type === "staff") return { Authorization: `Bearer ${auth.token}` };
    return {};
  };

  const [entityId, setEntityId] = useState(ENTITIES[0].id);
  const [fieldId, setFieldId] = useState(ENTITIES[0].fields[0].id);
  const [clause, setClause] = useState<Clause>("contains");
  const [value, setValue] = useState("");
  const [value2, setValue2] = useState("");

  const [allData, setAllData] = useState<Record<string, unknown>[]>([]);
  const [results, setResults] = useState<Record<string, unknown>[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const entity = ENTITIES.find(e => e.id === entityId)!;
  const field = entity.fields.find(f => f.id === fieldId) ?? entity.fields[0];
  const clauses = field.type === "number" ? NUM_CLAUSES : TEXT_CLAUSES;
  const needsValue = !["is_empty", "is_not_empty"].includes(clause);

  function switchEntity(id: string) {
    const e = ENTITIES.find(x => x.id === id)!;
    setEntityId(id);
    setFieldId(e.fields[0].id);
    setClause(e.fields[0].type === "number" ? "greater_than" : "contains");
    setValue(""); setValue2("");
    setResults(null); setAllData([]); setSearched(false);
  }

  async function doSearch() {
    if (!entity) return;
    setLoading(true);
    setSearched(true);
    try {
      let data = allData;
      if (!data.length) {
        const r = await fetchApi(apiUrl(entity.endpoint), { headers: h() });
        if (!r.ok) { setLoading(false); return; }
        const raw = await r.json();
        data = Array.isArray(raw) ? raw : (raw.items ?? []);
        setAllData(data);
      }
      const filtered = data.filter(row => matches(row, field, clause, value, value2));
      setResults(filtered);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6 p-4 sm:p-6">
      {/* Header */}
      <div>
        <h2 className="text-lg font-bold text-slate-800">Find</h2>
        <p className="mt-0.5 text-sm text-slate-500">Search across customers, bills, orders, products and vendors using any field and condition.</p>
      </div>

      {/* Search builder */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
        {/* Entity selector */}
        <div className="flex flex-wrap gap-2">
          {ENTITIES.map(e => (
            <button key={e.id} type="button" onClick={() => switchEntity(e.id)}
              className={`flex items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-semibold transition ${entityId === e.id ? "bg-blue-600 text-white shadow" : "border border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100"}`}>
              {e.icon} {e.label}
            </button>
          ))}
        </div>

        {/* Filter row */}
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col">
            <label className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">Where</label>
            <select value={fieldId}
              onChange={e => { setFieldId(e.target.value); const f = entity.fields.find(x => x.id === e.target.value); setClause(f?.type === "number" ? "greater_than" : "contains"); }}
              className={INPUT}>
              {entity.fields.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}
            </select>
          </div>

          <div className="flex flex-col">
            <label className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">Condition</label>
            <select value={clause} onChange={e => setClause(e.target.value as Clause)} className={INPUT}>
              {clauses.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
            </select>
          </div>

          {needsValue && (
            <div className="flex flex-col">
              <label className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">Value</label>
              <input
                value={value}
                onChange={e => setValue(e.target.value)}
                onKeyDown={e => e.key === "Enter" && void doSearch()}
                type={field.type === "number" ? "number" : "text"}
                placeholder={`Enter ${field.label.toLowerCase()}…`}
                className={INPUT + " min-w-[200px]"} />
            </div>
          )}

          {clause === "between" && (
            <div className="flex flex-col">
              <label className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">To</label>
              <input value={value2} onChange={e => setValue2(e.target.value)} type="number" placeholder="Max value" className={INPUT + " w-36"} />
            </div>
          )}

          <button type="button" onClick={doSearch} disabled={loading}
            className="mt-5 inline-flex items-center gap-2 rounded-xl bg-blue-600 px-5 py-2 text-sm font-bold text-white shadow-sm hover:bg-blue-700 disabled:opacity-50">
            {loading ? "Searching…" : "🔍 Search"}
          </button>
        </div>
      </div>

      {/* Results */}
      {searched && results !== null && (
        <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-5 py-3">
            <span className="text-sm font-bold text-slate-700">
              {results.length === 0 ? "No results" : `${results.length} result${results.length !== 1 ? "s" : ""}`}
            </span>
            <span className="text-xs text-slate-400">
              {entity.icon} {entity.label} · {field.label} {clauses.find(c => c.id === clause)?.label} {needsValue ? `"${value}"${clause === "between" ? ` and "${value2}"` : ""}` : ""}
            </span>
          </div>

          {results.length === 0 ? (
            <div className="py-12 text-center text-slate-400 text-sm">
              <p className="text-3xl mb-3">🔍</p>
              No {entity.label.toLowerCase()}s match your search.
            </div>
          ) : (
            <div className="divide-y divide-slate-100">
              {results.map((row, i) => (
                <ResultRow key={i} row={row} entity={entity} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Result row ───────────────────────────────────────────────────────────────

function ResultRow({ row, entity }: { row: Record<string, unknown>; entity: EntityDef }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div>
      <button type="button" onClick={() => setExpanded(v => !v)}
        className="w-full px-5 py-3 text-left transition hover:bg-slate-50 flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-800">{entity.rowLabel(row)}</p>
          <p className="text-xs text-slate-500 mt-0.5">{entity.rowSub(row)}</p>
        </div>
        <span className="text-slate-300 text-lg">{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded && (
        <div className="border-t border-slate-100 bg-slate-50 px-5 py-4">
          <DetailView row={row} entityId={entity.id} />
        </div>
      )}
    </div>
  );
}

function DetailView({ row, entityId }: { row: Record<string, unknown>; entityId: string }) {
  const skip = new Set(["deleted_at", "document_key", "image_keys", "versions"]);

  // Build human-readable fields
  const fields: { label: string; value: string }[] = [];

  if (entityId === "customer") {
    fields.push(
      { label: "Name", value: String(row.name ?? "") },
      { label: "Company", value: String(row.company_name ?? "—") },
      { label: "Phone", value: String(row.phone ?? "—") },
      { label: "City", value: String((row.city as Record<string,unknown>)?.name ?? "—") },
      { label: "Route", value: String((row.route as Record<string,unknown>)?.name ?? "—") },
      { label: "Credit limit", value: row.credit_limit ? `₹${row.credit_limit}` : "None" },
      { label: "Status", value: row.is_active ? "Active" : "Inactive" },
    );
  } else if (entityId === "bill") {
    const totals = (row.totals ?? {}) as Record<string, unknown>;
    fields.push(
      { label: "Bill no", value: String(row.bill_no ?? `#${row.id}`) },
      { label: "Order ID", value: String(row.customer_order_id ?? "—") },
      { label: "Grand total", value: `₹${totals.grand_total ?? 0}` },
      { label: "Subtotal", value: `₹${totals.subtotal ?? 0}` },
      { label: "GST", value: row.gst_enabled ? `${row.gst_rate_percent}%` : "No" },
      { label: "Discount", value: row.discount_percent ? `${row.discount_percent}%` : "None" },
      { label: "Narration", value: String(row.narration ?? "—") },
      { label: "Created", value: row.created_at ? new Date(String(row.created_at)).toLocaleString("en-IN") : "—" },
    );
    if (row.document_key) {
      fields.push({ label: "PDF", value: "Available" });
    }
  } else if (entityId === "order") {
    const items = Array.isArray(row.items) ? row.items as Record<string, unknown>[] : [];
    fields.push(
      { label: "Customer", value: String(row.customer_name ?? "—") },
      { label: "Status", value: String(row.status ?? "—") },
      { label: "Total", value: `₹${row.total_amount ?? 0}` },
      { label: "Items", value: items.map(i => `${i.our_product_id ?? i.name} ×${i.quantity}`).join(", ") || "—" },
      { label: "Notes", value: String(row.notes ?? "—") },
      { label: "Created", value: row.created_at ? new Date(String(row.created_at)).toLocaleString("en-IN") : "—" },
    );
  } else if (entityId === "product") {
    fields.push(
      { label: "Code", value: String(row.our_product_id ?? "—") },
      { label: "Name", value: String(row.name ?? "—") },
      { label: "Selling price", value: `₹${row.selling_price ?? 0}` },
      { label: "Buying price", value: `₹${row.buying_price ?? 0}` },
      { label: "Stock status", value: String(row.stock_status ?? "—") },
      { label: "Category", value: String(row.category ?? "—") },
    );
  } else if (entityId === "vendor") {
    fields.push(
      { label: "Company", value: String(row.company_name ?? "—") },
      { label: "Contact", value: String(row.person_name ?? "—") },
      { label: "Phone", value: String(row.phone ?? "—") },
      { label: "Email", value: String(row.email ?? "—") },
      { label: "GST no", value: String(row.gst_no ?? "—") },
    );
  }

  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-3">
      {fields.filter(f => f.value !== "" && f.value !== "undefined").map(f => (
        <div key={f.label}>
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">{f.label}</span>
          <p className="text-sm text-slate-800 break-words">{f.value}</p>
        </div>
      ))}
    </div>
  );
}
