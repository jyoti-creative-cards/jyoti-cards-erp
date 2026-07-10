from __future__ import annotations

import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.services.storage import (
    copy_object,
    create_folder,
    delete_key,
    documents_root,
    list_objects,
    move_object,
    presigned_url,
    storage_configured,
    upload_bytes,
)

router = APIRouter(prefix="/documents", tags=["documents"])


class FolderCreate(BaseModel):
    prefix: str
    name: str


class RenameIn(BaseModel):
    src_key: str
    dest_key: str


@router.get("")
def browse_documents(
    prefix: str = Query("JCC/"),
    db: Session = Depends(get_db),
    auth=Depends(require_admin),
):
    if not storage_configured():
        raise HTTPException(503, "S3 storage not configured")
    if not prefix:
        prefix = documents_root()
    if not prefix.endswith("/"):
        prefix = prefix + "/"
    data = list_objects(prefix)
    folders = [{"prefix": p, "name": p.rstrip("/").split("/")[-1] + "/"} for p in data.get("prefixes", [])]
    files = []
    for obj in data.get("objects", []):
        key = obj["key"]
        files.append({
            "key": key,
            "name": os.path.basename(key),
            "size": obj.get("size"),
            "last_modified": obj.get("last_modified"),
            "url": presigned_url(key),
        })
    return {"prefix": prefix, "folders": folders, "files": files}


@router.post("/upload")
async def upload_document(
    prefix: str = Form("JCC/documents/"),
    file: UploadFile = File(...),
    auth=Depends(require_admin),
):
    if not storage_configured():
        raise HTTPException(503, "S3 storage not configured")
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    base = prefix if prefix.endswith("/") else f"{prefix}/"
    fname = (file.filename or "upload").replace("/", "_")
    key = f"{base}{uuid.uuid4().hex[:8]}_{fname}"
    upload_bytes(key, data, file.content_type or "application/octet-stream")
    return {"ok": True, "key": key, "url": presigned_url(key)}


@router.post("/folder")
def create_document_folder(body: FolderCreate, auth=Depends(require_admin)):
    if not storage_configured():
        raise HTTPException(503, "S3 storage not configured")
    base = body.prefix if body.prefix.endswith("/") else f"{body.prefix}/"
    safe = body.name.strip().replace("/", "_")
    key = create_folder(f"{base}{safe}")
    return {"ok": True, "prefix": key}


@router.patch("/rename")
def rename_document(body: RenameIn, auth=Depends(require_admin)):
    if not storage_configured():
        raise HTTPException(503, "S3 storage not configured")
    if not body.src_key or not body.dest_key:
        raise HTTPException(400, "src_key and dest_key required")
    move_object(body.src_key, body.dest_key)
    return {"ok": True, "key": body.dest_key, "url": presigned_url(body.dest_key)}


@router.patch("/move")
def move_document(body: RenameIn, auth=Depends(require_admin)):
    return rename_document(body, auth)


@router.delete("")
def delete_document(key: str = Query(...), auth=Depends(require_admin)):
    if not storage_configured():
        raise HTTPException(503, "S3 storage not configured")
    delete_key(key)
    return {"ok": True}
