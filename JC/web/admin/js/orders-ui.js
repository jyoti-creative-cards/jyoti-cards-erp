/** Shared Orders UX helpers — Vendor + Customer hubs/details */
const OrdersUI = (() => {
  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /** Search tokens from a query string. */
  function partySearchTokens(q) {
    return String(q || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
  }

  /**
   * Rank party for search display:
   * 0 = business name hit, 1 = city, 2 = person/alias, 3 = phone/other.
   * Returns null if tokens don't all match somewhere.
   */
  function partySearchRank(party, tokens) {
    const biz = String(party.business_name || "").toLowerCase();
    const city = String(party.city_name || party.city || "").toLowerCase();
    const person = `${party.person_name || ""} ${party.alias || ""}`.toLowerCase();
    const phone = `${party.phone || ""} ${party.secondary_phone || ""}`.toLowerCase();
    const address = String(party.address || "").toLowerCase();
    const label = String(party.customer_label || party.vendor_label || party.customer_name || "").toLowerCase();
    const allHay = [biz, city, person, phone, address, label].join(" ");
    if (!tokens.length) return [0, 0, 0, biz];
    if (!tokens.every(t => allHay.includes(t))) return null;

    const bizHits = tokens.filter(t => biz.includes(t)).length;
    const cityHits = tokens.filter(t => city.includes(t)).length;
    const personHits = tokens.filter(t => person.includes(t)).length;

    let tier;
    let hits;
    if (bizHits) { tier = 0; hits = bizHits; }
    else if (cityHits) { tier = 1; hits = cityHits; }
    else if (personHits) { tier = 2; hits = personHits; }
    else { tier = 3; hits = 0; }

    const starts = tokens[0] && biz.startsWith(tokens[0]) ? 1 : 0;
    return [tier, -hits, -starts, biz];
  }

  /** Filter + sort parties: business → city → person/alias. */
  function filterAndRankParties(list, q) {
    const tokens = partySearchTokens(q);
    if (!tokens.length) {
      return [...(list || [])].sort((a, b) => {
        const pnA = a.party_number ?? Infinity;
        const pnB = b.party_number ?? Infinity;
        if (pnA !== pnB) return pnA - pnB;
        return String(a.business_name || a.customer_name || a.vendor_label || "")
          .localeCompare(String(b.business_name || b.customer_name || b.vendor_label || ""), undefined, { sensitivity: "base" });
      });
    }
    const scored = [];
    for (const p of list || []) {
      const rank = partySearchRank(p, tokens);
      if (rank) scored.push({ p, rank });
    }
    scored.sort((a, b) => {
      for (let i = 0; i < a.rank.length; i++) {
        if (a.rank[i] < b.rank[i]) return -1;
        if (a.rank[i] > b.rank[i]) return 1;
      }
      return 0;
    });
    return scored.map(x => x.p);
  }

  function pill(text, tone = "muted") {
    return `<span class="ord-pill ord-pill-${tone}">${esc(text)}</span>`;
  }

  function moreMenu(items) {
    if (!items?.length) return "";
    const id = `ord-more-${Math.random().toString(36).slice(2, 9)}`;
    return `<div class="ord-more" onclick="event.stopPropagation()">
      <button type="button" class="btn btn-ghost btn-sm ord-more-btn" onclick="OrdersUI.toggleMore('${id}')" aria-haspopup="true">More ▾</button>
      <div class="ord-more-menu hidden" id="${id}">
        ${items.map(it => `<button type="button" class="ord-more-item${it.danger ? " is-danger" : ""}" onclick="${it.onclick}">${esc(it.label)}</button>`).join("")}
      </div>
    </div>`;
  }

  function toggleMore(id) {
    document.querySelectorAll(".ord-more-menu").forEach(el => {
      if (el.id !== id) el.classList.add("hidden");
    });
    document.getElementById(id)?.classList.toggle("hidden");
  }

  function closeAllMore() {
    document.querySelectorAll(".ord-more-menu").forEach(el => el.classList.add("hidden"));
  }

  function partyCard({
    title,
    titleIsHtml = false,
    meta,
    pillHtml = "",
    primaryLabel,
    primaryOnclick,
    moreItems = [],
    expandHtml = "",
    open = false,
    rowOnclick = "",
    canWrite = true,
  }) {
    // Primary = write action only. More menu stays for read-only (Show lines / Open / Print).
    const primary = canWrite && primaryLabel && primaryOnclick
      ? `<button type="button" class="btn btn-primary btn-sm" onclick="event.stopPropagation();${primaryOnclick}">${esc(primaryLabel)}</button>`
      : "";
    const more = moreMenu(moreItems);
    const titleHtml = titleIsHtml ? title : esc(title);
    return `<div class="ord-card${open ? " is-open" : ""}">
      <div class="ord-card-row"${rowOnclick ? ` onclick="${rowOnclick}"` : ""}>
        <div class="ord-card-main">
          ${rowOnclick ? `<span class="vo-chevron${open ? " is-open" : ""}" aria-hidden="true"></span>` : ""}
          <div class="ord-card-text">
            <div class="ord-card-title">${titleHtml} ${pillHtml}</div>
            <div class="ord-card-meta">${meta || ""}</div>
          </div>
        </div>
        <div class="ord-card-actions" onclick="event.stopPropagation()">
          ${primary}
          ${more}
        </div>
      </div>
      ${open && expandHtml ? `<div class="ord-card-expand">${expandHtml}</div>` : ""}
    </div>`;
  }

  function emptyState({ title, sub, ctaHtml = "" }) {
    return `<div class="ord-empty">
      <div class="ord-empty-icon">◇</div>
      <p class="ord-empty-title">${esc(title)}</p>
      ${sub ? `<p class="ord-empty-sub">${esc(sub)}</p>` : ""}
      ${ctaHtml || ""}
    </div>`;
  }

  function searchBar({ id, value, placeholder, oninput }) {
    const clearJs = `(function(){var el=document.getElementById('${esc(id)}');if(!el)return;el.value='';el.dispatchEvent(new Event('input',{bubbles:true}));})()`;
    const hasVal = !!String(value || "").trim();
    return `<div class="ord-search-wrap">
      <span class="ord-search-icon" aria-hidden="true">⌕</span>
      <input id="${esc(id)}" class="input ord-search" type="search" placeholder="${esc(placeholder)}" value="${esc(value || "")}" oninput="${oninput}" autocomplete="off" dir="ltr" style="direction:ltr;unicode-bidi:plaintext;" />
      <button type="button" class="ord-search-clear${hasVal ? "" : " hidden"}" onclick="${clearJs}" title="Clear search">×</button>
    </div>`;
  }

  function captureSearchCaret(id) {
    const el = document.getElementById(id);
    if (!el || document.activeElement !== el) return null;
    return { start: el.selectionStart, end: el.selectionEnd };
  }

  function restoreSearchCaret(id, caret) {
    if (!caret) return;
    const el = document.getElementById(id);
    if (!el) return;
    el.focus();
    try { el.setSelectionRange(caret.start, caret.end); } catch (_) { /* ignore */ }
  }

  function modeToggle({ prefix, mode }) {
    const queue = mode === "queue" || mode === "needs_action";
    return `<div class="ord-mode-toggle" role="tablist">
      <button type="button" class="ord-mode-btn${queue ? " active" : ""}" data-mode="queue" onclick="${prefix}.setHubMode('queue')">Today</button>
      <button type="button" class="ord-mode-btn${!queue ? " active" : ""}" data-mode="past" onclick="${prefix}.setHubMode('past')">Past</button>
    </div>`;
  }

  function stageChips({ stages, active, onclickFn }) {
    return `<div class="ord-stage-chips" role="tablist">
      ${stages.map(s => `<button type="button" class="ord-stage-chip${s.id === active ? " active" : ""}" data-bucket="${esc(s.id)}" onclick="${onclickFn}('${s.id}')">${esc(s.label)}</button>`).join("")}
    </div>`;
  }

  /** Action queue chips with counts — e.g. All (5) · To receive (3) */
  function actionChips({ hostId, items, active, onclickFn }) {
    const host = document.getElementById(hostId);
    if (!host) return;
    host.innerHTML = items.map(it => {
      const count = it.count != null ? ` <span class="ord-action-count">${esc(String(it.count))}</span>` : "";
      return `<button type="button" class="ord-action-chip${it.id === active ? " active" : ""}" data-action="${esc(it.id)}" onclick="${onclickFn}('${it.id}')">${esc(it.label)}${count}</button>`;
    }).join("");
    host.classList.toggle("hidden", !items.length);
  }

  function syncModeButtons(barSelector, mode) {
    const normalized = (mode === "needs_action") ? "queue" : (mode === "browse" ? "past" : mode);
    document.querySelectorAll(`${barSelector} .ord-mode-btn`).forEach(btn => {
      btn.classList.toggle("active", btn.getAttribute("data-mode") === normalized);
    });
  }

  function syncStageChips(barSelector, bucket) {
    document.querySelectorAll(`${barSelector} .ord-stage-chip`).forEach(btn => {
      btn.classList.toggle("active", btn.getAttribute("data-bucket") === bucket);
    });
  }

  // Close more menus on outside click (page-level, not modal dismiss)
  if (typeof document !== "undefined" && !window.__ordMoreBound) {
    window.__ordMoreBound = true;
    document.addEventListener("click", (e) => {
      if (!e.target.closest?.(".ord-more")) closeAllMore();
    });
  }

  return {
    esc, pill, moreMenu, toggleMore, closeAllMore, partyCard, emptyState,
    searchBar, captureSearchCaret, restoreSearchCaret,
    modeToggle, stageChips, actionChips, syncModeButtons, syncStageChips,
    partySearchTokens, partySearchRank, filterAndRankParties,
  };
})();

