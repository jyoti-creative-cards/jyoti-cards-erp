/** Setup — Bill series create, list, drill-down */
const BillSeries = (() => {
  let ctx = {};
  let seriesList = [];
  let currentSeries = null;
  let searchQ = "";

