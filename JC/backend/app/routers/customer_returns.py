from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin, require_permission
from app.schemas.customer_return import (
    CustomerReturnCreate,
    CustomerReturnDetail,
    CustomerReturnLineOut,
    CustomerReturnListItem,
    CustomerReturnSummary,
    ReturnableLineOut,
)
from app.schemas.stock import VoidIn
from app.services.activity import log_from_auth
from app.services.customer_returns import (
    create_customer_return,
    generate_customer_return_document,
    get_return_detail,
    list_customer_returns,
    list_returnable_lines,
    list_returns_by_customer,
)
from app.services.storage import presigned_url, storage_configured
from app.services.void_service import void_customer_return
from app.models.customer_return import CustomerReturn

router = APIRouter(prefix="/customer-returns", tags=["customer-returns"])


@router.get("", response_model=List[CustomerReturnSummary])
def list_returns(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("returns.read")),
):
    return [CustomerReturnSummary(**r) for r in list_returns_by_customer(db)]


@router.get("/customer/{customer_id}", response_model=List[CustomerReturnListItem])
def list_for_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("returns.read")),
):
    return [CustomerReturnListItem(**r) for r in list_customer_returns(db, customer_id)]


@router.get("/customer/{customer_id}/returnable", response_model=List[ReturnableLineOut])
def returnable_lines(
    customer_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("returns.read")),
):
    return [ReturnableLineOut(**r) for r in list_returnable_lines(db, customer_id)]


@router.post("", response_model=CustomerReturnDetail, status_code=status.HTTP_201_CREATED)
def create_return(
    body: CustomerReturnCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("returns.write")),
):
    ret = create_customer_return(
        db,
        customer_id=body.customer_id,
        lines=[ln.model_dump() for ln in body.lines],
        credit_amount=body.credit_amount,
        notes=body.notes,
        actor_type=auth.actor_type,
        actor_id=auth.actor_id,
        actor_name=auth.actor_name,
    )
    log_from_auth(
        db,
        auth,
        action="customer_return",
        entity_type="customer_return",
        entity_id=ret.id,
        entity_label=ret.return_number,
        detail=f"credit ₹{ret.credit_amount}",
    )
    db.commit()
    detail = get_return_detail(db, ret.id)
    return CustomerReturnDetail(
        **{k: v for k, v in detail.items() if k != "lines"},
        lines=[CustomerReturnLineOut(**ln) for ln in detail["lines"]],
    )


@router.get("/{return_id}", response_model=CustomerReturnDetail)
def get_return(
    return_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("returns.read")),
):
    detail = get_return_detail(db, return_id)
    return CustomerReturnDetail(
        **{k: v for k, v in detail.items() if k != "lines"},
        lines=[CustomerReturnLineOut(**ln) for ln in detail["lines"]],
    )


@router.post("/{return_id}/void", dependencies=[Depends(require_admin)])
def void_return_endpoint(
    return_id: int,
    body: VoidIn,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    from app.services import response_cache

    result = void_customer_return(db, auth, return_id, body.reason)
    response_cache.invalidate("stock:")
    response_cache.invalidate("shop:")
    return result


@router.get("/{return_id}/document")
def get_return_document(
    return_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_permission("returns.read")),
):
    ret = db.get(CustomerReturn, return_id)
    if not ret:
        raise HTTPException(404, "return not found")
    if not ret.document_key and storage_configured():
        try:
            generate_customer_return_document(db, ret.id)
            db.commit()
        except Exception:
            db.rollback()
            ret = db.get(CustomerReturn, return_id)
    if not ret or not ret.document_key:
        raise HTTPException(404, "document not available")
    url = presigned_url(ret.document_key)
    if not url:
        raise HTTPException(503, "storage not available")
    return {"document_url": url, "document_key": ret.document_key, "return_number": ret.return_number}
