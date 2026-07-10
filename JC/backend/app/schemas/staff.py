from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class StaffPublic(BaseModel):
    id: int
    name: str
    phone: str
    permissions: List[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class StaffCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    phone: str = Field(..., min_length=10, max_length=15)
    permissions: List[str] = Field(default_factory=list)


class StaffUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    permissions: Optional[List[str]] = None
    is_active: Optional[bool] = None


class StaffCreateResponse(StaffPublic):
    whatsapp_sent: bool = False
    whatsapp_error: Optional[str] = None
    temp_password: str = ""


class StaffLoginRequest(BaseModel):
    phone: str
    password: str


class StaffLoginResponse(BaseModel):
    access_token: str
    expires_in_minutes: int
    staff: StaffPublic


class PermissionGroupOut(BaseModel):
    label: str
    permissions: List[dict]


class ActivityPublic(BaseModel):
    id: int
    actor_type: str
    actor_id: Optional[int]
    actor_name: str
    action: str
    entity_type: str
    entity_id: Optional[int]
    entity_label: Optional[str]
    detail: Optional[str]
    created_at: datetime


class ActivityListResponse(BaseModel):
    items: List[ActivityPublic]
    total: int
    limit: int
    offset: int
