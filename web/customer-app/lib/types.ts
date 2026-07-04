export interface CustomerPublic {
  id: number;
  name: string;
  phone: string;
  company_name: string | null;
  address: string | null;
  secondary_phone: string | null;
  city: string | null;
  gst_number: string | null;
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
  alternatives: ShopProductAlternativePublic[];
}

export interface CustomerOrderLinePublic {
  catalog_product_id: number;
  our_product_id: string;
  name: string;
  category: string;
  quantity: number;
  unit_price: string;
  line_total: string;
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
}
