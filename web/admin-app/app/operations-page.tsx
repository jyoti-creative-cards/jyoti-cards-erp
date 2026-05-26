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
import { getApiBase } from "@/lib/api";

const KEY_STORE = "admin_x_key";

export default function OperationsAdminPage() {
  const [mainTab, setMainTab] = useState<ErpMainTab>("orders");
  const [adminKey, setAdminKey] = useState("");

  useEffect(() => {
    try {
      const k = sessionStorage.getItem(KEY_STORE);
      if (k) setAdminKey(k);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    try { sessionStorage.setItem(KEY_STORE, adminKey.trim()); }
    catch { /* ignore */ }
  }, [adminKey]);

  return (
    <ErpAppShell
      mainTab={mainTab}
      setMainTab={setMainTab}
      adminKey={adminKey}
      setAdminKey={setAdminKey}
      apiBase={getApiBase()}
    >
      {!adminKey.trim() ? (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="text-5xl">🔑</div>
          <h2 className="mt-4 text-lg font-semibold text-slate-700">Enter your admin key to continue</h2>
          <p className="mt-2 text-sm text-slate-500">Type your API key in the field at the top right.</p>
        </div>
      ) : (
        <>
          {mainTab === "people"  && <PeopleScreen  adminKey={adminKey} />}
          {mainTab === "catalog" && <CatalogScreen adminKey={adminKey} />}
          {mainTab === "stock"   && <StockScreen   adminKey={adminKey} />}
          {mainTab === "orders"  && <OrdersScreen  adminKey={adminKey} />}
          {mainTab === "finance" && <FinanceScreen adminKey={adminKey} />}
          {mainTab === "create"  && <CreateScreen  adminKey={adminKey} />}
          {mainTab === "admin"   && <AdminScreen   adminKey={adminKey} />}
        </>
      )}
    </ErpAppShell>
  );
}
