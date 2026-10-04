  function viewBillDoc(name, url) {
    if (!url) return ctx.toast("No document", "error");
    ctx.openDetail?.(name,
      `<iframe src="${ctx.esc(url)}" style="width:100%;height:70vh;border:none;border-radius:8px;"></iframe>`,
      `${ctx.detailFooterChild?.() || ""}<button class="btn btn-primary" style="flex:1;" onclick="App.closeDetail()">Close</button>`,
      "lg", { push: true });
  }

  function viewOrder(customerId) {
    App.closeDetail();
    App.showView("selling");
    CustomerOrders.openDetail(customerId, "billed");
  }

