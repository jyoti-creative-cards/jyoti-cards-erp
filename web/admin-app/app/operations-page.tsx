"use client";

import { useEffect, useState } from "react";
import { ErpAppShell, type ErpMainTab } from "@/components/ErpAppShell";
import { PeopleScreen } from "@/components/PeopleScreen";
import { CatalogScreen } from "@/components/CatalogScreen";
import { StockScreen } from "@/components/StockScreen";
import { OrdersScreen } from "@/components/OrdersScreen";
import { FinanceScreen } from "@/components/FinanceScreen";
import { CreateScreen } from "@/components/CreateScreen";
import { AdminScreen } from "@/components/AdminScreen";
import { RecycleBinScreen } from "@/components/RecycleBinScreen";
import { ReturnsScreen } from "@/components/ReturnsScreen";
import { StaffScreen } from "@/components/StaffScreen";
import { apiUrl, authHeaders, fetchApi, formatApiError, jsonAuthHeaders } from "@/lib/api";
import type { AuthState, StaffPublic } from "@/lib/types";
import { getApiBase } from "@/lib/api";

const AUTH_STORE = "erp_auth_v2";

function loadStoredAuth(): AuthState {
  try {
    const raw = sessionStorage.getItem(AUTH_STORE);
    if (!raw) return { type: "none" };
    return JSON.parse(raw) as AuthState;
  } catch { return { type: "none" }; }
}

function saveAuth(a: AuthState) {
  try { sessionStorage.setItem(AUTH_STORE, JSON.stringify(a)); } catch { /* ignore */ }
}

function hasPermission(auth: AuthState, perm: string): boolean {
  if (auth.type === "admin_key") return true;
  if (auth.type === "staff") {
    if (auth.staff.role === "admin") return true;
    return auth.staff.permissions.includes(perm);
  }
  return false;
}

// ─── Login Page ───────────────────────────────────────────────────────────────

