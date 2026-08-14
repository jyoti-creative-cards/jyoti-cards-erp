/**
 * JC Admin — central UI design system.
 * Use HubUI for every hub/page shell so layouts stay consistent.
 * OrdersUI (chips, party cards, search) is re-exported here.
 */
const HubUI = (() => {
  function esc(s) {
    if (typeof OrdersUI !== "undefined" && OrdersUI.esc) return OrdersUI.esc(s);
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /**
   * Hub / setup tile button.
   * @param {{ letter?: string, tag?: string, title: string, desc?: string, count?: string|number, countId?: string, onclick: string, className?: string }} t
   */
  function tile(t) {
    const cls = ["big-tile", "ui-tile", "setup-tile", t.className || ""].filter(Boolean).join(" ");
    return `<button type="button" class="${cls}" onclick="${t.onclick}">
      ${t.tag ? `<span class="setup-tile-tag">${esc(t.tag)}</span>` : ""}
      ${t.letter ? `<span class="big-tile-letter">${esc(t.letter)}</span>` : ""}
      <span class="big-tile-title">${esc(t.title)}</span>
      ${t.desc ? `<span class="big-tile-desc">${esc(t.desc)}</span>` : ""}
      ${t.count != null || t.countId
        ? `<span class="big-tile-count"${t.countId ? ` id="${esc(t.countId)}"` : ""}>${esc(t.count != null ? t.count : "0")}</span>`
        : ""}
    </button>`;
  }

  /**
   * Responsive 3-col tile grid (same as More / Setup).
   * @param {object[]} tiles
   * @param {{ className?: string, style?: string }=} opts
   */
  function tileGrid(tiles, opts = {}) {
    const extra = opts.className || "";
    const style = opts.style ? ` style="${opts.style}"` : "";
    return `<div class="ui-tile-grid setup-grid ${extra}"${style}>
      ${(tiles || []).map(tile).join("")}
    </div>`;
  }

  /** Page / sub-page hero (title + sub + right actions). sub is plain text (escaped). */
  function pageHero({ title, sub, actionsHtml = "" }) {
    return `<div class="ui-hero setup-page-hero">
      <div>
        <h2 class="setup-page-title">${esc(title)}</h2>
        ${sub ? `<p class="setup-page-sub">${esc(sub)}</p>` : ""}
      </div>
      ${actionsHtml ? `<div class="ui-hero-actions">${actionsHtml}</div>` : ""}
    </div>`;
  }

  /** Hub landing intro. rightHtml = stats / refresh slot (raw HTML). */
  function hubIntro({ title, sub, rightHtml = "" }) {
    return `<div class="ui-hub-intro${rightHtml ? " ui-hub-intro-row" : ""}">
      <div>
        <h2 class="ui-hub-title">${esc(title)}</h2>
        ${sub ? `<p class="ui-hub-sub">${esc(sub)}</p>` : ""}
      </div>
      ${rightHtml || ""}
    </div>`;
  }

  /** Shared toolbar row under hero. */
  function toolbar(innerHtml) {
    return `<div class="ui-toolbar fin-toolbar">${innerHtml || ""}</div>`;
  }

  function emptyState(opts) {
    return OrdersUI.emptyState(opts);
  }
  function searchBar(opts) {
    return OrdersUI.searchBar(opts);
  }
  function partyCard(opts) {
    return OrdersUI.partyCard(opts);
  }
  function stageChips(opts) {
    return OrdersUI.stageChips(opts);
  }
  function actionChips(opts) {
    return OrdersUI.actionChips(opts);
  }
  function pill(text, tone) {
    return OrdersUI.pill(text, tone);
  }

  function filterAndRankParties(list, q) {
    return OrdersUI.filterAndRankParties(list, q);
  }
  function partySearchTokens(q) {
    return OrdersUI.partySearchTokens(q);
  }

  return {
    esc, tile, tileGrid, pageHero, hubIntro, toolbar,
    emptyState, searchBar, partyCard, stageChips, actionChips, pill,
    filterAndRankParties, partySearchTokens,
  };
})();
