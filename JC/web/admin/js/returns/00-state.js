/** Customer returns — one return per customer, multi-bill lines, restock + AR credit */
const Returns = (() => {
  let ctx = null;
  let hubRows = [];
  let hubSearch = "";
  let detailCustomerId = null;
  let detailRows = [];
  let wizard = null;

