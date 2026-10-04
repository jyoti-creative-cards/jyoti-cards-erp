  function init(context) {
    ctx = context;
    TableUtils.register("addons", renderView);
  }

  async function ensureLookups() {
    if (categories.length && units.length) return;
    try {
      const rows = await ctx.api("/lookups");
      categories = rows.filter(r => r.lookup_type === "category").map(r => r.value);
      units = rows.filter(r => r.lookup_type === "unit").map(r => r.value);
    } catch (_) {
      categories = [];
      units = [];
    }
  }

  async function ensureVendors() {
    if (ctx.getVendors) {
      vendors = ctx.getVendors() || [];
      if (vendors.length) return;
    }
    vendors = await ctx.api("/vendors");
  }

  async function load() {
    // Live hub is Products (addons tab)
    if (typeof Products !== "undefined" && Products.refreshHub) {
      await Products.refreshHub();
      return;
    }
    addons = await ctx.api("/addons");
    if (ctx.onCountChange) ctx.onCountChange(addons.length);
  }

  async function refreshAfterMutation() {
    ctx.invalidateCache?.("/addons");
    if (typeof Products !== "undefined" && Products.refreshHub) await Products.refreshHub();
    else await load();
  }

  function fmtPrice(val) {
    if (val == null || val === "") return "—";
    const n = parseFloat(val);
    if (Number.isNaN(n)) return ctx.esc(String(val));
    return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function stockBadge(a) {
    const map = {
      in_stock: ["badge-green", "In stock"],
      low_stock: ["badge-amber", "Low stock"],
      out_of_stock: ["badge-gray", "Out of stock"],
      negative_stock: ["badge-red", "Negative"],
    };
    const [cls, label] = map[a.stock_status] || ["badge-gray", "—"];
    return `<span class="badge ${cls}">${ctx.esc(a.quantity_on_hand ?? 0)} on hand · ${label}</span>`;
  }

  function renderView() { /* legacy — Products hub owns list; kept only for TableUtils.register above */ }

  async function uploadImage(vendorId, ourProductId, file) {
    if (ctx.uploadImage) return ctx.uploadImage(vendorId, ourProductId, file);
    if (ctx.apiForm) return ctx.apiForm("/catalog/upload-image", buildImageForm(vendorId, ourProductId, file));
    const fd = buildImageForm(vendorId, ourProductId, file);
    const base = ctx.apiBase || "";
    const key = ctx.adminKey || "";
    const res = await fetch(`${base}/catalog/upload-image`, {
      method: "POST",
      headers: { "X-Admin-Key": key },
      body: fd,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const msg = typeof err.detail === "string" ? err.detail : `HTTP ${res.status}`;
      throw new Error(msg);
    }
    return res.json();
  }

  function buildImageForm(vendorId, ourProductId, file) {
    const fd = new FormData();
    fd.append("vendor_id", String(vendorId));
    fd.append("our_product_id", ourProductId);
    fd.append("image_index", "1");
    fd.append("file", file);
    return fd;
  }

