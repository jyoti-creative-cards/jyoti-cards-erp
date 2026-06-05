"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import type { AuthState } from "@/lib/types";

export type ErpMainTab = "people" | "catalog" | "stock" | "orders" | "finance" | "returns" | "create" | "admin" | "staff" | "recyclebin";

type NavEntry = { id: ErpMainTab; label: string; icon: string; permission?: string };

const NAV: NavEntry[] = [
  { id: "people",     label: "People",      icon: "👥", permission: "people.view"    },
  { id: "catalog",    label: "Catalog",     icon: "📦", permission: "catalog.view"   },
  { id: "stock",      label: "Stock",       icon: "🏪", permission: "stock.view"     },
  { id: "orders",     label: "Orders",      icon: "📋", permission: "orders.view"    },
  { id: "finance",    label: "Finance",     icon: "💰", permission: "finance.view"   },
  { id: "returns",    label: "Returns",     icon: "↩️",  permission: "returns.view"   },
  { id: "create",     label: "Create",      icon: "➕", permission: "create.use"     },
  { id: "admin",      label: "Setup",       icon: "⚙️", permission: "admin.setup"    },
  { id: "staff",      label: "Staff",       icon: "👔", permission: "admin.manage"   },
  { id: "recyclebin", label: "Recycle Bin", icon: "🗑️", permission: "recyclebin.view"},
];

const TITLE_MAP: Record<ErpMainTab, string> = {
  people: "People", catalog: "Catalog", stock: "Stock", orders: "Orders",
  finance: "Finance", returns: "Returns & Credit Notes", create: "Create",
  admin: "Admin", staff: "Staff Management", recyclebin: "Recycle Bin",
};

type Props = {
  mainTab: ErpMainTab;
  setMainTab: (t: ErpMainTab) => void;
  auth: AuthState;
  onLogout: () => void;
  apiBase: string;
  children: ReactNode;
};

function hasPermission(auth: AuthState, perm?: string): boolean {
  if (!perm) return true; // no permission required
  if (auth.type === "admin_key") return true; // admin key = full access
  if (auth.type === "staff") {
    if (auth.staff.role === "admin") return true;
    return auth.staff.permissions.includes(perm);
  }
  return false;
}

export function ErpAppShell({ mainTab, setMainTab, auth, onLogout, apiBase, children }: Props) {
  const isLoggedIn = auth.type !== "none";
  const [uiPort, setUiPort] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    setUiPort(typeof window !== "undefined" ? window.location.port : "");
  }, []);

  const visibleNav = NAV.filter(item => hasPermission(auth, item.permission));

  function tabClass(item: NavEntry, active: boolean): string {
    const isCreate = item.id === "create";
    const isAdmin = item.id === "admin" || item.id === "staff";
    if (isCreate) return active
      ? "border-emerald-400 text-emerald-300"
      : "border-transparent text-emerald-400 hover:border-emerald-500 hover:text-emerald-300";
    if (isAdmin) return active
      ? "border-orange-400 text-orange-300"
      : "border-transparent text-orange-400 hover:border-orange-500 hover:text-orange-300";
    return active
      ? "border-blue-400 text-white"
      : "border-transparent text-slate-400 hover:border-slate-500 hover:text-slate-200";
  }

  const staffName = auth.type === "staff" ? auth.staff.name : auth.type === "admin_key" ? "Admin" : "";

  return (
    <div className="erp-shell flex min-h-screen flex-col">
      {/* Top nav bar */}
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-slate-200 bg-[#0f172a] px-4 py-0 shadow-md">
        <div className="flex items-center gap-4">
          <button type="button" className="rounded p-2 text-slate-300 hover:text-white md:hidden"
            onClick={() => setSidebarOpen((v) => !v)}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 6h18M3 12h18M3 18h18" />
            </svg>
          </button>
          <div className="flex items-center py-2">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/logo.jpeg" alt="Jyoti Creative Cards" className="h-9 w-auto rounded" />
          </div>
          <nav className="hidden gap-1 md:flex">
            {visibleNav.map((item) => (
              <button key={item.id} type="button" onClick={() => setMainTab(item.id)}
                className={`flex items-center gap-2 rounded-none border-b-2 px-4 py-3 text-sm font-medium transition-colors ${tabClass(item, mainTab === item.id)}`}>
                <span className="text-base leading-none">{item.icon}</span>
                {item.label}
              </button>
            ))}
          </nav>
        </div>
        {/* User info + logout */}
        <div className="flex items-center gap-3">
          {staffName && (
            <span className="text-xs text-slate-400">{staffName}</span>
          )}
          {isLoggedIn && (
            <button type="button" onClick={onLogout}
              className="rounded border border-slate-600 px-2.5 py-1.5 text-xs text-slate-300 hover:border-red-500 hover:text-red-400">
              Logout
            </button>
          )}
        </div>
      </header>

      {/* Mobile nav drawer */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-30 md:hidden" onClick={() => setSidebarOpen(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <nav className="absolute left-0 top-0 flex h-full w-60 flex-col bg-[#0f172a] p-4 shadow-xl">
            <div className="mb-6 flex items-center gap-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/logo.jpeg" alt="Jyoti Creative Cards" className="h-8 w-auto rounded" />
            </div>
            {visibleNav.map((item) => (
              <button key={item.id} type="button"
                onClick={() => { setMainTab(item.id); setSidebarOpen(false); }}
                className={`flex items-center gap-3 rounded-lg px-3 py-3 text-left text-sm font-medium transition-colors ${
                  mainTab === item.id ? "bg-blue-600 text-white" : "text-slate-300 hover:bg-white/5 hover:text-white"
                }`}>
                <span className="text-xl leading-none">{item.icon}</span>
                {item.label}
              </button>
            ))}
          </nav>
        </div>
      )}

      {/* Content */}
      <main className="flex-1 bg-slate-100 p-4 md:p-6">
        <div className="mx-auto max-w-[1400px]">
          {children}
        </div>
      </main>

      <footer className="border-t border-slate-200 bg-white px-4 py-2 text-center text-[10px] text-slate-400">
        {TITLE_MAP[mainTab]} · Backend{" "}
        <span className="font-mono">{apiBase || "same-origin (/api/proxy)"}</span>
        {uiPort ? ` · UI :${uiPort}` : ""}
      </footer>
    </div>
  );
}
