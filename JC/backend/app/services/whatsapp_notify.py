"""Hindi WhatsApp updates for confirm, bill, and dispatch.

Order confirmation uses the approved template order_confirmation (PDF + portal button).
Bill and dispatch use bill_ready_hindi and dispatch_ready_hindi, which write the
portal address in the message. Sending never raises and never runs on sqlite tests.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrations.whatsapp.client import send_template, upload_media
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.models.customer_order import CustomerOrder, CustomerOrderLine, CustomerOrderPlacement

logger = logging.getLogger("jc.whatsapp")

PORTAL_URL = "https://jyoticards.vercel.app"
# Dynamic button on order_confirmation is https://jyoticards.vercel.app/{{1}}.
# "?" keeps the click on the portal home.
PORTAL_BUTTON_SUFFIX = "?"

ORDER_TEMPLATE = "order_confirmation"
BILL_TEMPLATE = "bill_ready_hindi"
DISPATCH_TEMPLATE = "dispatch_ready_hindi"


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
        pdf = _order_pdf(db, placement)
        if not pdf:
            logger.error("WhatsApp order %s skipped: no PDF", placement_id)
            return
        media = upload_media(pdf, f"order-{placement.id}.pdf")
        if not media.get("ok"):
            logger.error("WhatsApp order %s upload failed: %s", placement_id, media.get("error"))
            return
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
            header_media_id=media.get("media_id"),
            header_filename=f"order-{placement.id}.pdf",
            url_button_suffix=PORTAL_BUTTON_SUFFIX,
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
        pdf = _bill_pdf(db, bill.id)
        if not pdf:
            logger.error("WhatsApp dispatch %s skipped: no PDF", bill_id)
            return
        media = upload_media(pdf, f"dispatch-{bill.bill_number}.pdf")
        if not media.get("ok"):
            logger.error("WhatsApp dispatch %s upload failed: %s", bill_id, media.get("error"))
            return
        result = send_template(
            customer.phone,
            DISPATCH_TEMPLATE,
            language="hi",
            body_params=dispatch_ready_params(customer.business_name or "Customer", bill.bill_number),
            header_media_id=media.get("media_id"),
            header_filename=f"dispatch-{bill.bill_number}.pdf",
        )
        if not result.get("ok"):
            logger.error("WhatsApp dispatch %s failed: %s", bill_id, result.get("error"))
    except Exception:
        logger.exception("WhatsApp dispatch %s failed", bill_id)


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


def _order_pdf(db: Session, placement: CustomerOrderPlacement) -> bytes | None:
    from app.services.doc_gen import generate_customer_order_document
    from app.services.storage import download_bytes

    if placement.document_key:
        stored = download_bytes(placement.document_key)
        if stored:
            return stored
    generate_customer_order_document(db, placement.id)
    db.commit()
    if placement.document_key:
        return download_bytes(placement.document_key)
    return None


def _bill_pdf(db: Session, bill_id: int) -> bytes | None:
    from app.services.doc_jobs import bill_file_pdf_bytes

    return bill_file_pdf_bytes(db, bill_id)
