"""Download / print PDFs + WhatsApp share for bills, statements, daybook, ageing."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin, require_any_permission, require_permission
from app.integrations.whatsapp.client import send_document, upload_media, wa_me_link
from app.models.customer import Customer
from app.models.customer_bill import CustomerBill
from app.models.freight_agent import FreightAgent, FreightLedgerEntry
from app.models.vendor import Vendor
from app.services.activity import log_from_auth
from app.services.doc_gen import generate_customer_bill_document
from app.services.report_pdfs import (
    render_ageing_pdf,
    render_ap_statement_pdf,
    render_ar_statement_pdf,
    render_daybook_pdf,
    render_freight_payment_pdf,
    render_freight_statement_pdf,
)
router = APIRouter(prefix="/share", tags=["share"])


def _pdf_response(data: bytes, filename: str) -> Response:
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/bills/{bill_id}/pdf")
def bill_pdf(
    bill_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_any_permission("customer_orders.read", "vendor_orders.read")),
):
    bill = db.get(CustomerBill, bill_id)
    if not bill:
        raise HTTPException(404, "bill not found")
    generate_customer_bill_document(db, bill_id)
    db.commit()
    bill = db.get(CustomerBill, bill_id)
    from app.services.storage import download_bytes

    if not bill or not bill.document_key:
        raise HTTPException(500, "could not generate bill PDF")
    data = download_bytes(bill.document_key)
    if not data:
        # regenerate
        generate_customer_bill_document(db, bill_id)
        db.commit()
        bill = db.get(CustomerBill, bill_id)
        data = download_bytes(bill.document_key) if bill and bill.document_key else None
    if not data:
        raise HTTPException(500, "PDF unavailable")
    return _pdf_response(data, f"{bill.bill_number}.pdf")


@router.get("/statements/ar/{customer_id}/pdf")
def ar_statement_pdf(
    customer_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    if not db.get(Customer, customer_id):
        raise HTTPException(404, "customer not found")
    return _pdf_response(render_ar_statement_pdf(db, customer_id), f"ar_{customer_id}.pdf")


@router.get("/statements/ap/{vendor_id}/pdf")
def ap_statement_pdf(
    vendor_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    if not db.get(Vendor, vendor_id):
        raise HTTPException(404, "vendor not found")
    return _pdf_response(render_ap_statement_pdf(db, vendor_id), f"ap_{vendor_id}.pdf")


@router.get("/daybook/pdf")
def daybook_pdf(
    day: date = Query(...),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return _pdf_response(render_daybook_pdf(db, day), f"daybook_{day.isoformat()}.pdf")


@router.get("/ageing/pdf")
def ageing_pdf(
    side: str = Query("ar", pattern="^(ar|ap)$"),
    as_of: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    return _pdf_response(render_ageing_pdf(db, side, as_of), f"ageing_{side}.pdf")


@router.get("/statements/freight/{agent_id}/pdf")
def freight_statement_pdf(
    agent_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    if not db.get(FreightAgent, agent_id):
        raise HTTPException(404, "freight agent not found")
    return _pdf_response(render_freight_statement_pdf(db, agent_id), f"freight_{agent_id}.pdf")


@router.get("/freight-payments/{entry_id}/pdf")
def freight_payment_pdf(
    entry_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    entry = db.get(FreightLedgerEntry, entry_id)
    if not entry or entry.entry_type not in ("settlement", "advance"):
        raise HTTPException(404, "freight payment not found")
    if entry.document_key:
        from app.services.storage import download_bytes

        data = download_bytes(entry.document_key)
        if data:
            return _pdf_response(data, f"freight_pay_{entry_id}.pdf")
    try:
        pdf = render_freight_payment_pdf(db, agent_id=entry.freight_agent_id, entry_id=entry.id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return _pdf_response(pdf, f"freight_pay_{entry_id}.pdf")


class WhatsAppShareIn(BaseModel):
    phone: Optional[str] = None
    caption: str = ""
    kind: str = Field(
        ...,
        description="bill|ar_statement|ap_statement|daybook|ageing|freight_statement|freight_payment",
    )
    id: Optional[int] = None
    day: Optional[date] = None
    side: Optional[str] = "ar"


@router.post("/whatsapp")
def whatsapp_share(
    body: WhatsAppShareIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    """Upload PDF to WhatsApp and send as document (24h session window).
    Also returns wa.me fallback link.
    """
    pdf: bytes
    filename: str
    phone = (body.phone or "").strip()

    if body.kind == "bill":
        bill = db.get(CustomerBill, body.id or 0)
        if not bill:
            raise HTTPException(404, "bill not found")
        cust = db.get(Customer, bill.customer_id)
        phone = phone or (cust.phone if cust else "")
        generate_customer_bill_document(db, bill.id)
        db.commit()
        bill = db.get(CustomerBill, bill.id)
        from app.services.storage import download_bytes

        pdf = download_bytes(bill.document_key) if bill and bill.document_key else b""
        if not pdf:
            raise HTTPException(500, "bill PDF missing")
        filename = f"{bill.bill_number}.pdf"
        caption = body.caption or f"Bill {bill.bill_number}"
    elif body.kind == "ar_statement":
        cust = db.get(Customer, body.id or 0)
        if not cust:
            raise HTTPException(404, "customer not found")
        phone = phone or cust.phone
        pdf = render_ar_statement_pdf(db, cust.id)
        filename = f"statement_{cust.id}.pdf"
        caption = body.caption or f"Statement — {cust.business_name}"
    elif body.kind == "ap_statement":
        vend = db.get(Vendor, body.id or 0)
        if not vend:
            raise HTTPException(404, "vendor not found")
        phone = phone or vend.phone
        pdf = render_ap_statement_pdf(db, vend.id)
        filename = f"ap_{vend.id}.pdf"
        caption = body.caption or f"Statement — {vend.business_name}"
    elif body.kind == "daybook":
        if not body.day:
            raise HTTPException(400, "day required")
        pdf = render_daybook_pdf(db, body.day)
        filename = f"daybook_{body.day.isoformat()}.pdf"
        caption = body.caption or f"Daybook {body.day.isoformat()}"
    elif body.kind == "ageing":
        side = body.side if body.side in ("ar", "ap") else "ar"
        pdf = render_ageing_pdf(db, side)
        filename = f"ageing_{side}.pdf"
        caption = body.caption or f"Ageing {side.upper()}"
    elif body.kind == "freight_statement":
        agent = db.get(FreightAgent, body.id or 0)
        if not agent:
            raise HTTPException(404, "freight agent not found")
        pdf = render_freight_statement_pdf(db, agent.id)
        filename = f"freight_{agent.id}.pdf"
        caption = body.caption or f"Freight — {agent.name}"
    elif body.kind == "freight_payment":
        entry = db.get(FreightLedgerEntry, body.id or 0)
        if not entry or entry.entry_type not in ("settlement", "advance"):
            raise HTTPException(404, "freight payment not found")
        agent = db.get(FreightAgent, entry.freight_agent_id)
        if entry.document_key:
            from app.services.storage import download_bytes

            pdf = download_bytes(entry.document_key) or b""
        else:
            pdf = b""
        if not pdf:
            pdf = render_freight_payment_pdf(db, agent_id=entry.freight_agent_id, entry_id=entry.id)
        filename = f"freight_pay_{entry.id}.pdf"
        caption = body.caption or f"Freight pay — {agent.name if agent else entry.id}"
    else:
        raise HTTPException(400, "unknown kind")

    if not phone:
        raise HTTPException(400, "phone required")

    up = upload_media(pdf, filename)
    wa_result = {"ok": False}
    if up.get("ok"):
        wa_result = send_document(phone, media_id=up["media_id"], filename=filename, caption=caption)
    link = wa_me_link(phone, caption)
    log_from_auth(
        db, auth, action="whatsapp_share", entity_type=body.kind,
        entity_id=body.id, entity_label=filename,
        detail=f"to {phone} ok={wa_result.get('ok')} err={wa_result.get('error')}",
    )
    db.commit()
    return {
        "ok": bool(wa_result.get("ok")),
        "whatsapp": wa_result,
        "upload": {"ok": up.get("ok"), "error": up.get("error")},
        "wa_me": link,
        "hint": (
            "Document sent."
            if wa_result.get("ok")
            else "API send failed (often needs 24h customer session or approved doc template). Use wa_me link or download PDF."
        ),
    }
