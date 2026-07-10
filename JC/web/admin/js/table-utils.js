/** Simple sort + column filters for data tables */
const TableUtils = (() => {
  const states = {};

  function state(id) {
    if (!states[id]) states[id] = { sort: null, dir: "asc", filters: {}, rerender: null };
    return states[id];
  }

  function register(id, rerender) {
    state(id).rerender = rerender;
  }

  function norm(v) {
    if (v == null || v === undefined) return "";
    return String(v).toLowerCase();
  }

  function apply(rows, id, cols) {
    const s = state(id);
    let out = [...rows];
    for (const col of cols) {
      const f = (s.filters[col.key] || "").trim().toLowerCase();
      if (!f || col.filterable === false) continue;
      out = out.filter(r => norm(col.get(r)).includes(f));
    }
    if (s.sort) {
      const col = cols.find(c => c.key === s.sort);
      if (col) {
        out.sort((a, b) => {
          const av = norm(col.get(a));
          const bv = norm(col.get(b));
          const cmp = av < bv ? -1 : av > bv ? 1 : 0;
          return s.dir === "asc" ? cmp : -cmp;
        });
      }
    }
    return out;
  }

  function sortIcon(id, key) {
    const s = state(id);
    if (s.sort !== key) return "↕";
    return s.dir === "asc" ? "↑" : "↓";
  }

  function escAttr(s) {
    return String(s || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  }

  function headerHtml(id, cols) {
    const s = state(id);
    const labels = cols.map(c => {
      if (c.sortable === false) return `<th>${c.label}</th>`;
      return `<th class="sortable" onclick="TableUtils.sort('${id}','${c.key}')">${c.label} <span class="sort-icon">${sortIcon(id, c.key)}</span></th>`;
    }).join("");
    const filters = cols.map(c => {
      if (c.filterable === false) return `<th></th>`;
      const val = s.filters[c.key] || "";
      return `<th><input class="col-filter" placeholder="Filter ${c.label.toLowerCase()}…" value="${escAttr(val)}" oninput="TableUtils.setFilter('${id}','${c.key}',this.value)" /></th>`;
    }).join("");
    return `<thead><tr>${labels}</tr><tr class="filter-row">${filters}</tr></thead>`;
  }

  function sort(id, key) {
    const s = state(id);
    if (s.sort === key) s.dir = s.dir === "asc" ? "desc" : "asc";
    else { s.sort = key; s.dir = "asc"; }
    if (s.rerender) s.rerender();
  }

  function setFilter(id, key, value) {
    state(id).filters[key] = value;
    if (state(id).rerender) state(id).rerender();
  }

  function clearFilters(id) {
    state(id).filters = {};
    if (state(id).rerender) state(id).rerender();
  }

  return { register, apply, headerHtml, sort, setFilter, clearFilters, state };
})();
