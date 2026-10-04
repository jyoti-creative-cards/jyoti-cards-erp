from app.routers.catalog.router import router
from app.routers.catalog.bulk_create import bulk_create, update_product, _to_public, add_product_alternative, get_product, _sync_addon_links, _link_alternative, _sync_alternatives_bidirectional, _vendor_info, _count_alts
from app.routers.catalog.list_products import list_products, alternatives_board, _vendor_info_map
from app.routers.catalog.actions import list_vendors_for_catalog, check_duplicates, product_options, list_product_categories, list_product_year_groups, remove_product_alternative, delete_product, upload_image

__all__ = [
    "router",
    "_count_alts",
    "_link_alternative",
    "_sync_addon_links",
    "_sync_alternatives_bidirectional",
    "_to_public",
    "_vendor_info",
    "_vendor_info_map",
    "add_product_alternative",
    "alternatives_board",
    "bulk_create",
    "check_duplicates",
    "delete_product",
    "get_product",
    "list_product_categories",
    "list_product_year_groups",
    "list_products",
    "list_vendors_for_catalog",
    "product_options",
    "remove_product_alternative",
    "update_product",
    "upload_image",
]
