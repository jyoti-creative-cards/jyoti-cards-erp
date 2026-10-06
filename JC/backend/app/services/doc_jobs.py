"""Build a PDF once and store it. Later prints read that file."""

from __future__ import annotations

import logging
import sys
import threading

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.deps import AuthContext
from app.services.cost_visibility import can_see_cost
from app.services.doc_gen import (
    generate_customer_bill_document,
    generate_customer_order_document,
    generate_vendor_receipt_document,
)
from app.services.storage import download_bytes

log = logging.getLogger(__name__)
_locks: dict[tuple[str, int], threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(kind: str, entity_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault((kind, entity_id), threading.Lock())


def _start(kind: str, entity_id: int, show_cost: bool) -> None:
    if "pytest" in sys.modules:
        return
    threading.Thread(target=_job, args=(kind, entity_id, show_cost), daemon=True).start()


def enqueue_bill_pdf(bill_id: int) -> None:
    _start("bill", bill_id, False)


def enqueue_order_pdf(placement_id: int) -> None:
    _start("order", placement_id, False)


def enqueue_receipt_pdf(receipt_id: int, auth: AuthContext | None = None) -> None:
    _start("receipt", receipt_id, can_see_cost(auth))


def _job(kind: str, entity_id: int, show_cost: bool) -> None:
    db = SessionLocal()
    try:
        if kind == "bill":
            bill_pdf_bytes(db, entity_id)
        elif kind == "order":
            order_pdf_key(db, entity_id)
        elif kind == "receipt":
            receipt_pdf_key(db, entity_id, _cost_auth(show_cost))
    except Exception:
        db.rollback()
        log.warning("%s pdf job failed id=%s", kind, entity_id, exc_info=True)
    finally:
        db.close()


def _cost_auth(show_cost: bool) -> AuthContext:
    permissions = {"costs.read"} if show_cost else set()
    return AuthContext("staff", None, "System", permissions)


def bill_pdf_bytes(db: Session, bill_id: int) -> bytes | None:
    from app.models.customer_bill import CustomerBill

    with _lock("bill", bill_id):
        bill = db.get(CustomerBill, bill_id)
        if not bill:
            return None
        if bill.document_key:
            stored = download_bytes(bill.document_key)
            if stored:
                return stored
        generate_customer_bill_document(db, bill_id)
        fresh = getattr(bill, "_pdf_bytes", None)
        db.commit()
        if fresh:
            return fresh
        db.refresh(bill)
        if bill.document_key:
            return download_bytes(bill.document_key)
        return None


def order_pdf_key(db: Session, placement_id: int) -> str | None:
    from app.models.customer_order import CustomerOrderPlacement

    with _lock("order", placement_id):
        placement = db.get(CustomerOrderPlacement, placement_id)
        if not placement:
            return None
        if placement.document_key:
            return placement.document_key
        generate_customer_order_document(db, placement_id)
        db.commit()
        db.refresh(placement)
        return placement.document_key


def receipt_pdf_key(db: Session, receipt_id: int, auth: AuthContext | None) -> str | None:
    from app.models.stock import StockReceipt

    with _lock("receipt", receipt_id):
        receipt = db.get(StockReceipt, receipt_id)
        if not receipt:
            return None
        if receipt.receipt_document_key:
            return receipt.receipt_document_key
        generate_vendor_receipt_document(db, receipt_id, auth)
        db.commit()
        db.refresh(receipt)
        return receipt.receipt_document_key
