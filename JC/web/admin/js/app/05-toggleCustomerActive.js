  async function toggleCustomerActive(id, makeActive) {
    const label = makeActive ? "restore to active" : "mark as inactive";
    if (!confirm(`${makeActive ? "Restore" : "Mark inactive"} this customer?`)) return;
    try {
      await api(`/customers/${id}`, { method: "PATCH", body: JSON.stringify({ is_active: makeActive }) });
      closeDetail();
      invalidateCache("/customers");
      invalidateCache("/stats");
      await loadCustomers();
      toast(`Customer ${makeActive ? "restored to active" : "marked inactive"}`, "success");
    } catch (e) { toast(e.message, "error"); }
  }

  async function restoreCustomer(id) {
    if (!confirm("Restore customer from recycle bin?")) return;
    try {
      await api(`/customers/${id}/restore`, { method: "POST" });
      closeDetail();
      invalidateCache("/customers");
      invalidateCache("/stats");
      await loadCustomers();
      toast("Customer restored", "success");
    } catch (e) { toast(e.message, "error"); }
  }

  async function deleteCustomer(id) {
    if (!confirm("Move customer to recycle bin? They cannot login until restored.")) return;
    try {
      await api(`/customers/${id}`, { method: "DELETE" });
      closeDetail(); closeEditModal();
      invalidateCache();
      await refreshAll();
      toast("Customer moved to recycle bin", "success");
    } catch (e) { toast(e.message, "error"); }
  }

  async function sendCredentials(id) {
    if (!confirm("Generate a new unique password and send via WhatsApp?")) return;
    try {
      const r = await api(`/customers/${id}/reset-password`, { method: "POST" });
      const msg = r.whatsapp_sent
        ? `New password sent${r.portal_password ? `: ${r.portal_password}` : ""}`
        : (r.message || "Password reset — WhatsApp failed");
      toast(msg, r.whatsapp_sent ? "success" : "error");
    } catch (e) { toast(e.message, "error"); }
  }

  async function resendWhatsApp(id) {
    try {
      const r = await api(`/customers/${id}/resend-whatsapp`, { method: "POST" });
      if (wizardForm?._result?.id === id) {
        wizardForm._result.whatsapp_sent = !!r.whatsapp_sent;
        wizardForm._result.whatsapp_error = r.whatsapp_error || null;
        if (r.portal_password) wizardForm._result.portal_password = r.portal_password;
        if (wizardStep === 4) renderWizard();
      }
      toast(r.whatsapp_sent ? "WhatsApp sent (new password)" : (r.whatsapp_error || "WhatsApp failed"), r.whatsapp_sent ? "success" : "error");
    } catch (e) { toast(e.message, "error"); }
  }

  // ── Recycle Bin ───────────────────────────────────────────────────
  async function loadRecycleBin() {
    recycleData = await api("/recycle-bin");
    const rs = TableUtils.state("recycle");
    rs.sort = "deleted";
    rs.dir = "desc";
    renderRecycleTabs();
    renderRecycleTable();
  }

  function setRecycleTab(tab) {
    recycleTab = tab;
    renderRecycleTabs();
    renderRecycleTable();
  }

  function renderRecycleTabs() {
    const items = [
      { id: "all", label: "All", count: recycleData.total },
      { id: "routes", label: "Routes", count: recycleData.routes.length },
      { id: "cities", label: "Cities", count: recycleData.cities.length },
      { id: "customers", label: "Customers", count: recycleData.customers.length },
      { id: "vendors", label: "Vendors", count: recycleData.vendors?.length || 0 },
      { id: "catalog", label: "Catalog", count: recycleData.catalog_products?.length || 0 },
      { id: "addons", label: "Add-ons", count: recycleData.addons?.length || 0 },
      { id: "receipts", label: "Receipts/Bills", count: recycleData.receipts?.length || 0 },
      { id: "debit_notes", label: "Debit Notes", count: recycleData.debit_notes?.length || 0 },
      { id: "customer_bills", label: "Customer Bills", count: recycleData.customer_bills?.length || 0 },
      { id: "customer_placements", label: "Customer Orders", count: recycleData.customer_placements?.length || 0 },
      { id: "customer_returns", label: "Customer Returns", count: recycleData.customer_returns?.length || 0 },
      ...(isAdmin() ? [{ id: "staff", label: "Staff", count: recycleData.staff?.length || 0 }] : []),
    ];
    if (typeof OrdersUI !== "undefined") {
      OrdersUI.actionChips({
        hostId: "recycle-tabs",
        items,
        active: recycleTab,
        onclickFn: "App.setRecycleTab",
      });
    } else {
      document.getElementById("recycle-tabs").innerHTML = items.map(it =>
        `<button class="ord-action-chip${recycleTab === it.id ? " active" : ""}" onclick="App.setRecycleTab('${it.id}')">${esc(it.label)} <span class="ord-action-count">${it.count}</span></button>`
      ).join("");
    }
  }

  // Restore (not just purge) is require_admin server-side for these types
  // (recycle_bin.py's restore_receipt_endpoint/restore_debit_note_endpoint/
  // restore_customer_bill_endpoint/restore_customer_placement_endpoint/
  // restore_customer_return_endpoint/restore_staff all depend on require_admin, not
  // recycle.write) — a recycle.write-but-not-admin staffer used to see a normal
  // Restore button here too and always got a 403.
  const ADMIN_ONLY_RECYCLE_TYPES = new Set(["receipt", "debit_note", "customer_bill", "customer_placement", "customer_return", "staff"]);
  const RECYCLE_COLS = [
    { key: "type", label: "Type", get: i => i.type },
    { key: "name", label: "Name", get: i => i.name },
    { key: "details", label: "Details", get: i => i.subtitle || "" },
    { key: "deleted", label: "Deleted", get: i => i.deleted_at || "" },
    { key: "_actions", label: "", filterable: false, sortable: false },
  ];

  function renderRecycleTable() {
    const el = document.getElementById("recycle-table");
    let items = [];
    if (recycleTab === "all" || recycleTab === "routes") items = items.concat(recycleData.routes.map(i => ({ ...i, type: "route" })));
    if (recycleTab === "all" || recycleTab === "cities") items = items.concat(recycleData.cities.map(i => ({ ...i, type: "city" })));
    if (recycleTab === "all" || recycleTab === "customers") items = items.concat(recycleData.customers.map(i => ({ ...i, type: "customer" })));
    if (recycleTab === "all" || recycleTab === "vendors") items = items.concat((recycleData.vendors || []).map(i => ({ ...i, type: "vendor" })));
    if (recycleTab === "all" || recycleTab === "catalog") items = items.concat((recycleData.catalog_products || []).map(i => ({ ...i, type: "catalog_product" })));
    if (recycleTab === "all" || recycleTab === "addons") items = items.concat((recycleData.addons || []).map(i => ({ ...i, type: "addon" })));
    if (recycleTab === "all" || recycleTab === "receipts") items = items.concat((recycleData.receipts || []).map(i => ({ ...i, type: "receipt" })));
    if (recycleTab === "all" || recycleTab === "debit_notes") items = items.concat((recycleData.debit_notes || []).map(i => ({ ...i, type: "debit_note" })));
    if (recycleTab === "all" || recycleTab === "customer_bills") items = items.concat((recycleData.customer_bills || []).map(i => ({ ...i, type: "customer_bill" })));
    if (recycleTab === "all" || recycleTab === "customer_placements") items = items.concat((recycleData.customer_placements || []).map(i => ({ ...i, type: "customer_placement" })));
    if (recycleTab === "all" || recycleTab === "customer_returns") items = items.concat((recycleData.customer_returns || []).map(i => ({ ...i, type: "customer_return" })));
    if (isAdmin() && (recycleTab === "all" || recycleTab === "staff")) items = items.concat((recycleData.staff || []).map(i => ({ ...i, type: "staff" })));

    if (!items.length) {
      el.innerHTML = (typeof HubUI !== "undefined" ? HubUI.emptyState : OrdersUI.emptyState)({
        title: "Recycle bin is empty",
        sub: "Deleted routes, cities, people, and products show up here.",
      });
      return;
    }
    const rows = TableUtils.apply(items, "recycle", RECYCLE_COLS);
    const typeBadge = t => ({ route: "badge-blue", city: "badge-green", customer: "badge-gray", vendor: "badge-amber", catalog_product: "badge-blue", addon: "badge-gray", staff: "badge-blue", receipt: "badge-amber", debit_note: "badge-red", customer_bill: "badge-amber", customer_placement: "badge-blue", customer_return: "badge-red" }[t] || "badge-gray");
    const canRecycleWrite = canWrite("recycle");
    // Purge (permanent delete) is require_admin server-side for EVERY entity type,
    // regardless of recycle.write — was only gating the button on recycle.write for
    // route/city/customer/vendor/catalog_product/addon, so a recycle.write-but-not-
    // admin staffer saw a "Delete Forever" button that always 403'd when clicked.
    const canRestore = i => isAdmin() || (canRecycleWrite && !ADMIN_ONLY_RECYCLE_TYPES.has(i.type));
    const canPurge = () => isAdmin();
    el.innerHTML = `<table class="data">${TableUtils.headerHtml("recycle", RECYCLE_COLS)}<tbody>
      ${rows.map(i => `<tr class="clickable" onclick="App.openRecycleDetail('${i.type}',${i.id})">
        <td><span class="badge ${typeBadge(i.type)}">${i.type}</span></td>
        <td><strong>${esc(i.name)}</strong></td>
        <td style="color:var(--muted);font-size:13px;">${esc(i.subtitle || "—")}</td>
        <td style="font-size:13px;">${fmtDate(i.deleted_at)}</td>
        <td onclick="event.stopPropagation()">
          ${canRestore(i) ? `<button class="btn btn-primary btn-sm" onclick="App.restoreItem('${i.type}',${i.id})">Restore</button>` : ""}
          ${canPurge() ? `<button class="btn btn-danger btn-sm" onclick="App.purgeItem('${i.type}',${i.id})">Delete Forever</button>` : ""}
          ${!canRestore(i) && !canPurge() ? "—" : ""}
        </td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  async function openRecycleDetail(type, id) {
    detailMode = `recycle-${type}`; detailId = id;
    let body = "";

    if (type === "route") {
      const r = await api(`/recycle-bin/routes/${id}`);
      body = `<div class="review-grid" style="margin-bottom:20px;">
        ${reviewRow("Name", r.name)}${reviewRow("Notes", r.notes)}
        ${reviewRow("Cities", r.city_count)}${reviewRow("Customers", r.customer_count)}
        ${reviewRow("Deleted", fmtDate(r.deleted_at))}
      </div>
      <div class="detail-section"><h4>Cities (${r.cities.length})</h4>
        ${r.cities.length ? r.cities.map(c => `<div class="review-row"><span>${esc(c.name)}</span><span>${c.is_active ? "active" : "deleted"}</span></div>`).join("") : "<p style='color:var(--muted)'>None</p>"}
      </div>`;
    } else if (type === "city") {
      const c = await api(`/recycle-bin/cities/${id}`);
      body = `<div class="review-grid" style="margin-bottom:20px;">
        ${reviewRow("City", c.name)}${reviewRow("Route", c.route_name)}
        ${reviewRow("Customers", c.customer_count)}${reviewRow("Deleted", fmtDate(c.deleted_at))}
      </div>
      <div class="detail-section"><h4>Customers (${c.customers.length})</h4>
        ${c.customers.length ? c.customers.map(cu => `<div class="review-row"><span>${esc(cu.business_name)}</span><span>${esc(cu.phone)}</span></div>`).join("") : "<p style='color:var(--muted)'>None</p>"}
      </div>`;
    } else if (type === "customer") {
      const c = await api(`/recycle-bin/customers/${id}`);
      body = `<div class="profile-hero" style="margin:-24px -24px 24px;border-radius:0;">
        <h2>${esc(c.business_name)}</h2>
        <p>${esc(c.person_name || "No contact person")}</p>
        <div class="profile-meta"><span class="badge badge-blue">${esc(c.phone)}</span></div>
      </div>
      <div class="review-grid">
        ${reviewRow("Alias", c.alias)}${reviewRow("City", c.city_name)}
        ${reviewRow("Route", c.route_name)}${reviewRow("GST", c.gst_number)}
        ${reviewRow("Address", c.address)}${reviewRow("Deleted", fmtDate(c.deleted_at))}
      </div>`;
    } else if (type === "vendor") {
      const v = await api(`/recycle-bin/vendors/${id}`);
      body = `<div class="profile-hero" style="margin:-24px -24px 24px;border-radius:0;">
        <h2>${esc(v.business_name)}</h2>
        <p>${esc(v.person_name || "No contact")}</p>
        <div class="profile-meta"><span class="badge badge-blue">${esc(v.phone)}</span></div>
      </div>
      <div class="review-grid">
        ${reviewRow("City", v.city_name)}${reviewRow("GST", v.gst_number)}
        ${reviewRow("Address", v.address)}${reviewRow("Deleted", fmtDate(v.deleted_at))}
      </div>`;
    } else if (type === "catalog_product") {
      const p = await api(`/recycle-bin/catalog-products/${id}`);
      body = `<div class="review-grid">
        ${reviewRow("Product ID", p.our_product_id)}${reviewRow("Vendor", p.vendor_name)}
        ${reviewRow("Buy Price", fmtPersonMoney(p.buying_price))}${reviewRow("Deleted", fmtDate(p.deleted_at))}
      </div>`;
    } else if (type === "addon") {
      const a = await api(`/recycle-bin/addons/${id}`);
      body = `<div class="review-grid">
        ${reviewRow("Add-on ID", a.our_product_id)}
        ${reviewRow("Deleted", fmtDate(a.deleted_at))}
      </div>`;
    } else if (type === "receipt") {
      const r = await api(`/stock/receipts/${id}`);
      body = `<div class="review-grid" style="margin-bottom:20px;">
        ${reviewRow("Type", r.bill_status === "billed" ? "Bill" : "Receipt")}
        ${reviewRow("Order receipt #", r.order_receipt_number)}${reviewRow("Bill number", r.bill_number)}
        ${reviewRow("Bill amount", r.bill_amount != null ? "₹" + r.bill_amount : "—")}
        ${reviewRow("Net payable", r.net_payable != null ? "₹" + r.net_payable : "—")}
        ${reviewRow("Deleted", fmtDate(r.deleted_at))}${reviewRow("Reason", r.deleted_reason || "—")}
      </div>
      <div class="detail-section"><h4>Lines (${(r.lines || []).length})</h4>
        ${(r.lines || []).length ? r.lines.map(l => `<div class="review-row"><span>${esc(l.our_product_id)}</span><span>recv ${l.quantity_received} / bill ${l.quantity_billed || 0}</span></div>`).join("") : "<p style='color:var(--muted)'>None</p>"}
      </div>`;
    } else if (type === "debit_note") {
      const d = await api(`/debit-notes/${id}`);
      body = `<div class="review-grid">
        ${reviewRow("Vendor", d.vendor_label)}${reviewRow("Bill number", d.bill_number)}
        ${reviewRow("Type", d.note_type)}${reviewRow("Direction", d.direction)}
        ${reviewRow("Amount", "₹" + d.amount)}${reviewRow("Note", d.notes || "—")}
        ${reviewRow("Deleted", fmtDate(d.deleted_at))}${reviewRow("Reason", d.deleted_reason || "—")}
      </div>`;
    } else if (type === "customer_bill") {
      const b = await api(`/customer-orders/bills/${id}`);
      body = `<div class="review-grid" style="margin-bottom:20px;">
        ${reviewRow("Bill number", b.bill_number)}${reviewRow("Grand total", "₹" + b.grand_total)}
        ${reviewRow("Cancelled", b.cancelled_at ? fmtDate(b.cancelled_at) : "—")}${reviewRow("Cancel reason", b.cancel_reason || "—")}
        ${reviewRow("Deleted", fmtDate(b.deleted_at))}${reviewRow("Reason", b.deleted_reason || "—")}
      </div>
      <div class="detail-section"><h4>Lines (${(b.lines || []).length})</h4>
        ${(b.lines || []).length ? b.lines.map(l => `<div class="review-row"><span>${esc(l.our_product_id)}</span><span>qty ${l.quantity_shipped} · ₹${l.line_total}</span></div>`).join("") : "<p style='color:var(--muted)'>None</p>"}
      </div>
      <p style="margin-top:12px;font-size:12px;color:var(--muted);">Restoring un-hides the bill only — it stays cancelled if it already was.</p>`;
    } else if (type === "customer_placement") {
      const p = await api(`/customer-orders/placements/${id}`);
      body = `<div class="review-grid" style="margin-bottom:20px;">
        ${reviewRow("Status", p.status)}${reviewRow("Cancel reason", p.cancel_reason || "—")}
        ${reviewRow("Deleted", fmtDate(p.deleted_at))}${reviewRow("Reason", p.deleted_reason || "—")}
      </div>
      <div class="detail-section"><h4>Lines (${(p.lines || []).length})</h4>
        ${(p.lines || []).length ? p.lines.map(l => `<div class="review-row"><span>${esc(l.our_product_id)}</span><span>qty ${l.quantity} · billed ${l.quantity_billed || 0}</span></div>`).join("") : "<p style='color:var(--muted)'>None</p>"}
      </div>
      <p style="margin-top:12px;font-size:12px;color:var(--muted);">Restoring un-hides the order only — it stays cancelled if it already was.</p>`;
    } else if (type === "customer_return") {
      const r = await api(`/customer-returns/${id}`);
      body = `<div class="review-grid" style="margin-bottom:20px;">
        ${reviewRow("Return number", r.return_number)}${reviewRow("Credit amount", "₹" + r.credit_amount)}
        ${reviewRow("Customer", r.customer_label)}${reviewRow("Notes", r.notes || "—")}
        ${reviewRow("Deleted", fmtDate(r.deleted_at))}${reviewRow("Reason", r.deleted_reason || "—")}
      </div>
      <div class="detail-section"><h4>Lines (${(r.lines || []).length})</h4>
        ${(r.lines || []).length ? r.lines.map(l => `<div class="review-row"><span>${esc(l.our_product_id)}</span><span>qty ${l.quantity_returned} · ₹${l.line_calculated}</span></div>`).join("") : "<p style='color:var(--muted)'>None</p>"}
      </div>`;
    }

    // Purge is require_admin server-side for every type (see recycle-bin list view
    // for why); restore is also admin-only for the same subset as the list view
    // (see ADMIN_ONLY_RECYCLE_TYPES) — everything else only needs recycle.write.
    const canRestoreThis = isAdmin() || (canWrite("recycle") && !ADMIN_ONLY_RECYCLE_TYPES.has(type));
    const canPurgeThis = isAdmin();
    openDetail(`Deleted ${type}`, body,
      `${canRestoreThis ? `<button class="btn btn-primary" style="flex:1;" onclick="App.restoreItem('${type}',${id})">Restore</button>` : ""}
       ${canPurgeThis ? `<button class="btn btn-danger" onclick="App.purgeItem('${type}',${id})">Delete Forever</button>` : ""}
       <button class="btn btn-secondary" onclick="App.closeDetail()">Close</button>`,
      "md"
    );
  }

  const RESTORE_PATHS = { route: "routes", city: "cities", customer: "customers", vendor: "vendors", catalog_product: "catalog-products", addon: "addons", staff: "staff", receipt: "receipts", debit_note: "debit-notes", customer_bill: "customer-bills", customer_placement: "customer-placements", customer_return: "customer-returns" };

  async function restoreItem(type, id) {
    if (!confirm(`Restore this ${type}?`)) return;
    const path = RESTORE_PATHS[type] || `${type}s`;
    try {
      await api(`/recycle-bin/${path}/${id}/restore`, { method: "POST" });
      closeDetail();
      invalidateCache();
      if (["receipt", "debit_note"].includes(type)) {
        invalidateCache("/vendor-orders");
        invalidateCache("/accounts-payable");
      }
      if (["customer_bill", "customer_placement", "customer_return"].includes(type)) {
        invalidateCache("/customer-orders");
        invalidateCache("/accounts-receivable");
        invalidateCache("/customer-returns");
      }
      await refreshAll();
      if (peopleTab === "vendors") await Vendors.load();
      if (document.getElementById("view-people") && !document.getElementById("view-people").classList.contains("hidden") && peopleTab === "customers") {
        await loadCustomers();
      }
      if (document.getElementById("view-recycle") && !document.getElementById("view-recycle").classList.contains("hidden")) {
        await loadRecycleBin();
      }
      const LABELS = { receipt: "Receipt/bill", debit_note: "Debit note", customer_bill: "Bill", customer_placement: "Order", customer_return: "Return" };
      toast(`${LABELS[type] || type} restored`, "success");
    } catch (e) { toast(e.message, "error"); }
  }

  async function purgeItem(type, id) {
    // Type-to-confirm — a plain confirm() was too easy to click through for a truly
    // irreversible, admin-only action that can wipe historical accounting records.
    const typed = prompt(
      `Permanently delete this ${type.replace(/_/g, " ")}? This CANNOT be undone and is not the same as moving to the recycle bin.\n\nType DELETE to confirm:`,
      "",
    );
    if (typed === null) return;
    if (typed.trim().toUpperCase() !== "DELETE") {
      toast("Not deleted — you must type DELETE to confirm", "error");
      return;
    }
    const path = RESTORE_PATHS[type] || `${type}s`;
    try {
      await api(`/recycle-bin/${path}/${id}`, { method: "DELETE" });
      closeDetail();
      invalidateCache();
      if (["receipt", "debit_note"].includes(type)) {
        invalidateCache("/vendor-orders");
        invalidateCache("/accounts-payable");
      }
      if (["customer_bill", "customer_placement", "customer_return"].includes(type)) {
        invalidateCache("/customer-orders");
        invalidateCache("/accounts-receivable");
        invalidateCache("/customer-returns");
      }
      await loadRecycleBin();
      await updateHubCounts();
      toast("Permanently deleted", "success");
    } catch (e) { toast(e.message, "error"); }
  }

  function renderLookupSections() {
    const el = document.getElementById("lookup-sections");
    if (!el) return;
    const types = [
      ["category", "Categories", "category", "C", "e.g. Wedding, Birthday, Festival"],
      ["series", "Series", "series", "S", "e.g. Premium, Economy, Gold"],
      ["unit", "Units", "unit", "U", "e.g. pcs, pack, box"],
      ["year_group", "Year Groups", "year group", "Y", "e.g. 2025, 2026"],
    ];
    const canSetupWrite = canWrite("setup");
    el.innerHTML = types.map(([t, label, singular, letter, hint]) => {
      const items = lookups.filter(l => l.lookup_type === t);
      const chips = items.length
        ? items.map(i => `<span class="lookup-chip">
            <span class="lookup-chip-text">${esc(i.value)}</span>
            ${canSetupWrite ? `<button type="button" class="lookup-chip-edit" title="Edit" onclick="App.editLookup(${i.id})">Edit</button>
            <button type="button" class="lookup-chip-x" title="Remove" onclick="App.deleteLookup(${i.id})">×</button>` : ""}
          </span>`).join("")
        : `<p class="lookup-empty">No ${label.toLowerCase()} yet. Add the first one below.</p>`;
      return `<section class="lookup-card">
        <div class="lookup-card-head">
          <span class="lookup-card-letter">${letter}</span>
          <div>
            <h3 class="lookup-card-title">${label}</h3>
            <p class="lookup-card-hint">${hint}</p>
          </div>
          <span class="lookup-card-count">${items.length}</span>
        </div>
        <div class="lookup-chip-list">${chips}</div>
        ${canSetupWrite ? `<form class="lookup-add-row" onsubmit="event.preventDefault();App.submitLookup('${t}');">
          <input id="lookup-input-${t}" class="input lookup-add-input" type="text" maxlength="80" placeholder="Type new ${singular}…" autocomplete="off" />
          <button type="submit" class="btn btn-primary">Add</button>
        </form>` : ""}
      </section>`;
    }).join("");
  }

  async function submitLookup(type) {
    const input = document.getElementById(`lookup-input-${type}`);
    const val = (input?.value || "").trim();
    if (!val) {
      toast("Enter a name first", "error");
      input?.focus();
      return;
    }
    try {
      await api("/lookups", { method: "POST", body: JSON.stringify({ lookup_type: type, value: val }) });
      invalidateCache("/lookups");
      lookups = await api("/lookups", {}, 0);
      renderLookupSections();
      updateSetupHubCounts();
      toast("Added", "success");
      const next = document.getElementById(`lookup-input-${type}`);
      next?.focus();
    } catch (e) { toast(e.message, "error"); }
  }

  async function addLookup(type) {
    return submitLookup(type);
  }

  async function editLookup(id) {
    const row = lookups.find(l => l.id === id);
    if (!row) return;
    const next = prompt(`Rename “${row.value}”`, row.value);
    if (next == null) return;
    const val = next.trim();
    if (!val) return toast("Name required", "error");
    if (val === row.value) return;
    try {
      await api(`/lookups/${id}`, { method: "PATCH", body: JSON.stringify({ value: val }) });
      invalidateCache("/lookups");
      invalidateCache("/catalog");
      invalidateCache("/stock");
      lookups = await api("/lookups", {}, 0);
      renderLookupSections();
      updateSetupHubCounts();
      toast("Updated", "success");
    } catch (e) { toast(e.message, "error"); }
  }

  async function deleteLookup(id) {
    const row = lookups.find(l => l.id === id);
    const label = row ? row.value : "this option";
    if (!confirm(`Remove “${label}”? Products already using it keep the old value.`)) return;
    try {
      await api(`/lookups/${id}`, { method: "DELETE" });
      invalidateCache("/lookups");
      lookups = await api("/lookups", {}, 0);
      renderLookupSections();
      updateSetupHubCounts();
      toast("Removed", "success");
    } catch (e) { toast(e.message, "error"); }
  }

  function getVendors() { return vendors; }
  function getLookups() { return lookups; }

  function setVendors(list) { vendors = list || []; }

  const sharedCtx = () => ({
    api, toast, esc, fmtDate, fmtDay, timeAgo, reviewRow, productIdLabel, changeHistoryTable, openDetail,
    closeDetail: () => closeDetail(), detailBack, detailFooterChild, ledgerDetailCard, bindLedgerRowClicks,
    entityLedgerTableHtml, activityTableHtml, loadActivity,
    getCities: () => cities,
    getVendors: () => vendors,
    setVendors,
    getLookups: () => lookups,
    refreshStats: refreshAll,
    invalidateCache,
    peekCache,
    showLoading, hideLoading,
    uploadImage,
    apiBase: () => API,
    headers,
    checkBackend,
    can, canWrite, canRead, isAdmin,
    get staffUser() { return staffUser; },
    showView,
    showPeopleTab,
  });

  function openCustomerWizard() {
    if (!cities.length) {
      toast("Add cities in Setup first", "error");
      return;
    }
    wizardStep = 1;
    wizardForm = {};
    document.getElementById("wizard").classList.remove("hidden");
    renderWizard();
  }
  function closeWizard() { document.getElementById("wizard").classList.add("hidden"); }

