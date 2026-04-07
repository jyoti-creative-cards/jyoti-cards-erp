from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Date, Text,
    ForeignKey, Enum as SAEnum, JSON, CheckConstraint,
)
from sqlalchemy.orm import relationship
from db.database import Base
import enum


# ---------- Enums ----------

class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    PARTIALLY_RECEIVED = "partially_received"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SalesStatus(str, enum.Enum):
    PENDING = "pending"
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
    PURCHASE = "purchase"
    SALE = "sale"
    ADJUSTMENT = "adjustment"


# ---------- Product ----------

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
    created_at = Column(DateTime, default=datetime.utcnow)

    vendor = relationship("Vendor")


# ---------- Vendor ----------

class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    phone = Column(String(20))
    address = Column(Text)
    credit_terms = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------- Customer ----------

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    phone = Column(String(20))
    address = Column(Text)
    customer_type = Column(String(20), default="retailer")
    payment_mode = Column(String(20), default="credit")
    credit_limit = Column(Float, default=0)
    outstanding_balance = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------- Inventory ----------

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
    txn_type = Column(SAEnum(TxnType), nullable=False)
    quantity = Column(Float, nullable=False)
    reference_type = Column(String(50))  # 'purchase_order' / 'sales_order'
    reference_id = Column(Integer)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product")


# ---------- Purchase Orders ----------

class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)
    status = Column(SAEnum(OrderStatus), default=OrderStatus.PENDING)
    order_date = Column(Date, default=date.today)
    expected_date = Column(Date)
    total_amount = Column(Float, default=0)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    vendor = relationship("Vendor")
    items = relationship("PurchaseOrderItem", back_populates="order", cascade="all, delete-orphan")


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity_ordered = Column(Float, nullable=False)
    quantity_received = Column(Float, default=0)
    unit_price = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)

    order = relationship("PurchaseOrder", back_populates="items")
    product = relationship("Product")


# ---------- Sales Orders ----------

class SalesOrder(Base):
    __tablename__ = "sales_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    status = Column(SAEnum(SalesStatus), default=SalesStatus.PENDING)
    order_date = Column(Date, default=date.today)
    total_amount = Column(Float, default=0)
    notes = Column(Text)
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
    total_price = Column(Float, nullable=False)

    order = relationship("SalesOrder", back_populates="items")
    product = relationship("Product")


# ---------- Delivery ----------

class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sales_order_id = Column(Integer, ForeignKey("sales_orders.id"), nullable=False)
    status = Column(SAEnum(DeliveryStatus), default=DeliveryStatus.PENDING)
    delivery_date = Column(Date)
    driver_name = Column(String(100))
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    sales_order = relationship("SalesOrder")


# ---------- Payments ----------

class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_type = Column(SAEnum(PaymentType), nullable=False)
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
    entity_type = Column(String(20), nullable=False)  # 'customer' / 'vendor'
    entity_id = Column(Integer, nullable=False)
    debit = Column(Float, default=0)
    credit = Column(Float, default=0)
    description = Column(Text)
    reference_type = Column(String(50))
    reference_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------- WhatsApp Log ----------

class WhatsAppLog(Base):
    __tablename__ = "whatsapp_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone = Column(String(20))
    message = Column(Text)
    direction = Column(String(10))  # 'in' / 'out'
    parsed_order_json = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
