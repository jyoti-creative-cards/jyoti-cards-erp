from datetime import datetime, date
import enum

from sqlalchemy import Column, Integer, String, Float, DateTime, Date, Text, ForeignKey, Enum as SAEnum, JSON, Boolean
from sqlalchemy.orm import relationship

from db.database import Base


def enum_values(enum_cls):
    return SAEnum(
        enum_cls,
        values_callable=lambda enum_items: [item.value for item in enum_items],
        native_enum=False,
        validate_strings=True,
    )


class PurchaseOrderStatus(str, enum.Enum):
    CREATED = "created"
    PENDING = "pending"
    APPROVED = "approved"
    LOADED = "loaded"
    IN_TRANSIT = "in_transit"
    RECEIVED = "received"
    MATCHED = "matched"
    CLOSED = "closed"
    DISPUTED = "disputed"
    PARTIALLY_RECEIVED = "partially_received"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SalesStatus(str, enum.Enum):
    CREATED = "created"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PACKED = "packed"
    DISPATCHED = "dispatched"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class DeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"


class PaymentType(str, enum.Enum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"


class TxnType(str, enum.Enum):
    PURCHASE_RECEIPT = "purchase_receipt"
    PURCHASE = "purchase"
    SALE = "sale"
    SALE_CANCEL = "sale_cancel"
    ADJUSTMENT = "adjustment"


class NotificationStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"
    MOCK_SENT = "mock_sent"


class MatchStatus(str, enum.Enum):
    PENDING = "pending"
    MATCHED = "matched"
    DISPUTED = "disputed"


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    sku = Column(String(50), unique=True, nullable=False)
    category = Column(String(100))
    vendor_id = Column(Integer, ForeignKey("vendors.id"))
    purchase_price = Column(Float, default=0)
    selling_price = Column(Float, default=0)
    unit = Column(String(20), default="pcs")
    min_stock_level = Column(Float, default=0)
    image_path = Column(String(500))
    reorder_level = Column(Float, default=0)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    vendor = relationship("Vendor")


class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    phone = Column(String(20))
    address = Column(Text)
    credit_terms = Column(String(100))
    gst_number = Column(String(50))
    gst_percent = Column(Float, default=0)
    gst_inclusive = Column(Boolean, default=False)
    default_shipment_mode = Column(String(50))
    transporter_name = Column(String(200))
    transporter_contact = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    phone = Column(String(20))
    whatsapp_phone = Column(String(20))
    address = Column(Text)
    customer_type = Column(String(20), default="retailer")
    payment_mode = Column(String(20), default="credit")
    credit_limit = Column(Float, default=0)
    outstanding_balance = Column(Float, default=0)
    default_discount_percent = Column(Float, default=0)
    notifications_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), unique=True, nullable=False)
    quantity_available = Column(Float, default=0)
    quantity_reserved = Column(Float, default=0)
    godown_location = Column(String(100))

    product = relationship("Product")


class InventoryTransaction(Base):
    __tablename__ = "inventory_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    txn_type = Column(enum_values(TxnType), nullable=False)
    quantity = Column(Float, nullable=False)
    reference_type = Column(String(50))
    reference_id = Column(Integer)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)
    status = Column(enum_values(PurchaseOrderStatus), default=PurchaseOrderStatus.CREATED)
    order_date = Column(Date, default=date.today)
    expected_date = Column(Date)
    vendor_committed_date = Column(Date)
    loading_date = Column(Date)
    receiving_date = Column(Date)
    total_amount = Column(Float, default=0)
    gst_amount = Column(Float, default=0)
    final_amount = Column(Float, default=0)
    shipment_mode = Column(String(50))
    transport_name = Column(String(200))
    transport_contact = Column(String(50))
    notes = Column(Text)
    vendor_notification_status = Column(enum_values(NotificationStatus), default=NotificationStatus.PENDING)
    internal_notification_status = Column(enum_values(NotificationStatus), default=NotificationStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)

    vendor = relationship("Vendor")
    items = relationship("PurchaseOrderItem", back_populates="order", cascade="all, delete-orphan")
    bills = relationship("VendorBill", back_populates="purchase_order", cascade="all, delete-orphan")
    receipts = relationship("GoodsReceipt", back_populates="purchase_order", cascade="all, delete-orphan")


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity_ordered = Column(Float, nullable=False)
    quantity_received = Column(Float, default=0)
    unit_price = Column(Float, nullable=False)
    gst_percent = Column(Float, default=0)
    total_price = Column(Float, nullable=False)

    order = relationship("PurchaseOrder", back_populates="items")
    product = relationship("Product")


