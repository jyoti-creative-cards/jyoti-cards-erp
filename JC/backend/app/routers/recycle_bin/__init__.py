from app.routers.recycle_bin.router import router
from app.routers.recycle_bin.listing import list_recycle_bin, get_deleted_route, get_deleted_city, get_deleted_customer, get_deleted_vendor, get_deleted_catalog_product, get_deleted_addon
from app.routers.recycle_bin.restore import restore_route, restore_city, restore_customer, restore_vendor, restore_catalog_product, restore_addon, restore_staff, restore_receipt_endpoint, restore_debit_note_endpoint, restore_customer_bill_endpoint, restore_customer_placement_endpoint, restore_customer_return_endpoint
from app.routers.recycle_bin.purge import purge_route, purge_city, purge_customer, purge_vendor, purge_catalog_product, purge_addon, purge_staff, purge_receipt_endpoint, purge_debit_note_endpoint, purge_customer_bill_endpoint, purge_customer_placement_endpoint, purge_customer_return_endpoint

__all__ = [
    "router",
    "list_recycle_bin",
    "get_deleted_route",
    "get_deleted_city",
    "get_deleted_customer",
    "get_deleted_vendor",
    "get_deleted_catalog_product",
    "get_deleted_addon",
    "restore_route",
    "restore_city",
    "restore_customer",
    "restore_vendor",
    "restore_catalog_product",
    "restore_addon",
    "restore_staff",
    "restore_receipt_endpoint",
    "restore_debit_note_endpoint",
    "restore_customer_bill_endpoint",
    "restore_customer_placement_endpoint",
    "restore_customer_return_endpoint",
    "purge_route",
    "purge_city",
    "purge_customer",
    "purge_vendor",
    "purge_catalog_product",
    "purge_addon",
    "purge_staff",
    "purge_receipt_endpoint",
    "purge_debit_note_endpoint",
    "purge_customer_bill_endpoint",
    "purge_customer_placement_endpoint",
    "purge_customer_return_endpoint",
]
