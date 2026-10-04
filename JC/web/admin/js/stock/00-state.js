/** Stock — inventory, vendor order receipts */
const Stock = (() => {
  let ctx = {};
  let products = [];
  let viewMode = "grid";
  let wizardStep = 1;
  let wizardMode = null;
  let receiptSubmitBusy = false; // guard against double-click firing two receive/bill requests
  let wizardVendorId = null;
  let placedOrder = null;
  let wizardLines = [];
  let billFile = null;
  let billFileKey = null;
  let pendingDebitNotes = [];
  let receiptMeta = { billNumber: "", orderReceiptNumber: "", additionalCharges: "", totalBilledAmount: "", billingPct: "", gstPct: "", notes: "", eventDate: "" };
  let wizardReceiptId = null; // selected pending-bill receipt (bill_received mode)
  let wizardPendingBillList = null; // { vendor_id, vendor_label, receipts } from /stock/vendor-order/{id}/received
  let billingTerms = null; // vendor's typed billing terms, loaded with the chosen receipt
  let billPreview = null; // { expected_bill_total, expected_extra_cash, suggested_debit_notes } from /bill-preview
