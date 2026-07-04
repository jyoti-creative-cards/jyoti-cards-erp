"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import type { AuthState } from "@/lib/types";

export type ErpMainTab =
  | "dashboard" | "people" | "orders" | "stock" | "finance"
  | "find" | "reports" | "create" | "admin" | "staff" | "recyclebin";

type NavItem = { id: ErpMainTab; label: string; icon: string; permission?: string };
type NavSection = { title?: string; items: NavItem[] };

const NAV_SECTIONS: NavSection[] = [
  {
    items: [
      { id: "dashboard",     label: "Dashboard",       icon: "🏠", permission: undefined       },
      { id: "people",        label: "People",          icon: "👥", permission: "people.view"  },
      { id: "orders",        label: "Orders",          icon: "📋", permission: "orders.view"  },
      { id: "stock",         label: "Stock",           icon: "🏪", permission: "stock.view"   },
      { id: "finance",       label: "Finance",         icon: "💰", permission: "finance.view" },
      { id: "find",          label: "Find",            icon: "🔍",  permission: undefined       },
      { id: "reports",       label: "Reports",         icon: "📊",  permission: undefined       },
    ],
  },
  {
    title: "Settings",
    items: [
      { id: "admin",      label: "Setup",       icon: "⚙️",  permission: "admin.setup"    },
      { id: "staff",      label: "Staff",       icon: "👔",  permission: "admin.manage"   },
      { id: "recyclebin", label: "Recycle Bin", icon: "🗑️",  permission: "recyclebin.view"},
    ],
  },
];

const TITLE_MAP: Record<ErpMainTab, string> = {
  dashboard: "Dashboard", orders: "Orders", people: "People",
  stock: "Stock", finance: "Finance",
  create: "Quick Add",
  find: "Find", reports: "Reports", admin: "Setup", staff: "Staff Management", recyclebin: "Recycle Bin",
};

function hasPermission(auth: AuthState, perm?: string): boolean {
  if (!perm) return true;
  if (auth.type === "admin_key") return true;
  if (auth.type === "staff") {
    if (auth.staff.role === "admin") return true;
    return auth.staff.permissions.includes(perm);
  }
  return false;
}

type Props = {
  mainTab: ErpMainTab;
  setMainTab: (t: ErpMainTab) => void;
  auth: AuthState;
  onLogout: () => void;
  apiBase: string;
  children: ReactNode;
};

