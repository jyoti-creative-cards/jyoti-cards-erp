  function _detailCustomerId() { return detailCustomerId; }

  function openCustomer(customerId, bucket) {
    return openDetail(customerId, bucket || "open");
  }

  return {
    init, loadList, setBucket, setHubMode, setQueueFilter, setHubSearch, setHubPrice, setHubSort, showHub, openDetail, openCustomer, switchBucket, toggleDetailExpand,
    openSlidePanel, closeSlidePanel, toggleCardMore, closeAllCardMore,
    goToDispatch, goCollectPayment, setDispatchStatus, setDispatchAgent, pickParcel, reassignParcel, submitParcelReassign,
    showCreateMenu, showCreateMenuFromCustomer, openCloseBatch,
    processOrder, processFromHub, billNow, billBookedOrder, closeProcessWizard, renderProcessWizard,
    openEditBill, editLatestBill, promptEditBillNumber, saveBillNumber, enableDiscount, clearDiscount, setBillEditSearch, addBillEditProduct, removeProcessLine,
    openEditFromOpen,
    _detailCustomerId,
    setShipQty, setLineDisc, setLineNetRate, setDiscToggle, setOverallDisc, skipBillAddon,
    setFreightAgent, setFreightCharges, setTransportMode, setTransportReceipt, setPackagingCharges,
    setGst, setGstRate, setBillSeries, setNarration, setEditBillNumber, setBillDate, setAddCharge, addChargeRow,
    setOfflinePlacedOn,
    setForceCredit, setBillOnAgent, printDayDuplicates,
    processNext, processBack, submitProcess, backFromBillDuplicate, proceedBillDuplicate, toggleBillOrder, toggleAllBillOrders,
    confirmOrder, _doConfirm, cancelOpenLine, cancelPlacement, cancelCustomerOpen, cancelEntireReceived, cancelAllOpen, editOpenLine, editReceivedLine, deleteReceivedLine, openEditPlacement, closeBillLine, cancelBill, voidBill, voidPlacement, openBillDoc, shareBillWhatsApp, uploadBillQr, resetBillQr,
    openOfflineWizard, closeOfflineWizard, renderOfflineWizard,
    pickOfflineCustomer, onOfflineCustomerSearch, setOfflineNotes, previewOrder, backFromOrderPreview,
    onOfflineSearchInput, onOfflineSearchKey, onOfflineQtyKey, toggleOfflineProduct, pickOfflineProduct, removeOfflineLine, skipOfflineAddon,
    setOfflineQty, bumpOfflineQty, offlineNext, offlineBack, submitOffline, backFromDuplicate, proceedDuplicate,
  };
})();
