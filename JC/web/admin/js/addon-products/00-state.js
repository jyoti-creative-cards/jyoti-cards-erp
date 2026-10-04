/** Addon products — list/grid, wizard, detail, edit */
const AddonProducts = (() => {
  let ctx = {};
  let addons = [];
  let categories = [];
  let units = [];
  let vendors = [];
  let wizardStep = 1;
  let wizardForm = {};
  let editingId = null;

