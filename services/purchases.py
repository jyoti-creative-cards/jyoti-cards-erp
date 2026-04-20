from datetime import date
import re
from typing import Optional

from sqlalchemy.orm import Session

from backend.services.whatsapp import send_internal_alert, send_whatsapp_document, send_whatsapp_message
from services.po_pdf import generate_po_pdf
from db.models import (
    GoodsReceipt,
    GoodsReceiptItem,
    Ledger,
    MatchStatus,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    ThreeWayMatch,
    Vendor,
    VendorBill,
    VendorOffering,
)
from services.inventory import add_stock


def _billing_percent(value, default: float = 100.0) -> float:
    if value is None:
        return float(default)
    if isinstance(value, str):
        match = re.search(r"\d+(?:\.\d+)?", value)
        if not match:
            return float(default)
        value = match.group(0)
    percent = float(value)
    return percent if percent > 0 else float(default)


def _billed_unit_price(base_unit_price: float, billing_percent: float) -> float:
    return round(float(base_unit_price) * (float(billing_percent) / 100.0), 2)


def _append_note(existing: Optional[str], new_note: Optional[str]) -> str:
    if not new_note:
        return existing or ""
    if not existing:
        return new_note
    return f"{existing}\n{new_note}"


def list_purchase_orders(db: Session, status: str = None, latest_only: bool = True):
    q = db.query(PurchaseOrder).order_by(PurchaseOrder.created_at.desc())
    if latest_only:
        q = q.filter(PurchaseOrder.is_latest.is_(True))
    if status:
        q = q.filter(PurchaseOrder.status == status)
    return q.all()


def get_purchase_order(db: Session, po_id: int):
    return db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()


def list_purchase_order_versions(db: Session, po_id: int):
    po = get_purchase_order(db, po_id)
    if not po:
        return []
    group_id = po.version_group_id or po.id
    return (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.version_group_id == group_id)
        .order_by(PurchaseOrder.version_number.desc())
        .all()
    )


def get_vendor_offerings_for_po(db: Session, vendor_id: int):
    return (
        db.query(VendorOffering)
        .filter(VendorOffering.vendor_id == vendor_id, VendorOffering.active.is_(True))
        .order_by(VendorOffering.created_at.desc())
        .all()
    )


def build_po_version_seed(po: PurchaseOrder):
    return [
        {
            "product_id": item.product_id,
            "vendor_offering_id": item.vendor_offering_id,
            "vendor_product_code": item.vendor_product_code,
            "quantity": float(item.quantity_ordered),
            "base_unit_price": float(item.base_unit_price or item.unit_price),
            "billing_percent": float(item.billing_percent or 100),
        }
        for item in po.items
    ]


def _po_caption(po: PurchaseOrder) -> str:
    """Short caption sent alongside the PO PDF — uses vendor's item codes."""
    vendor_name = po.vendor.firm_name or po.vendor.name
    lines = [
        f"Purchase Order #{po.id} (v{po.version_number})",
        f"To: {vendor_name}",
        f"Items: {len(po.items)}",
        f"Value: Rs {po.final_amount:,.0f}",
        f"Date: {po.order_date}",
    ]
    return "\n".join(lines)


