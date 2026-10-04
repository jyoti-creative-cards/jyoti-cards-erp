  async function refreshAll() {
    showLoading();
    try {
      // Boot path: skip full /customers (1.4k rows / ~700KB) — load when People opens.
      ["/routes", "/cities", "/vendors", "/stats"].forEach(p => invalidateCache(p));
      const [r, c, vend, stats] = await Promise.all([
        api("/routes", {}, 120000).catch(() => []),
        api("/cities", {}, 120000).catch(() => []),
        api("/vendors", {}, 120000).catch(() => []),
        api("/stats", {}, 30000).catch(() => null),
      ]);
      routes = r; cities = c; vendors = vend;
      if (typeof Catalog !== "undefined" && Catalog.setVendors) Catalog.setVendors(vend);
      // Keep any cached customers; otherwise prefetch in background after paint.
      const cachedCust = peekCache("/customers");
      if (Array.isArray(cachedCust) && cachedCust.length) {
        customers = cachedCust;
      } else {
        api("/customers", {}, 120000)
          .then((cust) => { customers = cust || []; })
          .catch(() => {});
      }
      await updateHubCounts();
      updateSetupHubCounts();
      if (isAdmin()) {
        api("/bill-series", {}, 120000).then(bs => {
          const el = document.getElementById("hub-billseries-count");
          if (el) el.textContent = `${(bs || []).length} series`;
        }).catch(() => {});
        api("/freight-agents", {}, 120000).then(fa => {
          const el = document.getElementById("hub-freight-count");
          if (el) el.textContent = `${(fa || []).length} agent${(fa || []).length === 1 ? "" : "s"}`;
        }).catch(() => {});
      }
      renderRoutesTable();
      renderCitiesTable();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      hideLoading();
    }
  }

  function renderPeopleCustomerSearch() {
    const slot = document.getElementById("people-customers-search-slot");
    if (!slot) return;
    // Only render once — re-rendering on every keystroke destroys the focused input
    if (document.getElementById("search-input")) return;
    slot.innerHTML = HubUI.searchBar({
      id: "search-input",
      value: "",
      placeholder: "Search name, phone, #number…",
      oninput: "App.debouncedLoadCustomers()",
    });
  }

  function renderPeopleVendorSearch() {
    const slot = document.getElementById("people-vendors-search-slot");
    if (!slot) return;
    if (document.getElementById("vendor-search-input")) return;
    slot.innerHTML = HubUI.searchBar({
      id: "vendor-search-input",
      value: "",
      placeholder: "Search name, phone, alias…",
      oninput: "App.debouncedVendorSearch()",
    });
  }

  function toggleInactiveCustomers() {
    showInactiveCustomers = !showInactiveCustomers;
    if (!showInactiveCustomers) customerStatusTab = "active"; // reset to active when hiding
    // Update toggle switch visuals
    document.getElementById("cst-inactive-track")?.classList.toggle("is-on", showInactiveCustomers);
    // Show/hide Active/Inactive tabs
    const tabsEl = document.getElementById("customer-status-tabs");
    if (tabsEl) tabsEl.style.display = showInactiveCustomers ? "" : "none";
    invalidateCache("/customers");
    loadCustomers();
  }

  function setCustomerStatusTab(tab) {
    customerStatusTab = tab;
    customerMissingPhone = false;
    document.getElementById("cst-tab-active")?.classList.toggle("active", tab === "active");
    document.getElementById("cst-tab-inactive")?.classList.toggle("active", tab === "inactive");
    document.getElementById("cst-tab-missing")?.classList.toggle("active", false);
    invalidateCache("/customers");
    loadCustomers();
  }

  function toggleMissingPhoneFilter() {
    customerMissingPhone = !customerMissingPhone;
    document.getElementById("cst-tab-missing")?.classList.toggle("active", customerMissingPhone);
    renderCustomersTable();
  }

  async function loadCustomers() {
    renderPeopleCustomerSearch(); // no-op if input already exists
    const q = document.getElementById("search-input")?.value.trim() || "";
    // When toggle is off: only active customers (search still works across active only)
    // When toggle is on: use the active/inactive tab selection
    let statusParam;
    if (!showInactiveCustomers) {
      statusParam = "status=active";
    } else {
      statusParam = `status=${customerStatusTab}`;
    }
    const searchParam = q ? `&search=${encodeURIComponent(q)}` : "";
    customers = await api(`/customers?${statusParam}${searchParam}`, {}, q ? 0 : 120000);
    renderCustomersTable();
  }

  async function reloadCustomers() {
    invalidateCache("/customers");
    invalidateCache("/stats");
    showLoading();
    try {
      await loadCustomers();
      await updateHubCounts();
      toast("Customer list refreshed", "success");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      hideLoading();
    }
  }

  // ── Routes ────────────────────────────────────────────────────────
  const ROUTE_COLS = [
    { key: "name", label: "Name", get: r => r.name },
    { key: "cities", label: "Cities", get: r => String(r.city_count) },
    { key: "customers", label: "Customers", get: r => String(r.customer_count || 0) },
    { key: "notes", label: "Notes", get: r => r.notes || "" },
    { key: "_actions", label: "", filterable: false, sortable: false },
  ];

  function renderRoutesTable() {
    const el = document.getElementById("routes-table");
    if (!routes.length) {
      el.innerHTML = HubUI.emptyState({
        title: "No routes yet",
        sub: "Add a delivery route, then link cities.",
        ctaHtml: canWrite("setup")
          ? `<button class="btn btn-primary" onclick="App.openRouteModal()">+ Add Route</button>`
          : "",
      });
      return;
    }
    const rows = TableUtils.apply(routes, "routes", ROUTE_COLS);
    el.innerHTML = `<table class="data">${TableUtils.headerHtml("routes", ROUTE_COLS)}<tbody>
      ${rows.map(r => `<tr class="clickable" onclick="App.openRouteDetail(${r.id})">
        <td><strong>${esc(r.name)}</strong></td>
        <td><span class="badge badge-blue">${r.city_count} cities</span></td>
        <td><span class="badge badge-gray">${r.customer_count || 0} customers</span></td>
        <td style="color:var(--muted);font-size:13px;">${esc(r.notes || "—")}</td>
        <td onclick="event.stopPropagation()">${canWrite("setup") ? `<div class="actions">
          <button class="btn btn-ghost btn-sm" onclick="App.openRouteModal(${r.id})">Edit</button>
          <button class="btn btn-danger btn-sm" onclick="App.deleteRoute(${r.id},${JSON.stringify(r.name)})">Delete</button>
        </div>` : ""}</td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  async function openRouteDetail(id) {
    const r = await api(`/routes/${id}`);
    detailMode = "route"; detailId = id;
    openDetail("Route Details", `
      <div class="review-grid" style="margin-bottom:20px;">
        ${reviewRow("Name", r.name)}
        ${reviewRow("Notes", r.notes)}
        ${reviewRow("Cities", r.city_count)}
        ${reviewRow("Customers", r.customer_count)}
        ${reviewRow("Created", fmtDate(r.created_at))}
      </div>
      <div class="detail-section">
        <h4>Cities on this route (${r.cities.length})</h4>
        ${r.cities.length ? `<table class="data"><thead><tr><th>City</th><th>Customers</th></tr></thead><tbody>
          ${r.cities.map(c => `<tr class="clickable" onclick="App.closeDetail();App.openCityDetail(${c.id})"><td>${esc(c.name)}</td><td>${c.customer_count}</td></tr>`).join("")}
        </tbody></table>` : '<p style="color:var(--muted);font-size:14px;">No cities assigned yet.</p>'}
      </div>`,
      `${canWrite("setup") ? `<button class="btn btn-danger btn-sm" onclick="App.deleteRoute(${id},${JSON.stringify(r.name)})">Delete</button>
       <button class="btn btn-secondary" onclick="App.closeDetail();App.openRouteModal(${id})">Edit</button>` : ""}
       <button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
      "lg"
    );
  }

  function openRouteModal(id) {
    const editing = id ? routes.find(r => r.id === id) : null;
    document.getElementById("modal-title").textContent = editing ? "Edit Route" : "Add Route";
    document.getElementById("modal-body").innerHTML = `
      <div style="display:grid;gap:16px;">
        <div><label class="label">Route Name *</label><input id="m-route-name" class="input" value="${esc(editing?.name || "")}" /></div>
        <div><label class="label">Notes</label><input id="m-route-notes" class="input" value="${esc(editing?.notes || "")}" /></div>
      </div>`;
    document.getElementById("modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="App.closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="App.saveRoute(${id || "null"})">${editing ? "Save" : "Create"}</button>`;
    document.getElementById("modal").classList.remove("hidden");
  }

  async function saveRoute(id) {
    const name = document.getElementById("m-route-name").value.trim();
    if (!name) return toast("Route name required", "error");
    const notes = document.getElementById("m-route-notes").value.trim() || null;
    try {
      if (id) await api(`/routes/${id}`, { method: "PATCH", body: JSON.stringify({ name, notes }) });
      else await api("/routes", { method: "POST", body: JSON.stringify({ name, notes }) });
      closeModal(); closeDetail();
      await refreshAll();
      toast(id ? "Route updated" : "Route created", "success");
    } catch (e) { toast(e.message, "error"); }
  }

  async function deleteRoute(id, name) {
    if (!confirm(`Move route "${name}" to recycle bin?`)) return;
    try {
      await api(`/routes/${id}`, { method: "DELETE" });
      closeDetail(); closeModal();
      await refreshAll();
      toast("Route moved to recycle bin", "success");
    } catch (e) { toast(e.message, "error"); }
  }

  // ── Cities ────────────────────────────────────────────────────────
  const CITY_COLS = [
    { key: "name", label: "City", get: c => c.name },
    { key: "route", label: "Route", get: c => c.route_name || "Unassigned" },
    { key: "customers", label: "Customers", get: c => String(c.customer_count || 0) },
    { key: "_actions", label: "", filterable: false, sortable: false },
  ];

  function renderCitiesTable() {
    const el = document.getElementById("cities-table");
    if (!cities.length) {
      el.innerHTML = HubUI.emptyState({
        title: "No cities yet",
        sub: "Each city maps to one delivery route.",
        ctaHtml: canWrite("setup")
          ? `<button class="btn btn-primary" onclick="App.openCityModal()">+ Add City</button>`
          : "",
      });
      return;
    }
    const rows = TableUtils.apply(cities, "cities", CITY_COLS);
    el.innerHTML = `<table class="data">${TableUtils.headerHtml("cities", CITY_COLS)}<tbody>
      ${rows.map(c => `<tr class="clickable" onclick="App.openCityDetail(${c.id})">
        <td><strong>${esc(c.name)}</strong></td>
        <td>${c.route_name ? `<span class="badge badge-green">${esc(c.route_name)}</span>` : '<span class="badge badge-amber">Unassigned</span>'}</td>
        <td>${c.customer_count || 0}</td>
        <td onclick="event.stopPropagation()">${canWrite("setup") ? `<div class="actions">
          <button type="button" class="btn btn-ghost btn-sm" onclick="event.stopPropagation();App.openCityModal(${c.id})">Edit</button>
          <button type="button" class="btn btn-danger btn-sm" onclick="event.stopPropagation();App.deleteCity(${c.id})">Delete</button>
        </div>` : ""}</td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  async function openCityDetail(id) {
    const c = await api(`/cities/${id}`);
    detailMode = "city"; detailId = id;
    openDetail("City Details", `
      <div class="review-grid" style="margin-bottom:20px;">
        ${reviewRow("City", c.name)}
        ${reviewRow("Route", c.route_name || "Unassigned")}
        ${reviewRow("Customers", c.customer_count)}
        ${reviewRow("Created", fmtDate(c.created_at))}
      </div>
      <div class="detail-section">
        <h4>Customers in this city (${c.customers.length})</h4>
        ${c.customers.length ? `<table class="data"><thead><tr><th>Business</th><th>Phone</th></tr></thead><tbody>
          ${c.customers.map(cu => `<tr class="clickable" onclick="App.closeDetail();App.openCustomerDetail(${cu.id})"><td>${esc(cu.business_name)}</td><td>${esc(cu.phone)}</td></tr>`).join("")}
        </tbody></table>` : '<p style="color:var(--muted);font-size:14px;">No customers in this city.</p>'}
      </div>`,
      `${canWrite("setup") ? `<button type="button" class="btn btn-danger btn-sm" onclick="App.deleteCity(${id})">Delete</button>
       <button type="button" class="btn btn-secondary" onclick="App.closeDetail();App.openCityModal(${id})">Edit</button>` : ""}
       <button type="button" class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
      "lg"
    );
  }

  function openCityModal(id) {
    const editing = id ? cities.find(c => c.id === id) : null;
    const routeOpts = routes.map(r => `<option value="${r.id}" ${editing?.route_id === r.id ? "selected" : ""}>${esc(r.name)}</option>`).join("");
    document.getElementById("modal-title").textContent = editing ? "Edit City" : "Add City";
    document.getElementById("modal-body").innerHTML = `
      <div style="display:grid;gap:16px;">
        <div><label class="label">City Name *</label><input id="m-city-name" class="input" value="${esc(editing?.name || "")}" /></div>
        <div><label class="label">Route</label>
          <select id="m-city-route" class="input">
            <option value="" ${!editing?.route_id ? "selected" : ""}>— No route —</option>
            ${routeOpts}
          </select>
          <p style="margin:6px 0 0;font-size:12px;color:var(--muted);">Clear route to leave city unassigned.</p>
        </div>
      </div>`;
    document.getElementById("modal-footer").innerHTML = `
      <button type="button" class="btn btn-secondary" onclick="App.closeModal()">Cancel</button>
      <button type="button" class="btn btn-primary" onclick="App.saveCity(${id || "null"})">${editing ? "Save" : "Create"}</button>`;
    document.getElementById("modal").classList.remove("hidden");
  }

  async function saveCity(id) {
    const name = document.getElementById("m-city-name").value.trim();
    const rawRoute = document.getElementById("m-city-route").value;
    const route_id = rawRoute ? parseInt(rawRoute, 10) : null;
    if (!name) return toast("City name required", "error");
    try {
      if (id) await api(`/cities/${id}`, { method: "PATCH", body: JSON.stringify({ name, route_id }) });
      else await api("/cities", { method: "POST", body: JSON.stringify({ name, route_id }) });
      closeModal(); closeDetail();
      await refreshAll();
      toast(id ? "City updated" : "City created", "success");
    } catch (e) { toast(e.message, "error"); }
  }

  async function deleteCity(id) {
    const city = cities.find(c => c.id === id);
    const label = city?.name || `#${id}`;
    if (!confirm(`Move city "${label}" to recycle bin?`)) return;
    try {
      await api(`/cities/${id}`, { method: "DELETE" });
      closeDetail(); closeModal();
      await refreshAll();
      toast("City moved to recycle bin", "success");
    } catch (e) { toast(e.message, "error"); }
  }

  // ── Customers ─────────────────────────────────────────────────────
  const CUSTOMER_COLS = [
    { key: "party_number", label: "#", get: c => c.party_number || 0, exactNumeric: true, numeric: true },
    { key: "business", label: "Business", get: c => `${c.business_name} ${c.person_name || ""}` },
    { key: "city", label: "City / Route", get: c => `${c.city_name || ""} ${c.route_name || ""}` },
    { key: "financials", label: "Financials", filterable: false, sortable: false },
    { key: "phone", label: "Phone", get: c => c.phone },
    { key: "alias", label: "Alias", get: c => c.alias || "" },
    { key: "_actions", label: "", filterable: false, sortable: false },
  ];

  function renderFinancialsCell(c) {
    const limit = c.credit_limit !== null && c.credit_limit !== undefined ? Number(c.credit_limit) : null;
    const outstanding = c.outstanding_balance !== null && c.outstanding_balance !== undefined ? Number(c.outstanding_balance) : null;
    const available = c.available_credit !== null && c.available_credit !== undefined ? Number(c.available_credit) : null;
    const trackOnly = limit !== null && limit === 0;
    const hasLimit = limit !== null && limit > 0;
    const fmt = n => "₹" + Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: 0 });

    if (outstanding === null && !hasLimit) return '<span style="color:var(--muted);">—</span>';

    if (trackOnly) {
      if (outstanding === null) return '<span style="color:var(--muted);">—</span>';
      const outColor = outstanding > 0 ? "var(--red,#dc2626)" : outstanding < 0 ? "var(--green,#16a34a)" : "var(--muted)";
      return `<span style="font-size:12px;color:var(--muted);">Due</span>
        <span style="font-weight:600;color:${outColor};margin-left:4px;">${fmt(outstanding)}</span>`;
    }

    const parts = [];
    if (hasLimit) {
      parts.push(`<span style="font-size:11px;color:var(--muted);">Limit</span> <span style="font-size:12px;">₹${limit.toLocaleString("en-IN", { maximumFractionDigits: 0 })}${c.credit_override ? ' <span class="badge badge-amber" style="font-size:10px;">OVR</span>' : ""}</span>`);
    }
    if (outstanding !== null) {
      const outColor = outstanding > 0 ? "var(--red,#dc2626)" : outstanding < 0 ? "var(--green,#16a34a)" : "var(--muted)";
      parts.push(`<span style="font-size:11px;color:var(--muted);">Due</span> <span style="font-size:12px;font-weight:600;color:${outColor};">${fmt(outstanding)}</span>`);
    }
    if (available !== null) {
      const avColor = available >= 0 ? "var(--green,#16a34a)" : "var(--red,#dc2626)";
      parts.push(`<span style="font-size:11px;color:var(--muted);">Avail</span> <span style="font-size:12px;color:${avColor};">${fmt(available)}</span>`);
    }
    return parts.join('<br>');
  }

  // Extract "other notes" from notes field — stored before " | Bills:" separator
  function getOtherNotes(c) {
    if (!c.notes) return "";
    const first = c.notes.split(" | ")[0] || "";
    return first.startsWith("Bills:") ? "" : first;
  }

  // Party badges: marker_1 + marker_2 + other_notes + payment_type(CASH only if not already in markers)
  function partyBadgesHtml(c, opts) {
    const parts = [];
    if (c.marker_1) {
      parts.push(`<span class="badge badge-blue" style="font-size:10px;padding:2px 5px;">${esc(c.marker_1)}</span>`);
    }
    if (c.marker_2) {
      parts.push(`<span class="badge badge-amber" style="font-size:10px;padding:2px 5px;">${esc(c.marker_2)}</span>`);
    }
    const otherNotes = getOtherNotes(c);
    if (otherNotes) {
      parts.push(`<span class="badge badge-green" style="font-size:10px;padding:2px 5px;">${esc(otherNotes)}</span>`);
    }
    const allMarkers = [(c.marker_1 || ""), (c.marker_2 || ""), otherNotes].join(" ").toUpperCase();
    if (c.payment_type === "CASH" && !allMarkers.includes("CASH")) {
      parts.push(`<span class="badge badge-amber" style="font-size:10px;padding:2px 5px;">CASH</span>`);
    }
    return parts.join(" ");
  }

  function renderCustomersTable() {
    const el = document.getElementById("customers-table");
    if (!customers.length) {
      el.innerHTML = (typeof HubUI !== "undefined" ? HubUI.emptyState : OrdersUI.emptyState)({
        title: "No customers yet",
        sub: "Add dealers you sell to.",
        ctaHtml: canWrite("customers")
          ? `<button class="btn btn-primary btn-lg" onclick="App.openCustomerWizard()">+ Create First Customer</button>`
          : "",
      });
      return;
    }
    const visibleCustomers = customerMissingPhone
      ? customers.filter(c => c.phone && c.phone.startsWith("000"))
      : customers;
    const rows = TableUtils.apply(visibleCustomers, "customers", CUSTOMER_COLS);
    el.innerHTML = `<table class="data">${TableUtils.headerHtml("customers", CUSTOMER_COLS)}<tbody>
      ${rows.map(c => {
        const missingPh = c.phone && c.phone.startsWith("000");
        const badges = partyBadgesHtml(c);
        return `<tr class="clickable" onclick="App.openCustomerDetail(${c.id})">
        <td style="text-align:center;color:var(--muted);font-size:12px;font-weight:700;white-space:nowrap;padding-right:4px;">${c.party_number ? `#${c.party_number}` : "—"}</td>
        <td><div style="display:flex;align-items:baseline;gap:6px;flex-wrap:wrap;">
            <strong>${esc(c.business_name)}</strong>
            ${badges ? `<span style="display:inline-flex;gap:3px;align-items:center;flex-wrap:wrap;">${badges}</span>` : ""}
          </div>
          ${c.person_name ? `<span style="font-size:12px;color:var(--muted);">${esc(c.person_name)}</span>` : ""}
          ${!c.is_active && !c.deleted_at ? '<span class="badge badge-amber" style="margin-left:4px;">Inactive</span>' : ""}
          ${missingPh ? '<span class="badge badge-red" style="margin-left:4px;">No phone</span>' : ""}</td>
        <td>${esc(c.city_name || "—")}${c.route_name ? `<br><span style="font-size:12px;color:var(--muted);">${esc(c.route_name)}</span>` : ""}</td>
        <td style="white-space:nowrap;">${renderFinancialsCell(c)}</td>
        <td>${missingPh ? '<span style="color:var(--muted);font-style:italic;">—</span>' : esc(c.phone)}</td>
        <td>${c.alias ? esc(c.alias) : "—"}</td>
        <td onclick="event.stopPropagation()"></td>
      </tr>`}).join("")}
    </tbody></table>`;
  }

  function fmtPersonMoney(val) {
    if (val == null || val === "") return "—";
    const n = Number(val);
    if (Number.isNaN(n)) return esc(String(val));
    const prefix = n < 0 ? "-₹" : "₹";
    return prefix + Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: 2 });
  }

