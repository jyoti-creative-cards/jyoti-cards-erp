"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";

export type ErpMainTab = "people" | "catalog" | "stock" | "orders" | "finance" | "create" | "admin";

type NavEntry = { id: ErpMainTab; label: string; icon: string };

const NAV: NavEntry[] = [
  { id: "people",  label: "People",  icon: "👥" },
  { id: "catalog", label: "Catalog", icon: "📦" },
  { id: "stock",   label: "Stock",   icon: "🏪" },
  { id: "orders",  label: "Orders",  icon: "📋" },
  { id: "finance", label: "Finance", icon: "💰" },
  { id: "create",  label: "Create",  icon: "➕" },
  { id: "admin",   label: "Admin",   icon: "⚙️" },
];

const TITLE_MAP: Record<ErpMainTab, string> = {
  people:  "People",
  catalog: "Catalog",
  stock:   "Stock",
  orders:  "Orders",
  finance: "Finance",
  create:  "Create",
  admin:   "Admin",
};

type Props = {
  mainTab: ErpMainTab;
  setMainTab: (t: ErpMainTab) => void;
  adminKey: string;
  setAdminKey: (k: string) => void;
  apiBase: string;
  children: ReactNode;
};

export function ErpAppShell({ mainTab, setMainTab, adminKey, setAdminKey, apiBase, children }: Props) {
  const hasKey = Boolean(adminKey.trim());
  const [uiPort, setUiPort] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    setUiPort(typeof window !== "undefined" ? window.location.port : "");
  }, []);

  return (
    <div className="erp-shell flex min-h-screen flex-col">
      {/* Top nav bar */}
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-slate-200 bg-[#0f172a] px-4 py-0 shadow-md">
        <div className="flex items-center gap-4">
          {/* Mobile hamburger */}
          <button
            type="button"
            className="rounded p-2 text-slate-300 hover:text-white md:hidden"
            onClick={() => setSidebarOpen((v) => !v)}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 6h18M3 12h18M3 18h18" />
            </svg>
          </button>
          {/* Brand */}
          <div className="flex items-center py-2">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/logo.jpeg" alt="Jyoti Creative Cards" className="h-9 w-auto rounded" />
          </div>
          {/* Desktop nav tabs */}
          <nav className="hidden gap-1 md:flex">
            {NAV.map((item) => {
              const active = mainTab === item.id;
                  const isCreate = item.id === "create";
                  const isAdmin = item.id === "admin";
                  return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setMainTab(item.id)}
                  className={`flex items-center gap-2 rounded-none border-b-2 px-4 py-3 text-sm font-medium transition-colors ${
                    isCreate
                      ? active
                        ? "border-emerald-400 text-emerald-300"
                        : "border-transparent text-emerald-400 hover:border-emerald-500 hover:text-emerald-300"
                      : isAdmin
                        ? active
                          ? "border-orange-400 text-orange-300"
                          : "border-transparent text-orange-400 hover:border-orange-500 hover:text-orange-300"
                        : active
                          ? "border-blue-400 text-white"
                          : "border-transparent text-slate-400 hover:border-slate-500 hover:text-slate-200"
                  }`}
                >
                  <span className="text-base leading-none">{item.icon}</span>
                  {item.label}
                </button>
              );
            })}
          </nav>
        </div>
        {/* Admin key */}
        <div className="flex items-center gap-2">
          <input
            type="password"
            data-testid="admin-api-key"
            value={adminKey}
            onChange={(e) => setAdminKey(e.target.value)}
            placeholder="Admin key"
            className="w-32 rounded border border-slate-600 bg-slate-800 px-2.5 py-1.5 text-xs text-white placeholder-slate-400 focus:border-blue-400 focus:outline-none sm:w-40"
          />
          <span
            className={`h-2 w-2 rounded-full ${hasKey ? "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.7)]" : "bg-amber-400"}`}
            title={hasKey ? "Key set" : "No key"}
          />
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
            {NAV.map((item) => {
              const active = mainTab === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => { setMainTab(item.id); setSidebarOpen(false); }}
                  className={`flex items-center gap-3 rounded-lg px-3 py-3 text-left text-sm font-medium transition-colors ${
                    active ? "bg-blue-600 text-white" : "text-slate-300 hover:bg-white/5 hover:text-white"
                  }`}
                >
                  <span className="text-xl leading-none">{item.icon}</span>
                  {item.label}
                </button>
              );
            })}
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
