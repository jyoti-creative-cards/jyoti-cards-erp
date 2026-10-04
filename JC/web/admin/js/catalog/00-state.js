/** Catalog module — grid, wizard, detail, edit */
const Catalog = (() => {
  let ctx = {};
  let products = [];
  let addons = [];
  let wizardStep = 1;
  let wizardVendorId = null;
  let wizardRows = [];
  let editingId = null;
  let editReturnTo = null;
  let wizardCreatedProducts = [];
  let catalogVendors = [];
  let wizardDupes = [];

  const MAX_ALTERNATIVES = 3;
  const STEP_LABELS = ["Product", "Price", "Create"];

  let _rowCounter = 0;
