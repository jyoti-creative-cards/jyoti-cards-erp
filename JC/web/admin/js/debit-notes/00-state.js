/** Debit notes — create / edit modal with plain-language direction choices */
const DebitNotes = (() => {
  let ctx = {};
  let state = {
    vendorId: null,
    receiptId: null,
    lines: [],
    editing: null,
    editIndex: null, // set when editing a not-yet-saved wizard row (local, no API call)
    prefillNote: null,
    onDone: null,
    noteType: "item",
    itemDirection: "short", // short = billed more / received less → pay less
    valueDirection: "over", // over = bill too high → pay less
  };

