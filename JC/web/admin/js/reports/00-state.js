/** Reports — Today / Books / Stock / Tax hub */
const Reports = (() => {
  let ctx = {};
  let mode = "today"; // today | books | stock | tax
  let chip = "daybook";
  let ledgerKind = "customers";
  // toISOString() is always UTC — for the first 5h30m of every IST calendar day
  // (00:00-05:29 IST = 18:30-23:59 UTC the previous day) this returned yesterday's
  // date, silently mislabeling "Today"/date-preset chips with the wrong day for
  // that whole window (the exact class of bug app/services/biz_date.py exists to
  // prevent on the backend).
  const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
  let fromDate = "";
  let toDate = "";
  let datePreset = "month"; // today | week | month | all | custom
  let lowThreshold = 10;
  let hubSearch = "";
  let ledgerDetail = null;
  let hideVoids = true;
  let backLabel = "Back";
  let ageingSide = "ar";

  const MODES = [
    { id: "today", label: "Today" },
    { id: "books", label: "Books" },
    { id: "stock", label: "Stock" },
    { id: "tax", label: "Tax" },
  ];

  const CHIPS = {
    today: [
      { id: "daybook", label: "Daybook" },
      { id: "sales-book", label: "Sales book" },
      { id: "day-bills", label: "Day bills" },
      { id: "receipt-book", label: "Receipt book" },
      { id: "purchases", label: "Purchase bills" },
      { id: "payments", label: "Payments" },
    ],
    books: [
      { id: "sales-book", label: "Sales book" },
      { id: "day-bills", label: "Day bills" },
      { id: "receipt-book", label: "Receipt book" },
      { id: "daybook", label: "Daybook" },
      { id: "ledgers", label: "Ledgers" },
      { id: "ageing", label: "Due age" },
      { id: "customer-sales", label: "Customer sales" },
      { id: "vendor-purchases", label: "Vendor purchase" },
      { id: "item-sales", label: "Item sales" },
      { id: "item-purchases", label: "Item purchase" },
    ],
    stock: [
      { id: "stock-wise", label: "Stock wise" },
      { id: "valuation", label: "Valuation" },
      { id: "movers", label: "Fast / slow" },
      { id: "low", label: "Low stock" },
      { id: "returns", label: "Returns" },
      { id: "debit-notes", label: "Debit notes" },
    ],
    tax: [
      { id: "gst-sales", label: "GST sales" },
      { id: "gst-purchases", label: "GST purchase" },
      { id: "cashbook", label: "Cash book" },
      { id: "expense-cat", label: "Expense by category" },
      { id: "pnl", label: "Profit & loss" },
    ],
  };

  const LEDGER_KINDS = [
    { id: "customers", label: "Customers" },
    { id: "vendors", label: "Vendors" },
    { id: "products", label: "Products" },
    { id: "staff", label: "Staff" },
    { id: "routes", label: "Routes" },
    { id: "cash", label: "Cash" },
    { id: "freight", label: "Freight" },
    { id: "expenses", label: "Expense" },
  ];

