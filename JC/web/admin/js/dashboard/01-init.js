  function init(context) { ctx = context; }

  function fmtPrice(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc?.(String(val)) || String(val);
    const prefix = n < 0 ? "-₹" : "₹";
    return prefix + Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function fmtPriceExact(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return ctx.esc?.(String(val)) || String(val);
    const prefix = n < 0 ? "-₹" : "₹";
    return prefix + Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function greeting() {
    const h = new Date().getHours();
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    return "Good evening";
  }

  function showHub() {
    load();
  }

  async function load() {
    const body = document.getElementById("dashboard-body");
    if (!body) return;
    ctx.showLoading?.();
    try {
      data = await ctx.api("/dashboard", {}, 0);
      render();
    } catch (e) {
      body.innerHTML = OrdersUI.emptyState({ title: "Could not load Today", sub: e.message });
    } finally {
      ctx.hideLoading?.();
    }
  }

  function goto(target) {
    if (target === "orders_customer") {
      App.showView("selling");
      CustomerOrders?.setHubMode?.("queue");
      CustomerOrders?.setBucket?.("open");
      return;
    }
    if (target === "orders_vendor") {
      App.showView("buying");
      VendorOrders?.setHubMode?.("queue");
      VendorOrders?.setBucket?.("placed");
      return;
    }
    if (target === "finance_ar") {
      App.showView("money");
      Finance?.showAr?.();
      return;
    }
    if (target === "finance_ap") {
      App.showView("money");
      Finance?.showAp?.();
      return;
    }
    if (target === "finance_freight") {
      App.showView("money");
      Finance?.showFreight?.();
      return;
    }
    if (target === "reports_low_stock") {
      App.showView("products");
      Products?.setMainTab?.("stock");
      Products?.setAttentionFilter?.("low_stock");
      return;
    }
    if (target === "reports_today") {
      App.showView("reports");
      Reports?.setMode?.("today");
      Reports?.setChip?.("daybook");
      return;
    }
    if (target === "returns") {
      App.showView("returns");
      return;
    }
    if (target === "people_customers") {
      App.showView("people");
      App.showPeopleTab?.("customers");
      return;
    }
    if (target === "people_vendors") {
      App.showView("people");
      App.showPeopleTab?.("vendors");
      return;
    }
    if (target === "products") {
      App.showView("products");
      return;
    }
    if (target === "setup") {
      App.showView("setup");
      return;
    }
    if (target === "reports_books") {
      App.showView("reports");
      Reports?.setMode?.("books");
      Reports?.setChip?.("ledgers");
      return;
    }
  }

  const ACTION_COPY = {
    customer_orders: { label: "Bill customers", hint: "Qty ready to bill", cta: "Bill" },
    vendor_orders: { label: "Vendor orders", hint: "Receive goods or bill vendors", cta: "Open" },
    collect: { label: "Collect cash", hint: "Customer dues", cta: "Collect" },
    pay_vendors: { label: "Pay vendors", hint: "Vendor dues", cta: "Pay" },
    freight: { label: "Freight dues", hint: "Agent dues after pick", cta: "Settle" },
    low_stock: { label: "Low stock", hint: "Needs reorder attention", cta: "View" },
    returns: { label: "Returns", hint: "Last 7 days", cta: "Open" },
  };

  function barPct(part, whole) {
    const a = Math.max(0, Number(part) || 0);
    const b = Math.max(a, Number(whole) || 0);
    if (b <= 0) return 0;
    return Math.min(100, Math.round((a / b) * 100));
  }