class VendorBill(Base):
    __tablename__ = "vendor_bills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    bill_number = Column(String(100))
    bill_date = Column(Date)
    bill_amount = Column(Float, default=0)
    gst_amount = Column(Float, default=0)
    file_path = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)

    purchase_order = relationship("PurchaseOrder", back_populates="bills")


class GoodsReceipt(Base):
    __tablename__ = "goods_receipts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    receipt_date = Column(Date, default=date.today)
    receipt_number = Column(String(100))
    file_path = Column(String(500))
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    purchase_order = relationship("PurchaseOrder", back_populates="receipts")


class ThreeWayMatch(Base):
    __tablename__ = "three_way_matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    vendor_bill_id = Column(Integer, ForeignKey("vendor_bills.id"))
    goods_receipt_id = Column(Integer, ForeignKey("goods_receipts.id"))
    status = Column(enum_values(MatchStatus), default=MatchStatus.PENDING)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class DiscountRule(Base):
    __tablename__ = "discount_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    discount_percent = Column(Float, default=0)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer")
    product = relationship("Product")


class SalesOrder(Base):
    __tablename__ = "sales_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    status = Column(enum_values(SalesStatus), default=SalesStatus.CREATED)
    order_date = Column(Date, default=date.today)
    channel = Column(String(20), default="manual")
    subtotal_amount = Column(Float, default=0)
    discount_percent = Column(Float, default=0)
    discount_amount = Column(Float, default=0)
    total_amount = Column(Float, default=0)
    notes = Column(Text)
    customer_notification_status = Column(enum_values(NotificationStatus), default=NotificationStatus.PENDING)
    internal_notification_status = Column(enum_values(NotificationStatus), default=NotificationStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer")
    items = relationship("SalesOrderItem", back_populates="order", cascade="all, delete-orphan")


class SalesOrderItem(Base):
    __tablename__ = "sales_order_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("sales_orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Float, nullable=False)
    unit_price = Column(Float, nullable=False)
    discount_percent = Column(Float, default=0)
    total_price = Column(Float, nullable=False)

    order = relationship("SalesOrder", back_populates="items")
    product = relationship("Product")


class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sales_order_id = Column(Integer, ForeignKey("sales_orders.id"), nullable=False)
    status = Column(enum_values(DeliveryStatus), default=DeliveryStatus.PENDING)
    delivery_date = Column(Date)
    driver_name = Column(String(100))
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    sales_order = relationship("SalesOrder")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_type = Column(enum_values(PaymentType), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    vendor_id = Column(Integer, ForeignKey("vendors.id"))
    amount = Column(Float, nullable=False)
    payment_date = Column(Date, default=date.today)
    reference = Column(String(200))
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer")
    vendor = relationship("Vendor")


class Ledger(Base):
    __tablename__ = "ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(20), nullable=False)
    entity_id = Column(Integer, nullable=False)
    debit = Column(Float, default=0)
    credit = Column(Float, default=0)
    description = Column(Text)
    reference_type = Column(String(50))
    reference_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class WhatsAppConversation(Base):
    __tablename__ = "whatsapp_conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone = Column(String(20), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    last_message_at = Column(DateTime, default=datetime.utcnow)
    last_intent = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer")


class WhatsAppLog(Base):
    __tablename__ = "whatsapp_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone = Column(String(20))
    direction = Column(String(10))
    message = Column(Text)
    parsed_order_json = Column(JSON)
    related_type = Column(String(50))
    related_id = Column(Integer)
    status = Column(String(20), default="logged")
    created_at = Column(DateTime, default=datetime.utcnow)
