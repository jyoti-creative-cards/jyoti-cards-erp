from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.deps import AuthContext, get_auth_context
from app.services.whatsapp_gate import set_whatsapp_sends, whatsapp_sends_enabled

router = APIRouter(prefix="/settings", tags=["settings"])


class WhatsappSendsIn(BaseModel):
    enabled: bool


class WhatsappSendsOut(BaseModel):
    enabled: bool


@router.get("/whatsapp", response_model=WhatsappSendsOut)
def get_whatsapp_sends(_auth: AuthContext = Depends(get_auth_context)) -> WhatsappSendsOut:
    return WhatsappSendsOut(enabled=whatsapp_sends_enabled())


@router.put("/whatsapp", response_model=WhatsappSendsOut)
def put_whatsapp_sends(
    body: WhatsappSendsIn,
    _auth: AuthContext = Depends(get_auth_context),
) -> WhatsappSendsOut:
    return WhatsappSendsOut(enabled=set_whatsapp_sends(body.enabled))
