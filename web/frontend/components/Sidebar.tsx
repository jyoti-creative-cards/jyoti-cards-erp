"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type Item = { href: string; label: string };
type Group = { title: string; items: Item[] };

const groups: Group[] = [
  {
    title: "Overview",
    items: [{ href: "/", label: "Dashboard" }],
  },
  {
    title: "Entities",
    items: [
      { href: "/customers", label: "Customers" },
      { href: "/vendors", label: "Vendors" },
      { href: "/vendor-products", label: "Catalog (SKUs)" },
    ],
  },
  {
    title: "Orders & stock",
    items: [
      { href: "/purchase-orders", label: "Purchase orders" },
      { href: "/customer-orders", label: "Customer orders" },
      { href: "/stock-receipts", label: "Stock receipts" },
      { href: "/inventory", label: "Inventory" },
    ],
  },
  {
    title: "Accounts",
    items: [
      { href: "/accounting/ar", label: "AR (receivable)" },
      { href: "/accounting/ap", label: "AP (payable)" },
      { href: "/accounting/gl", label: "GL accounts" },
      { href: "/accounting/journals", label: "Journal register" },
      { href: "/accounting/trial", label: "Trial balance" },
      { href: "/accounting/pnl", label: "P&L" },
    ],
  },
  {
    title: "Billing",
    items: [
      { href: "/billing/customer", label: "Customer billing" },
      { href: "/billing/vendor", label: "Purchase billing" },
    ],
  },
  {
    title: "Documents",
    items: [
      { href: "/documents/purchase-orders", label: "PO documents" },
      { href: "/documents/goods-receipts", label: "Goods receipts" },
      { href: "/documents/vendor-bills", label: "Vendor bills" },
      { href: "/documents/sales-orders", label: "Sales orders" },
    ],
  },
  {
    title: "Analytics",
    items: [{ href: "/analytics", label: "Sales analytics" }],
  },
  {
    title: "Setup",
    items: [{ href: "/warehouses", label: "Warehouses" }],
  },
];

export function Sidebar() {
  const pathname = usePathname() || "/";

  return (
    <aside className="flex w-56 shrink-0 flex-col overflow-y-auto border-r border-slate-700 bg-sidebar py-4">
      <div className="px-4 pb-4 text-sm font-semibold tracking-tight text-slate-200">
        Jyoti ERP
      </div>
      <nav className="flex flex-col gap-4 px-2">
        {groups.map((g) => (
          <div key={g.title}>
            <div className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              {g.title}
            </div>
            <div className="flex flex-col gap-0.5">
              {g.items.map((l) => {
                const active =
                  l.href === "/"
                    ? pathname === "/"
                    : pathname === l.href ||
                      pathname.startsWith(`${l.href}/`);
                return (
                  <Link
                    key={l.href}
                    href={l.href}
                    prefetch
                    className={
                      active
                        ? "rounded-md bg-slate-700 px-3 py-2 text-sm font-medium text-white"
                        : "rounded-md px-3 py-2 text-sm text-slate-300 hover:bg-slate-700/80 hover:text-white"
                    }
                  >
                    {l.label}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
    </aside>
  );
}
