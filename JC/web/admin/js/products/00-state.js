/** Products — Stock / Catalog tabs with unified Products + Add-ons views */
const Products = (() => {
  let ctx = {};
  let mainTab = "stock";
  let typeFilter = "products";
  let addonMode = false;
  let searchQuery = "";
  let filters = { vendor_id: "", category: "", series: "", year_group: "", price_min: "", price_max: "", stock_status: "", no_sell_price: false, no_addons: false };
  let catalogProducts = [];
  let catalogTotal = 0;
  let catalogOffset = 0;
  const CATALOG_PAGE = 100;
  const STOCK_PAGE = 100;
  let stockProducts = [];
  let stockTotal = 0;
  let stockUnits = 0;
  let stockCounts = null;
  let addons = [];
  let lookups = { categories: [], series: [], year_groups: [] };
  let viewMode = "grid";
  let filtersOpen = false;
  let attentionFilter = "all"; // all | low_stock | out_of_stock | negative_stock | no_sell | no_addons