def create_purchase_order(
    db: Session,
    vendor_id: int,
    items: list[dict],
    order_date=None,
    expected_date=None,
    vendor_committed_date=None,
    shipment_mode="",
    transport_name="",
    transport_contact="",
    notes="",
    source_po_id: Optional[int] = None,
):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise ValueError("Vendor not found")
    if not items:
        raise ValueError("Add at least one item")

    previous_po = get_purchase_order(db, source_po_id) if source_po_id else None
    if previous_po:
        previous_po.is_latest = False
    version_group_id = previous_po.version_group_id if previous_po else None
    version_number = (previous_po.version_number + 1) if previous_po else 1

    po = PurchaseOrder(
        vendor_id=vendor_id,
        version_group_id=version_group_id,
        previous_version_id=previous_po.id if previous_po else None,
        version_number=version_number,
        is_latest=True,
        status=PurchaseOrderStatus.CREATED,
        order_date=order_date or date.today(),
        expected_date=expected_date,
        vendor_committed_date=vendor_committed_date,
        shipment_mode=shipment_mode,
        transport_name=transport_name,
        transport_contact=transport_contact,
        notes=notes,
    )
    db.add(po)
    db.flush()
    if not po.version_group_id:
        po.version_group_id = po.id

    subtotal = 0.0
    for raw_item in items:
        quantity = float(raw_item.get("quantity", 0) or 0)
        if quantity <= 0:
            continue
        offering = None
        offering_id = raw_item.get("vendor_offering_id")
        if offering_id:
            offering = db.query(VendorOffering).filter(VendorOffering.id == offering_id).first()
        product = raw_item.get("product")
        if not product:
            from db.models import Product

            product = db.query(Product).filter(Product.id == raw_item["product_id"]).first()
        if not product:
            raise ValueError("Product not found")

        base_unit_price = float(raw_item.get("base_unit_price") or raw_item.get("unit_price") or (offering.vendor_price if offering else product.purchase_price) or 0)
        billing_percent = _billing_percent(raw_item.get("billing_percent"), _billing_percent((offering.billing_percent if offering else None), _billing_percent(vendor.billing_condition, 100)))
        billed_unit_price = _billed_unit_price(base_unit_price, billing_percent)
        line_total = round(quantity * billed_unit_price, 2)
        subtotal += line_total

        db.add(
            PurchaseOrderItem(
                order_id=po.id,
                product_id=product.id,
                vendor_offering_id=offering.id if offering else raw_item.get("vendor_offering_id"),
                vendor_product_code=raw_item.get("vendor_product_code") or (offering.vendor_product_code if offering else ""),
                our_product_code=product.sku,
                quantity_ordered=quantity,
                quantity_received=0,
                base_unit_price=base_unit_price,
                billing_percent=billing_percent,
                unit_price=billed_unit_price,
                gst_percent=float(raw_item.get("gst_percent", 0) or 0),
                total_price=line_total,
            )
        )

    if subtotal <= 0:
        raise ValueError("Add at least one item")

    po.total_amount = subtotal
    po.final_amount = subtotal
    po.gst_amount = 0
    db.add(
        Ledger(
            entity_type="vendor",
            entity_id=vendor_id,
            debit=po.final_amount,
            credit=0,
            description=f"PO#{po.id} v{po.version_number} created",
            reference_type="purchase_order",
            reference_id=po.id,
        )
    )
    db.commit()
    db.refresh(po)

    # generate PDF and send to vendor via WhatsApp
    pdf_path = generate_po_pdf(po)
    caption = _po_caption(po)
    pdf_filename = f"PO_{po.id}_v{po.version_number}.pdf"

    vendor_result = send_whatsapp_document(
        db, vendor.phone, pdf_path, caption, pdf_filename,
        "purchase_order", po.id,
    )
    if vendor_result.status == "failed":
        fallback_text = (
            f"PO #{po.id} (v{po.version_number}) created.\n"
            f"Items: {len(po.items)}\n"
            f"Value: Rs {po.final_amount:,.0f}\n"
            f"Please check details in dashboard or contact Jyoti Cards."
        )
        vendor_result = send_whatsapp_message(
            db, vendor.phone, fallback_text, "purchase_order", po.id
        )
    internal_result = send_internal_alert(
        db, f"PO#{po.id} v{po.version_number} sent to {vendor.firm_name or vendor.name} — Rs {po.final_amount:,.0f}",
        "purchase_order", po.id,
    )
    po.vendor_notification_status = vendor_result.status
    po.internal_notification_status = internal_result.status
    db.commit()
    db.refresh(po)
    return po


def create_purchase_order_version(db: Session, po_id: int, items: list[dict], **kwargs):
    po = get_purchase_order(db, po_id)
    if not po:
        raise ValueError("PO not found")
    return create_purchase_order(db, po.vendor_id, items, source_po_id=po.id, **kwargs)


def update_purchase_order_status(db: Session, po_id: int, new_status, loading_date=None, receiving_date=None, notes=None):
    po = get_purchase_order(db, po_id)
    if not po:
        raise ValueError("PO not found")
    po.status = new_status
    if loading_date:
        po.loading_date = loading_date
    if receiving_date:
        po.receiving_date = receiving_date
    po.notes = _append_note(po.notes, notes)
    db.commit()
    send_internal_alert(db, f"PO#{po.id} status -> {po.status.value}", "purchase_order", po.id)
    return po


