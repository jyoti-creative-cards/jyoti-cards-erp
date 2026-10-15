"""Hindi WhatsApp updates for confirm, bill, and dispatch.

Order confirmation and dispatch are text only. The bill message is the one
that carries a PDF. Sending runs after the screen has already moved on, and
never raises. Sqlite tests do not send.
"""
from __future__ import annotations

import logging
import sys
import threading
from decimal import Decimal

from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrations.whatsapp.client import send_template, upload_media
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement

logger = logging.getLogger("jc.whatsapp")

PORTAL_URL = "https://jyoticards.vercel.app"

ORDER_TEMPLATE = "order_confirmed_hindi"
BILL_TEMPLATE = "bill_ready_hindi"
DISPATCH_TEMPLATE = "dispatch_sent_hindi"
ORDER_CANCEL_TEMPLATE = "order_cancelled_hindi"
BILL_CANCEL_TEMPLATE = "bill_cancelled_hindi"


def order_confirmation_params(
    customer_name: str,
    order_no: str,
    item: str,
    quantity: int,
    rate: str,
) -> list[str]:
    return [customer_name, order_no, item, str(int(quantity)), rate, PORTAL_URL]


def bill_ready_params(customer_name: str, bill_number: str, amount: str) -> list[str]:
    return [customer_name, bill_number, amount]


def dispatch_ready_params(customer_name: str, bill_number: str) -> list[str]:
    return [customer_name, bill_number]


def order_cancelled_params(customer_name: str, order_no: str) -> list[str]:
    return [customer_name, order_no]


def bill_cancelled_params(customer_name: str, bill_number: str) -> list[str]:
    return [customer_name, bill_number]


def notify_order_confirmed(db: Session, placement_id: int) -> None:
    if not _allow(db):
        return
    try:
        placement = db.get(CustomerOrderPlacement, placement_id)
        if not placement:
            return
        order = db.get(CustomerOrder, placement.customer_order_id)
        if not order:
            return
        customer = db.get(Customer, order.customer_id)
        if not customer or not customer.phone:
            return
        lines = (
            db.query(CustomerOrderLine)
            .filter(
                CustomerOrderLine.placement_id == placement.id,
                CustomerOrderLine.status == "active",
            )
            .order_by(CustomerOrderLine.id.asc())
            .all()
        )
        if not lines:
            return
        first = lines[0]
        extra = len(lines) - 1
        item = (first.our_product_id or "").strip() or "-"
        if extra > 0:
            item = f"{item} (+{extra})"
        qty = sum(int(ln.quantity or 0) for ln in lines)
        rate = format(Decimal(str(first.unit_price or 0)), "f")
        result = send_template(
            customer.phone,
            ORDER_TEMPLATE,
            language="hi",
            body_params=order_confirmation_params(
                customer.business_name or "Customer",
                str(placement.id),
                item,
                qty,
                rate,
            ),
        )
        if not result.get("ok"):
            logger.error("WhatsApp order %s failed: %s", placement_id, result.get("error"))
    except Exception:
        logger.exception("WhatsApp order %s failed", placement_id)


def notify_bill_created(db: Session, bill_id: int) -> None:
    if not _allow(db):
        return
    try:
        bill = db.get(CustomerBill, bill_id)
        if not bill:
            return
        customer = db.get(Customer, bill.customer_id)
        if not customer or not customer.phone:
            return
        pdf = _bill_pdf(db, bill.id)
        if not pdf:
            logger.error("WhatsApp bill %s skipped: no PDF", bill_id)
            return
        media = upload_media(pdf, f"{bill.bill_number}.pdf")
        if not media.get("ok"):
            logger.error("WhatsApp bill %s upload failed: %s", bill_id, media.get("error"))
            return
        amount = format(Decimal(str(bill.grand_total or 0)), "f")
        result = send_template(
            customer.phone,
            BILL_TEMPLATE,
            language="hi",
            body_params=bill_ready_params(customer.business_name or "Customer", bill.bill_number, amount),
            header_media_id=media.get("media_id"),
            header_filename=f"{bill.bill_number}.pdf",
        )
        if not result.get("ok"):
            logger.error("WhatsApp bill %s failed: %s", bill_id, result.get("error"))
    except Exception:
        logger.exception("WhatsApp bill %s failed", bill_id)