function LoginPage({ onAuth }: { onAuth: (a: AuthState) => void }) {
  const [mode, setMode] = useState<"key" | "staff">("staff");
  const [adminKey, setAdminKey] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleAdminKey(e: React.FormEvent) {
    e.preventDefault();
    const key = adminKey.trim();
    if (!key) return;
    setLoading(true); setError("");
    // Validate key by calling a protected endpoint
    const r = await fetchApi(apiUrl("customers"), { headers: { "X-Admin-Key": key } });
    setLoading(false);
    if (r.ok || r.status === 200) {
      const auth: AuthState = { type: "admin_key", key };
      onAuth(auth);
    } else {
      setError("Invalid admin key.");
    }
  }

  async function handleStaffLogin(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true); setError("");
    const r = await fetchApi(apiUrl("staff/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: email.trim().toLowerCase(), password }),
    });
    const data = await r.json().catch(() => ({})) as { access_token?: string; staff?: StaffPublic };
    setLoading(false);
    if (!r.ok) { setError(formatApiError(data)); return; }
    if (data.access_token && data.staff) {
      const auth: AuthState = { type: "staff", token: data.access_token, staff: data.staff };
      onAuth(auth);
    } else {
      setError("Login failed.");
    }
  }

  return (
    <div className="flex min-h-screen bg-[#0f172a]">
      {/* Left panel - branding */}
      <div className="hidden lg:flex lg:w-[420px] flex-col justify-between bg-[#0a1020] p-10">
        <div>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.jpeg" alt="Jyoti Creative Cards" className="h-12 w-12 rounded-xl object-cover" />
          <h1 className="mt-8 text-3xl font-bold text-white leading-tight">Jyoti Creative<br />Cards ERP</h1>
          <p className="mt-3 text-slate-400 text-sm leading-relaxed">Operations portal — manage orders, inventory, billing, people, and more from one place.</p>
        </div>
        <div className="space-y-3">
          {["Orders & billing", "Inventory tracking", "Customer management", "Staff access control"].map(f => (
            <div key={f} className="flex items-center gap-2.5 text-sm text-slate-400">
              <span className="h-1.5 w-1.5 rounded-full bg-blue-500" />
              {f}
            </div>
          ))}
        </div>
      </div>

      {/* Right panel - login */}
      <div className="flex flex-1 flex-col items-center justify-center p-6">
        <div className="w-full max-w-sm">
          {/* Mobile logo */}
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/logo.jpeg" alt="Jyoti Creative Cards" className="h-10 w-10 rounded-xl object-cover" />
            <h1 className="text-xl font-bold text-white">ERP Portal</h1>
          </div>

        <div className="rounded-2xl bg-white/5 border border-white/10 backdrop-blur-sm shadow-2xl overflow-hidden">
          {/* Mode toggle */}
          <div className="flex border-b border-white/10">
            <button type="button" onClick={() => setMode("staff")}
              className={`flex-1 py-3 text-sm font-medium transition ${mode === "staff" ? "bg-white/10 text-white" : "text-slate-400 hover:text-slate-200"}`}>
              Staff Login
            </button>
            <button type="button" onClick={() => setMode("key")}
              className={`flex-1 py-3 text-sm font-medium transition ${mode === "key" ? "bg-white/10 text-white" : "text-slate-400 hover:text-slate-200"}`}>
              Admin Key
            </button>
          </div>

          <div className="p-6">
            {error && (
              <div className="mb-4 rounded-lg bg-red-500/20 border border-red-500/30 px-4 py-3 text-sm text-red-300">{error}</div>
            )}

            {mode === "staff" ? (
              <form onSubmit={handleStaffLogin} className="space-y-4">
                <div>
                  <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-slate-400">Username</label>
                  <input type="text" required value={email} onChange={e => setEmail(e.target.value)}
                    placeholder="your.username"
                    autoComplete="username"
                    className="w-full rounded-xl border border-white/10 bg-white/10 px-4 py-3 text-sm text-white placeholder-slate-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" />
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-slate-400">Password</label>
                  <input type="password" required value={password} onChange={e => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full rounded-xl border border-white/10 bg-white/10 px-4 py-3 text-sm text-white placeholder-slate-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" />
                </div>
                <button type="submit" disabled={loading}
                  className="w-full rounded-xl bg-blue-600 py-3 text-sm font-semibold text-white shadow-lg hover:bg-blue-500 disabled:opacity-50 transition-colors">
                  {loading ? "Signing in…" : "Sign In →"}
                </button>
              </form>
            ) : (
              <form onSubmit={handleAdminKey} className="space-y-4">
                <div>
                  <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-slate-400">Admin API Key</label>
                  <input type="password" required value={adminKey} onChange={e => setAdminKey(e.target.value)}
                    placeholder="Enter admin key"
                    className="w-full rounded-xl border border-white/10 bg-white/10 px-4 py-3 text-sm text-white placeholder-slate-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" />
                </div>
                <button type="submit" disabled={loading}
                  className="w-full rounded-xl bg-blue-600 py-3 text-sm font-semibold text-white shadow-lg hover:bg-blue-500 disabled:opacity-50 transition-colors">
                  {loading ? "Verifying…" : "Enter →"}
                </button>
              </form>
            )}
          </div>
        </div>
        </div>
      </div>
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────

export default function OperationsAdminPage() {
  const [mainTab, setMainTab] = useState<ErpMainTab>("orders");
  const [auth, setAuth] = useState<AuthState>({ type: "none" });

  useEffect(() => {
    const stored = loadStoredAuth();
    if (stored.type !== "none") setAuth(stored);
  }, []);

  function onAuth(a: AuthState) {
    setAuth(a);
    saveAuth(a);
    // Default tab based on permissions
    if (a.type === "staff" && a.staff.role !== "admin") {
      const firstPerm = a.staff.permissions[0] || "";
      const tabMap: Record<string, ErpMainTab> = {
        "orders.view": "orders", "people.view": "people", "catalog.view": "catalog",
        "stock.view": "stock", "finance.view": "finance", "returns.view": "returns",
      };
      const firstTab = tabMap[firstPerm] || "orders";
      setMainTab(firstTab);
    }
  }

  function onLogout() {
    setAuth({ type: "none" });
    saveAuth({ type: "none" });
    setMainTab("orders");
  }

  // Legacy adminKey for components still expecting it
  const adminKey = auth.type === "admin_key" ? auth.key : "";

  const can = (perm: string) => hasPermission(auth, perm);

  if (auth.type === "none") {
    return <LoginPage onAuth={onAuth} />;
  }

  return (
    <ErpAppShell
      mainTab={mainTab}
      setMainTab={setMainTab}
      auth={auth}
      onLogout={onLogout}
      apiBase={getApiBase()}
    >
      {mainTab === "people"     && can("people.view")     && <PeopleScreen adminKey={adminKey} auth={auth} />}
      {mainTab === "catalog"    && can("catalog.view")    && <CatalogScreen adminKey={adminKey} />}
      {mainTab === "stock"      && can("stock.view")      && <StockScreen adminKey={adminKey} />}
      {mainTab === "orders"     && can("orders.view")     && <OrdersScreen adminKey={adminKey} />}
      {mainTab === "finance"    && can("finance.view")    && <FinanceScreen adminKey={adminKey} />}
      {mainTab === "returns"    && can("returns.view")    && <ReturnsScreen auth={auth} canEdit={can("returns.edit")} />}
      {mainTab === "create"     && can("create.use")      && <CreateScreen adminKey={adminKey} />}
      {mainTab === "admin"      && (can("admin.setup") || can("admin.audit")) && <AdminScreen adminKey={adminKey} auth={auth} />}
      {mainTab === "staff"      && can("admin.manage")    && <StaffScreen auth={auth} />}
      {mainTab === "recyclebin" && can("recyclebin.view") && <RecycleBinScreen adminKey={adminKey} />}
    </ErpAppShell>
  );
}
