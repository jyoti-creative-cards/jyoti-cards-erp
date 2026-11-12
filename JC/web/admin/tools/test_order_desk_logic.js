function run(argv) {
  var app = Application.currentApplication();
  app.includeStandardAdditions = true;
  eval(app.read(Path(argv[0])) + "\nthis.__deskLogic = OrderDeskLogic;");
  var L = this.__deskLogic;
  var fails = [];
  function eq(name, got, want) {
    var a = JSON.stringify(got);
    var b = JSON.stringify(want);
    if (a !== b) fails.push(name + " got " + a + " want " + b);
  }
  eq("buttons new", L.buttonsFor("new"), ["confirm", "bill", "dispatch"]);
  eq("buttons confirmed", L.buttonsFor("confirmed"), ["bill"]);
  eq("buttons billed", L.buttonsFor("billed"), ["dispatch"]);
  eq("buttons dispatched", L.buttonsFor("dispatched"), []);
  eq("all dates", L.inDateRange("2026-11-01", "", ""), true);
  eq("inside", L.inDateRange("2026-11-02T18:30:00Z", "2026-11-01", "2026-11-03"), true);
  eq("before", L.inDateRange("2026-10-01", "2026-11-01", "2026-11-03"), false);
  eq("after", L.inDateRange("2026-12-01", "2026-11-01", "2026-11-03"), false);
  eq("missing day", L.inDateRange("", "2026-11-01", ""), false);

  var series = [
    { id: 1, prefix: "A", start_num: 1, end_num: 1000, name: "A", current_num: 4 },
    { id: 2, prefix: "B", start_num: 1, end_num: 1000, name: "B", current_num: 9 },
  ];
  eq("series", L.defaultBillSeriesId(series), "2");
  eq("number", L.nextBillNumber(series, 2, 1), "B11");

  var state = {
    discountEnabled: true,
    useOverallDiscount: false,
    lines: [{
      catalog_product_id: 7,
      quantity_to_ship: 2,
      skip_addon_ids: [3],
      discount_percent: "10",
      net_rate: "90",
      discSource: "pct",
    }],
    additionalCharges: [{ name: "Box", amount: "5" }],
    pickedCatalogs: { "4": "12" },
    gstEnabled: false,
    gstRate: "18",
    narration: " Hold ",
    transportMode: "bus",
    freightAgentId: "8",
    freightCharges: "40",
    packagingCharges: "",
    billDate: "2026-11-12",
    billSeriesId: "2",
    selectedPlacementIds: [15],
    commissionAgentId: 1,
    billOnAgent: false,
    confirmDuplicate: false,
    forceCreditOverride: false,
  };
  eq("bill body", L.billBody(state), {
    lines: [{
      catalog_product_id: 7,
      quantity_to_ship: 2,
      quantity: 2,
      skip_addon_ids: [3],
      discount_percent: 10,
    }],
    gst_enabled: false,
    gst_rate_percent: 18,
    narration: "Hold",
    additional_charges: [{ name: "Box", amount: "5" }],
    catalogs: [{ catalog_id: 4, price: "12" }],
    force_credit_override: false,
    confirm_duplicate: false,
    bill_series_id: 2,
    transport_mode: "bus",
    freight_agent_id: 8,
    freight_charges: "40",
    bill_date: "2026-11-12",
    placement_ids: [15],
    on_commission_agent: false,
  });
  state.discSource = "net";
  state.lines[0].discSource = "net";
  eq("net rate wins", L.billBody(state).lines[0].net_rate, 90);
  eq("no percent when net", L.billBody(state).lines[0].discount_percent, undefined);
  eq("bus freight missing", L.billError({ lines: [{ quantity_to_ship: 1 }], transportMode: "bus", freightAgentId: "", freightCharges: "", billSeriesId: "1" }), "Select the freight agent");
  eq("qty missing", L.billError({ lines: [], transportMode: "self_pickup", billSeriesId: "1" }), "Enter a quantity");
  eq("offline", L.offlineBody({
    lines: [{ catalog_product_id: 1, quantity: 3, skip_addon_ids: [] }],
    narration: " Note ",
    placedOn: "2026-11-12",
    confirmDuplicate: false,
  }), {
    lines: [{ catalog_product_id: 1, quantity: 3, skip_addon_ids: [] }],
    narration: "Note",
    placed_on: "2026-11-12",
    confirm_duplicate: false,
  });
  eq("offline empty", L.offlineError({ lines: [] }), "Add at least one item");

  var applied = L.applySelectedOrders({
    lines: [{ direct: true, catalog_product_id: 99, quantity_to_ship: 1 }],
    selectedPlacementIds: [1],
    contextLines: [{ catalog_product_id: 7, our_product_id: "A1", unit_price: "10", quantity_open: 4, quantity_on_hand: 2, open_line_id: 3, addons: [] }],
    billableOrders: [{ placement_id: 1, lines: [{ catalog_product_id: 7, quantity: 6 }] }, { placement_id: 2, lines: [{ catalog_product_id: 8, quantity: 1 }] }],
  });
  eq("booked qty capped", applied[0].quantity_to_ship, 4);
  eq("direct kept", applied[1].catalog_product_id, 99);

  if (fails.length) return fails.join("\n");
  return "ok";
}