export function ErpAppShell({ mainTab, setMainTab, auth, onLogout, apiBase, children }: Props) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const staffName = auth.type === "staff" ? auth.staff.name : "Admin";
  const userInitial = staffName.charAt(0).toUpperCase();
  const isAdminKey = auth.type === "admin_key";

  const canCreate = hasPermission(auth, "create.use");

  function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
    return (
      <div className="flex h-full flex-col">
        {/* Logo */}
        <div className="flex items-center gap-3 px-4 py-4 border-b border-white/10">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.jpeg" alt="Jyoti Creative Cards" className="h-8 w-8 rounded-lg object-cover flex-shrink-0" />
          {!sidebarCollapsed && (
            <div className="min-w-0">
              <p className="text-sm font-bold text-white truncate leading-tight">Jyoti Creative</p>
              <p className="text-[10px] text-slate-400">ERP Portal</p>
            </div>
          )}
        </div>

        {/* Quick Add button */}
        {canCreate && (
          <div className="px-3 pt-4 pb-2">
            <button
              type="button"
              onClick={() => { setMainTab("create"); onNavigate?.(); }}
              className={`flex items-center gap-2.5 w-full rounded-xl bg-blue-600 px-3 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-500 transition-colors ${sidebarCollapsed ? "justify-center" : ""}`}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M12 5v14M5 12h14" />
              </svg>
              {!sidebarCollapsed && "Quick Add"}
            </button>
          </div>
        )}

        {/* Nav sections */}
        <nav className="flex-1 overflow-y-auto px-3 py-2 space-y-5">
          {NAV_SECTIONS.map((section, si) => {
            const visible = section.items.filter(item => hasPermission(auth, item.permission));
            if (!visible.length) return null;
            return (
              <div key={si}>
                {section.title && !sidebarCollapsed && (
                  <p className="mb-1 px-2 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                    {section.title}
                  </p>
                )}
                <div className="space-y-0.5">
                  {visible.map(item => {
                    const active = mainTab === item.id;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => { setMainTab(item.id); onNavigate?.(); }}
                        title={sidebarCollapsed ? item.label : undefined}
                        className={`flex items-center gap-3 w-full rounded-xl px-3 py-2.5 text-sm font-medium transition-all ${
                          active
                            ? "bg-white/15 text-white shadow-sm"
                            : "text-slate-400 hover:bg-white/8 hover:text-slate-200"
                        } ${sidebarCollapsed ? "justify-center" : ""}`}
                      >
                        <span className="text-base leading-none flex-shrink-0">{item.icon}</span>
                        {!sidebarCollapsed && <span>{item.label}</span>}
                        {active && !sidebarCollapsed && (
                          <span className="ml-auto h-1.5 w-1.5 rounded-full bg-blue-400" />
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </nav>

        {/* User footer */}
        <div className="border-t border-white/10 px-3 py-3">
          <div className={`flex items-center gap-3 ${sidebarCollapsed ? "justify-center" : ""}`}>
            <div className="h-8 w-8 flex-shrink-0 rounded-full bg-slate-600 flex items-center justify-center text-sm font-bold text-white">
              {userInitial}
            </div>
            {!sidebarCollapsed && (
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-200 truncate">{staffName}</p>
                <p className="text-xs text-slate-500">{isAdminKey ? "Super admin" : auth.type === "staff" ? auth.staff.role : ""}</p>
              </div>
            )}
            {!sidebarCollapsed && (
              <button
                type="button"
                onClick={onLogout}
                title="Logout"
                className="flex-shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-white/10 hover:text-red-400 transition-colors"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
                </svg>
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-100">
      {/* Desktop sidebar */}
      <aside
        className={`hidden md:flex flex-col bg-[#0f172a] transition-all duration-200 flex-shrink-0 ${
          sidebarCollapsed ? "w-[64px]" : "w-[220px]"
        }`}
      >
        <SidebarContent />
        {/* Collapse toggle */}
        <button
          type="button"
          onClick={() => setSidebarCollapsed(v => !v)}
          className="absolute bottom-16 left-0 hidden md:flex h-6 w-6 items-center justify-center rounded-full bg-slate-700 text-slate-300 hover:bg-slate-600 shadow-lg"
          style={{ left: sidebarCollapsed ? "48px" : "208px", bottom: "72px", transition: "left 0.2s" }}
          title={sidebarCollapsed ? "Expand" : "Collapse"}
        >
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            {sidebarCollapsed
              ? <path d="M9 18l6-6-6-6" />
              : <path d="M15 18l-6-6 6-6" />}
          </svg>
        </button>
      </aside>

      {/* Mobile overlay sidebar */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 md:hidden" onClick={() => setSidebarOpen(false)}>
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
          <aside className="absolute left-0 top-0 h-full w-[220px] bg-[#0f172a] shadow-2xl" onClick={e => e.stopPropagation()}>
            <SidebarContent onNavigate={() => setSidebarOpen(false)} />
          </aside>
        </div>
      )}

      {/* Right: topbar + content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top bar (slim) */}
        <header className="flex h-12 flex-shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4 shadow-sm">
          <div className="flex items-center gap-3">
            {/* Mobile hamburger */}
            <button
              type="button"
              className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 md:hidden"
              onClick={() => setSidebarOpen(true)}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M3 6h18M3 12h18M3 18h18" />
              </svg>
            </button>
            {/* Breadcrumb */}
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400">ERP</span>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-slate-300">
                <path d="M9 18l6-6-6-6" />
              </svg>
              <span className="text-sm font-semibold text-slate-700">{TITLE_MAP[mainTab]}</span>
            </div>
          </div>

          {/* Right: user badge on mobile */}
          <div className="flex items-center gap-2 md:hidden">
            <div className="h-7 w-7 rounded-full bg-slate-700 flex items-center justify-center text-xs font-bold text-white">
              {userInitial}
            </div>
            <button type="button" onClick={onLogout} className="text-xs text-slate-400 hover:text-red-500">
              Logout
            </button>
          </div>
        </header>

        {/* Scrollable content */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6">
          <div className="mx-auto max-w-[1400px]">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
