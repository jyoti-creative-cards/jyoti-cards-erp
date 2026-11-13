/** Pure helpers for the Orders screen. The bill body matches the single-bill save. */
const OrderDeskLogic = (() => {
  function calcNetFromDisc(rate, discPct) {
    const r = Number(rate);
    const d = Number(discPct);
    if (!Number.isFinite(r) || r <= 0) return "";
    if (!Number.isFinite(d) || d <= 0) return String(r);
    const net = r * (1 - Math.min(100, Math.max(0, d)) / 100);
    return (Math.round(net * 100) / 100).toString();
  }

  function toDay(value) {
    if (value == null || value === "") return "";
    const s = String(value);
    if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.slice(0, 10);
    const d = new Date(s);
    if (Number.isNaN(d.getTime())) return "";
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Kolkata",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(d);
  }

  function inDateRange(value, from, to) {
    const start = String(from || "").trim();
    const end = String(to || "").trim();
    if (!start && !end) return true;
    const day = toDay(value);
    if (!day) return false;
    if (start && day < start) return false;
    if (end && day > end) return false;
    return true;
  }

  function orderDay(row) {
    return toDay(row && (row.display_date || row.bill_date || row.placed_at || row.created_at || row.updated_at));
  }

  function buttonsFor(filter) {
    if (filter === "new") return ["confirm", "bill", "dispatch"];
    if (filter === "confirmed") return ["bill"];
    if (filter === "billed") return ["dispatch"];
    return [];
  }

  function defaultBillSeriesId(rows) {
    const letters = (rows || []).filter(s => /^[A-Za-z]$/.test(String(s.prefix || "").trim()) && Number(s.start_num) === 1 && Number(s.end_num) === 1000);
    letters.sort((a, b) => String(a.prefix).toUpperCase().localeCompare(String(b.prefix).toUpperCase()));
    if (letters.length) return String(letters[letters.length - 1].id);
    const actual = (rows || []).find(s => String(s.name || "").trim().toLowerCase() === "actual");
    return String((actual || (rows || [])[0] || {}).id || "");
  }

  function nextBillNumber(series, seriesId, offset) {
    const s = (series || []).find(x => String(x.id) === String(seriesId));
    if (!s) return "";
    const base = s.current_num + 1 >= s.start_num ? s.current_num + 1 : s.start_num;
    return `${s.prefix}${base + (Number(offset) || 0)}`;
  }

  function billEditable(createdAt, anyDay) {
    if (anyDay) return true;
    if (!createdAt) return false;
    const created = new Date(createdAt);
    if (Number.isNaN(created.getTime())) return false;
    const day = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Kolkata",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
    return day.format(created) === day.format(new Date());
  }

  function applySelectedOrders(state) {
    const direct = (state.lines || []).filter(l => l.direct);
    const chosen = new Set((state.selectedPlacementIds || []).map(Number));
    const byCid = new Map((state.contextLines || []).map(l => [Number(l.catalog_product_id), l]));
    const seen = [];
    const qty = {};
    for (const order of state.billableOrders || []) {
      if (!chosen.has(Number(order.placement_id))) continue;
      for (const ln of order.lines || []) {
        const cid = Number(ln.catalog_product_id);
        if (!seen.includes(cid)) seen.push(cid);
        qty[cid] = (qty[cid] || 0) + Number(ln.quantity || 0);
      }
    }
    const booked = seen.map(cid => {
      const l = byCid.get(cid);
      if (!l || !(qty[cid] > 0)) return null;
      const q = Math.min(Number(l.quantity_open) || 0, qty[cid] || 0);
      return {
        catalog_product_id: l.catalog_product_id,
        our_product_id: l.our_product_id,
        unit_price: l.unit_price,
        quantity_open: q,
        quantity_to_ship: q,
        quantity_on_hand: l.quantity_on_hand,
        discount_percent: "",
        net_rate: calcNetFromDisc(l.unit_price, 0),
        discSource: "",
        addons: l.addons || [],
        skip_addon_ids: [],
        direct: false,
        open_line_id: l.open_line_id,
        marking: l.marking || "",
      };
    }).filter(l => l && l.quantity_open > 0);
    const bookedIds = new Set(booked.map(l => Number(l.catalog_product_id)));
    return booked.concat(direct.filter(l => !bookedIds.has(Number(l.catalog_product_id))));
  }

  function billBody(s) {
    const discOn = !!s.discountEnabled;
    const lines = (s.lines || [])
      .filter(l => Number(l.quantity_to_ship) > 0)
      .map(l => {
        const row = {
          catalog_product_id: l.catalog_product_id,
          quantity_to_ship: Number(l.quantity_to_ship),
          quantity: Number(l.quantity_to_ship),
        };
        row.skip_addon_ids = (l.skip_addon_ids || []).map(Number);
        if (l.direct) row.direct = true;
        if (discOn && !s.useOverallDiscount) {
          const hasPct = l.discount_percent !== "" && l.discount_percent != null && Number.isFinite(Number(l.discount_percent));
          const hasNet = l.net_rate !== "" && l.net_rate != null && Number.isFinite(Number(l.net_rate));
          if (l.discSource === "net" && hasNet) row.net_rate = Number(l.net_rate);
          else if (hasPct) row.discount_percent = Number(l.discount_percent);
          else if (hasNet) row.net_rate = Number(l.net_rate);
        }
        return row;
      });
    const extra = (s.additionalCharges || [])
      .filter(c => String(c.name || "").trim() && String(c.amount || "").trim() && Number(c.amount) > 0)
      .map(c => ({ name: String(c.name).trim(), amount: String(c.amount) }));
    const catalogs = !s.editBillId
      ? Object.entries(s.pickedCatalogs || {}).map(([id, price]) => ({
          catalog_id: Number(id),
          price: String(price === "" || price == null ? "0" : price),
        }))
      : [];
    const body = {
      lines,
      gst_enabled: !!s.gstEnabled,
      gst_rate_percent: Number(s.gstRate) || 18,
      narration: String(s.narration || "").trim() || null,
      additional_charges: extra,
      catalogs,
      force_credit_override: !!s.forceCreditOverride,
      confirm_duplicate: !!s.confirmDuplicate,
    };
    if (!s.editBillId) body.bill_series_id = Number(s.billSeriesId);
    if (discOn && s.useOverallDiscount && String(s.overallDiscount || "").trim()) {
      body.overall_discount_percent = Number(s.overallDiscount);
    }
    if (s.transportMode) body.transport_mode = s.transportMode;
    if (s.transportMode === "transport" && String(s.transportReceiptNumber || "").trim()) {
      body.transport_receipt_number = String(s.transportReceiptNumber).trim();
    }
    if (s.transportMode === "bus" && s.freightAgentId) body.freight_agent_id = Number(s.freightAgentId);
    if ((s.transportMode === "bus" || s.transportMode === "transport") && String(s.freightCharges ?? "").trim() !== "") {
      body.freight_charges = String(s.freightCharges);
    }
    if (String(s.packagingCharges || "").trim()) body.packaging_charges = String(s.packagingCharges);
    if (s.billDate) body.bill_date = s.billDate;
    if (!s.editBillId && (s.selectedPlacementIds || []).length) {
      body.placement_ids = s.selectedPlacementIds.map(Number);
    }
    if (!s.editBillId && s.commissionAgentId) body.on_commission_agent = !!s.billOnAgent;
    return body;
  }

  function billError(s) {
    const lines = s.lines || [];
    if (s.editBillId && lines.some(l => !(Number(l.quantity_to_ship) > 0))) return "Enter quantity for every item";
    if (!lines.some(l => Number(l.quantity_to_ship) > 0)) return "Enter a quantity";
    if (!s.transportMode) return "Select how this is sent";
    if (s.transportMode === "bus") {
      if (!s.freightAgentId) return "Select the freight agent";
      if (String(s.freightCharges ?? "").trim() === "") return "Enter freight";
    }
    if (s.transportMode === "transport" && String(s.freightCharges ?? "").trim() === "") return "Enter transport charges";
    if (!s.editBillId && !s.billSeriesId) return "Select a bill series";
    return "";
  }

  function offlineBody(s) {
    return {
      lines: (s.lines || []).filter(l => Number(l.quantity) > 0).map(l => ({
        catalog_product_id: l.catalog_product_id,
        quantity: Number(l.quantity),
        skip_addon_ids: l.skip_addon_ids || [],
      })),
      narration: String(s.narration || "").trim() || null,
      placed_on: s.placedOn || "",
      confirm_duplicate: !!s.confirmDuplicate,
    };
  }

  function offlineError(s) {
    if (!(s.lines || []).some(l => Number(l.quantity) > 0)) return "Add at least one item";
    return "";
  }

  return {
    calcNetFromDisc, toDay, inDateRange, orderDay, buttonsFor,
    defaultBillSeriesId, nextBillNumber, billEditable, applySelectedOrders,
    billBody, billError, offlineBody, offlineError,
  };
})();
