  return {
    login, staffLogin, setLoginTab, logout, toggleSidebar, showView, goBack, updateGlobalBack,
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
    toggleCustomerLedgerRow, openSelling, billCustomer, collectCustomer, openCustomerMoney,
    loadRecycleBin, setRecycleTab, openRecycleDetail, restoreItem, purgeItem,
    addLookup, submitLookup, editLookup, deleteLookup, openCustomerLedgerEntry, createCustomerOrder,
    closeModal, init,
    downloadExportKind, downloadBackupZip,
    debouncedLoadCustomers, debouncedVendorSearch, debouncedCatalogSearch, debouncedAddonSearch, debouncedStockSearch,
    setVendors,
  };
})();

App.init();
