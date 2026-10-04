/** Setup — Freight agents list / create / edit */
const FreightAgentsSetup = (() => {
  let ctx = {};
  let agents = [];
  let searchQ = "";
  let editingId = null;