def notify_dispatched(db: Session, bill_id: int) -> None:
    if not _allow(db):
        return
    try:
        bill = db.get(CustomerBill, bill_id)
        if not bill:
            return
        customer = db.get(Customer, bill.customer_id)
        if not customer or not customer.phone:
            return
        result = send_template(
            customer.phone,
            DISPATCH_TEMPLATE,
            language="hi",
            body_params=dispatch_ready_params(customer.business_name or "Customer", bill.bill_number),
        )
        if not result.get("ok"):
            logger.error("WhatsApp dispatch %s failed: %s", bill_id, result.get("error"))
    except Exception:
        logger.exception("WhatsApp dispatch %s failed", bill_id)


def notify_order_cancelled(db: Session, placement_id: int) -> None:
    if not _allow(db):
        return
    try:
        placement = db.get(CustomerOrderPlacement, placement_id)
        if not placement:
            return
        order = db.get(CustomerOrder, placement.customer_order_id)
        if not order:
            return
        customer = db.get(Customer, order.customer_id)
        if not customer or not customer.phone:
            return
        result = send_template(
            customer.phone,
            ORDER_CANCEL_TEMPLATE,
            language="hi",
            body_params=order_cancelled_params(customer.business_name or "Customer", str(placement.id)),
        )
        if not result.get("ok"):
            logger.error("WhatsApp order cancel %s failed: %s", placement_id, result.get("error"))
    except Exception:
        logger.exception("WhatsApp order cancel %s failed", placement_id)


def notify_bill_cancelled(db: Session, bill_id: int) -> None:
    if not _allow(db):
        return
    try:
        bill = db.get(CustomerBill, bill_id)
        if not bill:
            return
        customer = db.get(Customer, bill.customer_id)
        if not customer or not customer.phone:
            return
        result = send_template(
            customer.phone,
            BILL_CANCEL_TEMPLATE,
            language="hi",
            body_params=bill_cancelled_params(customer.business_name or "Customer", bill.bill_number),
        )
        if not result.get("ok"):
            logger.error("WhatsApp bill cancel %s failed: %s", bill_id, result.get("error"))
    except Exception:
        logger.exception("WhatsApp bill cancel %s failed", bill_id)


def schedule_whatsapp(kind: str, entity_id: int) -> None:
    """Send after this request returns. The screen does not wait on Meta or a PDF."""
    if "pytest" in sys.modules:
        return
    threading.Thread(
        target=_deliver,
        args=(kind, int(entity_id)),
        daemon=True,
        name=f"wa-{kind}-{entity_id}",
    ).start()


def _deliver(kind: str, entity_id: int) -> None:
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        if kind == "order_confirmed":
            notify_order_confirmed(db, entity_id)
        elif kind == "order_cancelled":
            notify_order_cancelled(db, entity_id)
        elif kind == "bill_created":
            notify_bill_created(db, entity_id)
        elif kind == "bill_cancelled":
            notify_bill_cancelled(db, entity_id)
        elif kind == "dispatched":
            notify_dispatched(db, entity_id)
    except Exception:
        logger.exception("WhatsApp %s %s failed", kind, entity_id)
    finally:
        db.close()


def _allow(db: Session) -> bool:
    try:
        if db.get_bind().dialect.name == "sqlite":
            return False
    except Exception:
        return False
    settings = get_settings()
    if settings.whatsapp_disable or not (settings.whatsapp_access_token or "").strip():
        return False
    return True


def _bill_pdf(db: Session, bill_id: int) -> bytes | None:
    from app.services.doc_jobs import bill_file_pdf_bytes

    return bill_file_pdf_bytes(db, bill_id)
