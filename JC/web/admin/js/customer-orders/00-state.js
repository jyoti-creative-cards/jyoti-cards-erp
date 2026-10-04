/** Customer orders — Today/Past date scope + same stage chips */
const CustomerOrders = (() => {
  let ctx = {};
  let orders = [];
  let currentOrder = null;
  let currentBucket = "open"; // same stages for Today + Past
  let hubMode = "queue"; // queue (Today) | past — date scope only
  let hubSearch = "";
  let hubSort = "latest"; // latest | oldest — unfiltered hub-list order
  let coExpandedId = null;
  let hubExpandedCustomerId = null;
  let hubExpandCache = {};
  let detailCustomerId = null;

  let dispatchParcels = [];
  let dispatchAgents = [];
  let dispatchStatus = "pending"; // pending | picked | all
  let dispatchAgentId = ""; // "" = all agents

  let processStep = 1;
  let processContext = null;
  let processLines = [];
  let discountEnabled = false;
  let useOverallDiscount = false;
  let overallDiscount = "";
  let gstEnabled = false;
  let gstRate = "18";
  let freightAgents = [];
  let billSeries = [];
  let freightAgentId = "";
  let freightCharges = "";
  let transportMode = "";
  let transportReceiptNumber = "";
  let packagingCharges = "";
  let additionalCharges = [{ name: "", amount: "" }];
  let billSeriesId = "";
  let customerNotes = "";
  let narration = "";
  let previewTotals = null;
  let processBusy = false;
  let forceCreditOverride = false;
  let editBillId = null;
  let editBillNumber = "";
  let billEditSearch = "";
  // catalog_product_id -> quantity_shipped as it stood when the edit wizard opened.
  // Used only to warn the user before a qty decrease restores stock + shrinks the order.
  let editBillOriginalQty = {};
  let billEditProducts = [];

  // Past stages — Dispatch is an ops stage (parcels), not a Today/Past peer.
  const PAST_BUCKETS = ["received", "open", "billed", "dispatch", "cancelled", "closed"];
  const BROWSE_BUCKETS = PAST_BUCKETS; // legacy alias
  // All backlog buckets (New/Confirmed/Billed) now day-scope consistently: day=today
  // shows only entries touched today, day=all shows full history — nothing is ever
  // lost, it just moves from Today to Past (see list_customer_orders on the backend).
  const NOT_DAY_SCOPED_BUCKETS = [];
  const BUCKET_LABELS = {
    needs_action: "Today",
    queue: "Today",
    summary: "Today",
    received: "New",
    open: "Confirmed",
    billed: "Billed",
    dispatch: "Dispatch",
    cancelled: "Cancelled",
    closed: "Done",
  };

  const BUCKET_HINTS = {
    received: "Review each order, edit if needed, then confirm →",
    open: "Goods being picked — create bill when ready. Edit if quantities change.",
    billed: "Bill sent — dispatch or collect payment first, then close.",
    dispatch: "Track parcels and agent pickups.",
    closed: "All settled.",
  };

