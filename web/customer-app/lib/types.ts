export interface CustomerPublic {
  id: number;
  business_name: string;
  person_name: string | null;
  phone: string;
  address: string | null;
  secondary_phone: string | null;
  city_name: string | null;
  gst_number: string | null;
  credit_limit?: string | null;
  created_at: string;
  updated_at: string;
  /** @deprecated API uses business_name */
  company_name?: string | null;
  /** @deprecated API uses person_name */
  name?: string | null;
  /** @deprecated API uses city_name */
  city?: string | null;
}

export interface ShopSuggestionPublic {
  catalog_product_id: number;
  our_product_id: string;
  image_url?: string;
  selling_price?: string;
  stock_status?: string;
  category?: string | null;
}

export interface ShopProductAlternativePublic {
  catalog_product_id: number;
  our_product_id: string;
  image_url: string;
  stock_status?: string;
  selling_price?: string;
  category?: string | null;
}

export interface ShopAddonPublic {
  our_product_id: string;
  name: string;
  quantity: number;
  unit: string;
  image_url?: string;
}

export interface ShopProductPublic {
  catalog_product_id: number;
  our_product_id: string;
  image_url: string;
  selling_price: string;
  stock_status: string;
  category?: string | null;
  series?: string | null;
  unit?: string | null;
  year_group?: string | null;
  addons?: ShopAddonPublic[];
  alternatives: ShopProductAlternativePublic[];
}

export interface CustomerOrderLinePublic {
  catalog_product_id: number;
  our_product_id: string;
  name: string;
  category: string;
  quantity: number;
  quantity_shipped?: number;
  unit_price: string;
  line_total: string;
  bill_id?: number | null;
  bill_number?: string | null;
  has_bill_document?: boolean;
  status?: string;
}

export interface CustomerOrderPublic {
  id: number;
  customer_id: number;
  status: string;
  items: CustomerOrderLinePublic[];
  total_amount: string;
  notes: string | null;
  customer_notes: string | null;
  created_at: string;
  updated_at: string;
  has_order_document?: boolean;
  document_url?: string | null;
}

/** API shape from GET /shop/orders */
export interface PortalPlacementPublic {
  id: number;
  line_id: number;
  catalog_product_id: number;
  our_product_id: string;
  image_url: string;
  quantity: number;
  quantity_shipped: number;
  unit_price: string;
  line_total: string;
  status: string;
  customer_notes: string | null;
  placed_at: string;
  bill_id: number | null;
  bill_number: string | null;
  has_bill_document: boolean;
  has_order_document: boolean;
  category?: string | null;
  series?: string | null;
  unit?: string | null;
}

/** API shape from POST /shop/orders */
export interface ShopOrderCreateResponse {
  ok: boolean;
  placement_id: number;
  merged?: boolean;
  our_product_id: string;
  quantity: number;
  unit_price: string;
  line_total: string;
  message: string;
  document_key?: string | null;
  document_url?: string | null;
  customer_notes?: string | null;
  whatsapp_sent?: boolean;
}
