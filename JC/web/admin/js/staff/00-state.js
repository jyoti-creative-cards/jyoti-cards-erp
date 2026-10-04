/** Staff management — admin only */
const StaffMgmt = (() => {
  let ctx = {};
  let staff = [];
  let permGroups = [];
  let editingId = null;
  let searchQ = "";

