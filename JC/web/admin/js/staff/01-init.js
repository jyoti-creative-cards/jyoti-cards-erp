  function init(context) { ctx = context; }

  async function load() {
    // Called unguarded on tab switch (app.js) — an API failure previously threw
    // an unhandled rejection and left the page stuck on whatever it last showed
    // with no explanation.
    try {
      [staff, permGroups] = await Promise.all([
        ctx.api("/staff"),
        ctx.api("/staff/permissions"),
      ]);
    } catch (e) {
      ctx.toast?.(e.message || "Could not load staff", "error");
      return;
    }
    if (!Array.isArray(staff)) staff = [];
    const count = document.getElementById("hub-staff-count");
    if (count) count.textContent = `${staff.length} staff`;
    renderSearch();
    render();
  }

  function setSearch(val) {
    searchQ = val || "";
    render();
  }

  function renderSearch() {
    const slot = document.getElementById("staff-search-slot");
    if (!slot) return;
    slot.innerHTML = HubUI.searchBar({
      id: "staff-search",
      value: searchQ,
      placeholder: "Search name or phone…",
      oninput: "StaffMgmt.setSearch(this.value)",
    });
  }

  function filtered() {
    const q = searchQ.trim().toLowerCase();
    if (!q) return staff;
    return staff.filter(s =>
      String(s.name || "").toLowerCase().includes(q)
      || String(s.phone || "").includes(q)
    );
  }

  function render() {
    const el = document.getElementById("staff-table");
    if (!el) return;
    const list = filtered();
    if (!staff.length) {
      el.innerHTML = HubUI.emptyState({
        title: "No staff yet",
        sub: "Add a team member to share logins.",
        ctaHtml: `<button class="btn btn-primary btn-lg" onclick="StaffMgmt.openWizard()">+ Add Staff</button>`,
      });
      return;
    }
    if (!list.length) {
      el.innerHTML = HubUI.emptyState({ title: "No matches", sub: "Clear search." });
      return;
    }
    el.innerHTML = `<div class="ord-card-list">${list.map(s => HubUI.partyCard({
      title: s.name,
      meta: `${ctx.esc(s.phone)}${s.permissions.length ? ` · ${s.permissions.length} permission${s.permissions.length === 1 ? "" : "s"}` : " · No permissions"}`,
      pillHtml: s.is_active === false ? HubUI.pill("Inactive", "muted") : HubUI.pill("Active", "ok"),
      primaryLabel: "Edit",
      primaryOnclick: `StaffMgmt.openEdit(${s.id})`,
      moreItems: [
        { label: "Open", onclick: `StaffMgmt.openDetail(${s.id})` },
        { label: "Remove", onclick: `StaffMgmt.deleteStaff(${s.id},${JSON.stringify(s.name)})`, danger: true },
      ],
      rowOnclick: `StaffMgmt.openDetail(${s.id})`,
      canWrite: true,
    })).join("")}</div>`;
  }

