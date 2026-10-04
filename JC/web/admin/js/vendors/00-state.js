/** Vendor module — CRUD, wizard, detail, edit */
const Vendors = (() => {
  let ctx = {};
  let vendors = [];
  let vendorLedger = [];
  let currentVendorId = null;
  let wizardStep = 1;
  let wizardForm = {};
  let editingId = null;

  const VENDOR_COLS = [
    { key: "vendor_number", label: "#", get: v => v.vendor_number || 0, exactNumeric: true, numeric: true },
    { key: "business", label: "Business", get: v => `${v.business_name} ${v.alias || ""}` },
    { key: "phone", label: "Phone", get: v => v.phone },
    { key: "city", label: "City", get: v => v.city_name || "" },
    { key: "contact", label: "Contact", get: v => v.person_name || "" },
    { key: "_actions", label: "", filterable: false, sortable: false },
  ];

