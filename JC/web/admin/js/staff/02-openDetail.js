  async function openDetail(id) {
    ctx.showLoading?.();
    try {
      const s = staff.find(x => x.id === id) || await ctx.api(`/staff/${id}`);
      ctx.openDetail("Staff — " + s.name, `
        <div class="review-grid" style="margin-bottom:20px;">
          ${ctx.reviewRow("Name", s.name)}
          ${ctx.reviewRow("Login ID", s.phone)}
          ${ctx.reviewRow("Permissions", s.permissions.length ? s.permissions.join(", ") : "None")}
          ${ctx.reviewRow("Status", s.is_active ? "Active" : "Inactive")}
          ${ctx.reviewRow("Created", ctx.fmtDate(s.created_at))}
        </div>
        <div class="detail-section">
          <h4>Activity</h4>
          <div id="staff-activity-wrap">Loading…</div>
        </div>`,
        `<button class="btn btn-secondary btn-sm" onclick="StaffMgmt.openEdit(${s.id})">Edit</button>
         <button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
        "md"
      );
      await ctx.loadActivity?.({ tableId: "staff-activity-wrap", actorId: s.id, limit: 50, clickable: true });
    } catch (e) { ctx.toast(e.message, "error"); }
    finally { ctx.hideLoading?.(); }
  }

  const ROLE_PRESETS = [
    {
      id: "sell",
      label: "Sell",
      hint: "Customers + selling orders",
      keys: ["customers.read", "customers.write", "customer_orders.read", "customer_orders.write", "returns.read", "returns.write", "catalog.read", "addons.read"],
    },
    {
      id: "buy",
      label: "Buy",
      hint: "Vendors + buying orders + stock",
      // Hint promises "stock" but stock.read/write (on-hand qty + ledger, gated
      // separately from catalog.*/vendor_orders.* server-side) was missing — the
      // buying flow itself worked without it, but the standalone Stock screen the
      // hint calls out always 403'd.
      keys: ["vendors.read", "vendors.write", "vendor_orders.read", "vendor_orders.write", "catalog.read", "catalog.write", "addons.read", "addons.write", "stock.read", "stock.write"],
    },
    {
      id: "stock",
      label: "Stock",
      hint: "Catalog + on-hand",
      // Named "Stock" and promises "on-hand" but stock.read/write (the actual
      // permission gating GET /stock/products, /stock/products/{id}, and
      // /stock/ledger/{id}) was entirely missing — the one thing this preset's own
      // label promises was the one thing it didn't grant.
      keys: ["catalog.read", "catalog.write", "addons.read", "addons.write", "stock.read", "stock.write"],
    },
    {
      id: "people",
      label: "People",
      hint: "Customers + vendors only",
      keys: ["customers.read", "customers.write", "vendors.read", "vendors.write"],
    },
    {
      id: "setup",
      label: "Setup",
      hint: "Routes and cities",
      // Deliberately no recycle.* here — recycle bin is unrelated to setup data
      // and least-privilege says don't bundle it in by default.
      keys: ["setup.read", "setup.write"],
    },
    {
      id: "staff",
      label: "Staff",
      hint: "Customer orders, products at selling price, and payment entry. No buying price, no vendor orders, no company totals.",
      keys: [
        "customers.read", "customers.write",
        "catalog.read", "addons.read", "setup.read",
        "customer_orders.read", "customer_orders.write",
        "returns.read", "returns.write",
        "stock.read",
        "finance.write",
      ],
    },
  ];

  function applyRolePreset(roleId) {
    const role = ROLE_PRESETS.find(r => r.id === roleId);
    if (!role) return;
    const want = new Set(role.keys);
    document.querySelectorAll(".staff-perm-cb").forEach(cb => {
      cb.checked = want.has(cb.value);
    });
  }

  function permCheckboxes(selected) {
    const sel = new Set(selected || []);
    const presets = `<div style="margin-bottom:14px;">
      <div style="font-size:12px;font-weight:700;color:var(--muted);margin-bottom:8px;">Quick roles</div>
      <div style="display:flex;flex-wrap:wrap;gap:6px;">
        ${ROLE_PRESETS.map(r => `<button type="button" class="btn btn-secondary btn-sm" title="${ctx.esc(r.hint)}" onclick="StaffMgmt.applyRolePreset('${r.id}')">${ctx.esc(r.label)}</button>`).join("")}
      </div>
      <p style="margin:8px 0 0;font-size:12px;color:var(--muted);">Tap a role, then tick or untick anything. Staff is the everyday set. Vendor orders, buying price, and company totals stay off unless you tick them.</p>
    </div>`;
    const groups = permGroups.map(g => `
      <div style="margin-bottom:12px;">
        <div style="font-size:12px;font-weight:700;color:var(--muted);margin-bottom:6px;">${ctx.esc(g.label)}</div>
        ${g.permissions.map(p => `<label style="display:flex;align-items:center;gap:8px;margin-bottom:4px;font-size:13px;">
          <input type="checkbox" class="staff-perm-cb" value="${ctx.esc(p.key)}" ${sel.has(p.key) ? "checked" : ""} />
          ${ctx.esc(p.label)}
        </label>`).join("")}
      </div>`).join("");
    return presets + groups;
  }

  function collectPerms() {
    return Array.from(document.querySelectorAll(".staff-perm-cb:checked")).map(cb => cb.value);
  }

  function openWizard() {
    editingId = null;
    document.getElementById("staff-modal-title").textContent = "New Staff Member";
    document.getElementById("staff-modal-body").innerHTML = `
      <div style="display:grid;gap:16px;">
        <div><label class="label">Full Name *</label><input id="sm-name" class="input" placeholder="e.g. Rahul Sharma" /></div>
        <div><label class="label">Mobile Number (Login ID) *</label><input id="sm-phone" class="input" type="tel" maxlength="10" placeholder="10-digit mobile" />
          <p style="margin:6px 0 0;font-size:12px;color:var(--muted);">Password = last 4 digits by default. Sent via WhatsApp.</p></div>
        <div><label class="label">Custom Password (optional)</label><input id="sm-password" class="input" placeholder="Leave blank to use last 4 digits of phone" />
          <p style="margin:6px 0 0;font-size:12px;color:var(--muted);">Set this if the phone number isn't real (e.g. no WhatsApp) — you'll need to share it yourself.</p></div>
        <div><label class="label">Permissions</label><div class="card" style="padding:16px;max-height:420px;overflow-y:auto;">${permCheckboxes([])}</div></div>
      </div>`;
    document.getElementById("staff-modal-footer").innerHTML = `
      <button class="btn btn-secondary" onclick="StaffMgmt.closeModal()">Cancel</button>
      <button class="btn btn-primary" style="flex:1;" onclick="StaffMgmt.save()">Create & Send WhatsApp</button>`;
    document.getElementById("staff-modal").classList.remove("hidden");
  }

