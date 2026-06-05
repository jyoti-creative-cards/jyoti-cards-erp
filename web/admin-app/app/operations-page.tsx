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
      body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
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
    <div className="flex min-h-screen flex-col items-center justify-center bg-slate-100 px-4">
      <div className="w-full max-w-md">
        {/* Brand */}
        <div className="mb-8 flex flex-col items-center gap-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.jpeg" alt="Jyoti Creative Cards" className="h-14 w-auto rounded-xl shadow" />
          <h1 className="text-2xl font-bold text-slate-800">ERP Portal</h1>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white shadow-lg">
          {/* Mode toggle */}
          <div className="flex border-b border-slate-200">
            <button type="button" onClick={() => setMode("staff")}
              className={`flex-1 py-3 text-sm font-medium transition ${mode === "staff" ? "border-b-2 border-blue-500 text-blue-600" : "text-slate-500 hover:text-slate-700"}`}>
              Staff Login
            </button>
            <button type="button" onClick={() => setMode("key")}
              className={`flex-1 py-3 text-sm font-medium transition ${mode === "key" ? "border-b-2 border-blue-500 text-blue-600" : "text-slate-500 hover:text-slate-700"}`}>
              Admin Key
            </button>
          </div>

          <div className="p-6">
            {error && (
              <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
            )}

            {mode === "staff" ? (
              <form onSubmit={handleStaffLogin} className="space-y-4">
                <div>
                  <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-slate-500">Email</label>
                  <input type="email" required value={email} onChange={e => setEmail(e.target.value)}
                    placeholder="your@email.com"
                    className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-slate-500">Password</label>
                  <input type="password" required value={password} onChange={e => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" />
                </div>
                <button type="submit" disabled={loading}
                  className="w-full rounded-lg bg-blue-600 py-2.5 text-sm font-semibold text-white shadow hover:bg-blue-700 disabled:opacity-50">
                  {loading ? "Signing in…" : "Sign In"}
                </button>
              </form>
            ) : (
              <form onSubmit={handleAdminKey} className="space-y-4">
                <div>
                  <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-slate-500">Admin API Key</label>
                  <input type="password" required value={adminKey} onChange={e => setAdminKey(e.target.value)}
                    placeholder="Enter admin key"
                    className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" />
                </div>
                <button type="submit" disabled={loading}
                  className="w-full rounded-lg bg-blue-600 py-2.5 text-sm font-semibold text-white shadow hover:bg-blue-700 disabled:opacity-50">
                  {loading ? "Verifying…" : "Enter"}
                </button>
              </form>
            )}
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
      {mainTab === "admin"      &&                           <AdminScreen adminKey={adminKey} />}
      {mainTab === "staff"      && can("admin.manage")    && <StaffScreen auth={auth} />}
      {mainTab === "recyclebin" && can("recyclebin.view") && <RecycleBinScreen adminKey={adminKey} />}
    </ErpAppShell>
  );
}
