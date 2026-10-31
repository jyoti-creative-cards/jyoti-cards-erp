  return {
    api, toast, login, staffLogin, setLoginTab, logout, toggleSidebar, showView, goBack, updateGlobalBack,
    showPeopleHub, showPeopleTab, renderPeopleCustomerSearch, renderPeopleVendorSearch, showSetupHub, showSetupTab,
    showMoreHub, showMoreSafety,
    setOrdersType,
    refreshAll, loadCustomers, reloadCustomers, loadActivity, openActivityItem, detailBack,
    openRouteDetail, openRouteModal, saveRoute, deleteRoute,
    openCityDetail, openCityModal, saveCity, deleteCity,
    openCustomerWizard, closeWizard, wizardBack, wizardNext, createCustomer,
    onCustomerWizardCityChange, onCustomerEditCityChange, onWizardPaymentTypeChange, onEditPaymentTypeChange, finishCustomerOpen, finishCustomerPlace, resendWhatsApp,
    openCustomerDetail, closeDetail, openCustomerEdit, closeEditModal, saveCustomer,
    deleteCustomer, toggleCustomerActive, restoreCustomer, sendCredentials,
    setCustomerStatusTab, toggleInactiveCustomers, toggleMissingPhoneFilter, setCustomerOpeningBalance, saveCustomerOpeningBalance,
    toggleCustomerLedgerRow, setCustomerLedgerDetails, setCustomerRealOnly, showCustomerMoneyLedger, onPartyLedgerSearch, pickPartyLedger, exportPartyLedger, printPartyLedger, rememberLedgerReturn, returnToLedger, openShortcut, closeShortcut, onShortcutSearch, pickShortcut, openSelling, billCustomer, collectCustomer, openCustomerMoney,
    loadRecycleBin, setRecycleTab, openRecycleDetail, restoreItem, purgeItem,
    addLookup, submitLookup, submitCatalogCategory, editLookup, deleteLookup, openCustomerLedgerEntry, createCustomerOrder,
    setOrderTakerMode, onOrderTakerStock, onOrderTakerCustomer, pickOrderTakerCustomer, clearOrderTakerCustomer, onOrderTakerItem, addOrderTakerItem, removeOrderTakerLine, saveOrderTakerOrder,
    closeModal, init, searchItemLookup, setWhatsappSends,
    downloadExportKind, downloadBackupZip,
    debouncedLoadCustomers, debouncedVendorSearch, debouncedCatalogSearch, debouncedAddonSearch, debouncedStockSearch,
    setVendors,
  };
})();

App.init();
