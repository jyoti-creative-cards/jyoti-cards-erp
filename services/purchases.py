from datetime import date
from sqlalchemy.orm import Session

from backend.services.whatsapp import send_internal_alert, send_whatsapp_message
from db.models import PurchaseOrder, PurchaseOrderItem, PurchaseOrderStatus, Ledger, VendorBill, GoodsReceipt, ThreeWayMatch, MatchStatus
from services.inventory import add_stock


def list_purchase_orders(db: Session, status: str = None):
    q = db.query(PurchaseOrder).order_by(PurchaseOrder.created_at.desc())
    if status:
        q = q.filter(PurchaseOrder.status == status)
    return q.all()


def get_purchase_order(db: Session, po_id: int):
    return db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()


def create_purchase_order(db: Session, vendor_id: int, items: list[dict], order_date=None, expected_date=None, vendor_committed_date=None, shipment_mode="", transport_name="", transport_contact="", notes=""):
    subtotal = sum(i["quantity"] * i["unit_price"] for i in items)
    gst_amount = sum((i["quantity"] * i["unit_price"]) * (i.get("gst_percent", 0) / 100) for i in items)
    po = PurchaseOrder(
        vendor_id=vendor_id,
        order_date=order_date or date.today(),
        expected_date=expected_date,
        vendor_committed_date=vendor_committed_date,
        total_amount=subtotal,
        gst_amount=gst_amount,
        final_amount=subtotal + gst_amount,
        shipment_mode=shipment_mode,
        transport_name=transport_name,
        transport_contact=transport_contact,
        notes=notes,
    )
    db.add(po)
    db.flush()

    for i in items:
        db.add(PurchaseOrderItem(
            order_id=po.id,
            product_id=i["product_id"],
            quantity_ordered=i["quantity"],
            quantity_received=0,
            unit_price=i["unit_price"],
            gst_percent=i.get("gst_percent", 0),
            total_price=i["quantity"] * i["unit_price"],
        ))

    db.add(Ledger(entity_type="vendor", entity_id=vendor_id, debit=po.final_amount, credit=0, description=f"PO#{po.id} created", reference_type="purchase_order", reference_id=po.id))
    db.commit()
    db.refresh(po)

    vendor_message = f"PO#{po.id} created for ₹{po.final_amount:,.0f}. Items: " + ", ".join([f"{i['quantity']} pcs" for i in items])
    vendor_result = send_whatsapp_message(db, po.vendor.phone, vendor_message, "purchase_order", po.id)
    internal_result = send_internal_alert(db, f"PO#{po.id} created for {po.vendor.name}", "purchase_order", po.id)
    po.vendor_notification_status = vendor_result.status
    po.internal_notification_status = internal_result.status
    db.commit()
    return po


def update_purchase_order_status(db: Session, po_id: int, new_status, loading_date=None, receiving_date=None, notes=None):
    po = get_purchase_order(db, po_id)
    if not po:
        raise ValueError("PO not found")
    po.status = new_status
    if loading_date:
        po.loading_date = loading_date
    if receiving_date:
        po.receiving_date = receiving_date
    if notes:
        po.notes = (po.notes or "") + f"\n{notes}"
    db.commit()
    send_internal_alert(db, f"PO#{po.id} status -> {po.status.value}", "purchase_order", po.id)
    return po


def receive_purchase_order(db: Session, po_id: int, receipt_number: str = "", receipt_file_path: str = "", notes: str = ""):
    po = get_purchase_order(db, po_id)
    if not po:
        raise ValueError("PO not found")
    for item in po.items:
        pending_qty = item.quantity_ordered - item.quantity_received
        if pending_qty > 0:
            item.quantity_received += pending_qty
            add_stock(db, item.product_id, pending_qty, "purchase_order", po.id, notes="Stock added on goods receipt", commit=False)
    po.status = PurchaseOrderStatus.RECEIVED
    po.receiving_date = date.today()
    receipt = GoodsReceipt(purchase_order_id=po.id, receipt_date=date.today(), receipt_number=receipt_number, file_path=receipt_file_path, notes=notes)
    db.add(receipt)
    db.commit()
    db.refresh(po)
    send_internal_alert(db, f"PO#{po.id} goods received", "purchase_order", po.id)
    return po


def add_vendor_bill(db: Session, po_id: int, bill_number: str, bill_date, bill_amount: float, gst_amount: float, file_path: str = ""):
    bill = VendorBill(purchase_order_id=po_id, bill_number=bill_number, bill_date=bill_date, bill_amount=bill_amount, gst_amount=gst_amount, file_path=file_path)
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
    if bill and receipt and po.status == PurchaseOrderStatus.RECEIVED:
        amount_diff = abs((bill.bill_amount + bill.gst_amount) - po.final_amount)
        status = MatchStatus.MATCHED if amount_diff < 1 else MatchStatus.DISPUTED
        notes.append(f"amount_diff={amount_diff}")
    match = ThreeWayMatch(purchase_order_id=po.id, vendor_bill_id=bill.id if bill else None, goods_receipt_id=receipt.id if receipt else None, status=status, notes=", ".join(notes))
    db.add(match)
    if status == MatchStatus.MATCHED:
        po.status = PurchaseOrderStatus.MATCHED
    elif status == MatchStatus.DISPUTED:
        po.status = PurchaseOrderStatus.DISPUTED
    db.commit()
    return match
