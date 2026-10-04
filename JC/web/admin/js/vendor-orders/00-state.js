/** Vendor orders — Today/Past date scope + same stage chips */
const VendorOrders = (() => {
  let ctx = {};
  let orders = [];
  let currentOrder = null;
  let openOrder = null;
  let closedLines = [];
  let currentBucket = "placed"; // same stages for Today + Past
  let hubMode = "queue"; // queue (Today) | past — date scope only
  let hubSearch = "";
  let showSummary = false;
  let orderSummary = null;
  let summaryDrill = null;
  let detailVendorId = null;
  let expandedProductId = null;
  let expandedPlacementId = null;
  let expandedClosedId = null;
  let hubExpandedVendorId = null;
  let hubExpandedPlacementId = null;
  let hubExpandCache = {};
  let wizardStep = 1;
  let wizardVendorId = null;
  let wizardProducts = [];
  let wizardLines = [];
  let wizardProductSearch = "";
  let focusQtyProductId = null;
  let wizardVendorSearch = "";
  let wizardVendorsCache = [];
  let wizardPlacedOn = "";