def record_purchase_receipt(db: Session, po_id: int, receipt_items: list[dict], receipt_number: str = "", notes: str = ""):
    po = get_purchase_order(db, po_id)
    if not po:
        raise ValueError("PO not found")
    if not receipt_items:
        raise ValueError("Add at least one received item")

    receipt = GoodsReceipt(
        purchase_order_id=po.id,
        receipt_date=date.today(),
        receipt_number=receipt_number,
        notes=notes,
    )
    db.add(receipt)
    db.flush()

    received_any = False
    item_map = {item.id: item for item in po.items}
    for raw_item in receipt_items:
        po_item = item_map.get(raw_item["purchase_order_item_id"])
        if not po_item:
            continue
        quantity = float(raw_item.get("quantity_received", 0) or 0)
        if quantity <= 0:
            continue
        received_any = True
        po_item.quantity_received += quantity
        db.add(
            GoodsReceiptItem(
                receipt_id=receipt.id,
                purchase_order_item_id=po_item.id,
                product_id=po_item.product_id,
                quantity_received=quantity,
                notes=raw_item.get("notes", ""),
            )
        )
        add_stock(
            db,
            po_item.product_id,
            quantity,
            "goods_receipt",
            receipt.id,
            notes=f"Stock received against PO#{po.id}",
            commit=False,
        )

    if not received_any:
        raise ValueError("Add at least one received quantity")

    po.receiving_date = date.today()
    if all(item.quantity_received >= item.quantity_ordered for item in po.items):
        po.status = PurchaseOrderStatus.COMPLETED
    else:
        po.status = PurchaseOrderStatus.PARTIALLY_RECEIVED

    db.commit()
    db.refresh(receipt)
    send_internal_alert(db, f"Receipt {receipt.receipt_number or receipt.id} added for PO#{po.id}", "purchase_order", po.id)
    return receipt


def close_purchase_order(db: Session, po_id: int, close_note: str):
    po = get_purchase_order(db, po_id)
    if not po:
        raise ValueError("PO not found")
    po.status = PurchaseOrderStatus.CLOSED
    po.close_note = close_note
    po.notes = _append_note(po.notes, close_note)
    db.commit()
    vendor_name = po.vendor.firm_name or po.vendor.name
    close_msg = (
        f"Purchase Order #{po.id} (v{po.version_number}) is now CLOSED.\n"
        f"Vendor: {vendor_name}\n"
        f"Value: Rs {po.final_amount:,.0f}\n"
        f"Note: {close_note or 'Order completed.'}"
    )
    vendor_result = send_whatsapp_message(
        db, po.vendor.phone, close_msg, "purchase_order", po.id,
    )
    po.vendor_notification_status = vendor_result.status
    db.commit()
    send_internal_alert(db, f"PO#{po.id} closed", "purchase_order", po.id)
    return po


def receive_purchase_order(db: Session, po_id: int, receipt_number: str = "", receipt_file_path: str = "", notes: str = ""):
    po = get_purchase_order(db, po_id)
    if not po:
        raise ValueError("PO not found")
    receipt_items = [
        {
            "purchase_order_item_id": item.id,
            "quantity_received": max(item.quantity_ordered - item.quantity_received, 0),
            "notes": notes,
        }
        for item in po.items
    ]
    return record_purchase_receipt(db, po_id, receipt_items, receipt_number=receipt_number, notes=notes)


def add_vendor_bill(db: Session, po_id: int, bill_number: str, bill_date, bill_amount: float, gst_amount: float, file_path: str = ""):
    bill = VendorBill(
        purchase_order_id=po_id,
        bill_number=bill_number,
        bill_date=bill_date,
        bill_amount=bill_amount,
        gst_amount=gst_amount,
        file_path=file_path,
    )
    db.add(bill)
    db.commit()
    db.refresh(bill)
    return bill


def run_three_way_match(db: Session, po_id: int):
    po = get_purchase_order(db, po_id)
    if not po:
        raise ValueError("PO not found")
    bill = po.bills[-1] if po.bills else None
    receipt = po.receipts[-1] if po.receipts else None
    status = MatchStatus.PENDING
    notes = []
    if bill and receipt:
        amount_diff = abs((bill.bill_amount + bill.gst_amount) - po.final_amount)
        status = MatchStatus.MATCHED if amount_diff < 1 else MatchStatus.DISPUTED
        notes.append(f"amount_diff={amount_diff}")
    match = ThreeWayMatch(
        purchase_order_id=po.id,
        vendor_bill_id=bill.id if bill else None,
        goods_receipt_id=receipt.id if receipt else None,
        status=status,
        notes=", ".join(notes),
    )
    db.add(match)
    if status == MatchStatus.MATCHED:
        po.status = PurchaseOrderStatus.MATCHED
    elif status == MatchStatus.DISPUTED:
        po.status = PurchaseOrderStatus.DISPUTED
    db.commit()
    return match
