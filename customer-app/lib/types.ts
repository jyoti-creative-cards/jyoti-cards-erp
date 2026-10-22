export interface CustomerPublic {
  id: number;
  name: string;
  phone: string;
  company_name: string | null;
  address: string | null;
  secondary_phone: string | null;
  city: string | null;
  created_at: string;
  updated_at: string;
}

export interface ShopSuggestionPublic {
  catalog_product_id: number;
  our_product_id: string;
}

export interface ShopProductAlternativePublic {
  catalog_product_id: number;
  our_product_id: string;
  image_url: string;
}

export interface ShopProductPublic {
  catalog_product_id: number;
  our_product_id: string;
  image_url: string;
  selling_price: string;
  stock_status: string;
  quantity_on_hand?: number;
  alternatives: ShopProductAlternativePublic[];
}

export interface CustomerOrderLinePublic {
  catalog_product_id: number;
  our_product_id: string;
  name: string;
  quantity: number;
  unit_price: string;
  line_total: string;
}

export interface PortalOrderItem {
  catalog_product_id: number;
  our_product_id: string;
  quantity: number;
  unit_price: string;
}

export interface PortalOrderBill {
  id: number;
  bill_number: string;
  dispatched: boolean;
  receipt_number: string | null;
}

export interface PortalOrderPublic {
  id: number;
  status: string;
  placed_at: string;
  customer_notes: string | null;
  total_amount: string;
  items: PortalOrderItem[];
  bills: PortalOrderBill[];
  has_order_document: boolean;
}
