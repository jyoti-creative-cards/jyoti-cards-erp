"""Excel export + full backup zip."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import AuthContext, require_admin
from app.services.activity import log_from_auth
from app.services.export_data import EXPORT_KINDS, build_backup_zip
from app.services.full_backup import build_full_backup_zip

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/kinds")
def list_kinds(auth: AuthContext = Depends(require_admin)):
    return {"kinds": sorted(EXPORT_KINDS.keys()) + ["full"]}


@router.get("/backup.zip")
def export_backup(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    """Full business backup — every DB table as Excel (zip of workbooks)."""
    data = build_full_backup_zip(db)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_from_auth(
        db, auth, action="backup", entity_type="export",
        entity_label="full_backup.zip", detail=f"{len(data)} bytes",
    )
    db.commit()
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="jc_full_backup_{stamp}.zip"'},
    )


@router.get("/backup-summary.zip")
def export_backup_summary(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    """Legacy summary-only zip (aggregates). Prefer /backup.zip for full dump."""
    data = build_backup_zip(db)
    log_from_auth(db, auth, action="backup", entity_type="export", entity_label="backup-summary.zip", detail=f"{len(data)} bytes")
    db.commit()
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="jc_backup_summary.zip"'},
    )


@router.get("/{kind}.xlsx")
def export_kind(
    kind: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_admin),
):
    fn = EXPORT_KINDS.get(kind)
    if not fn:
        raise HTTPException(404, f"unknown export kind; try: {', '.join(sorted(EXPORT_KINDS))}")
    data = fn(db)
    log_from_auth(db, auth, action="export", entity_type="export", entity_label=kind, detail=f"{len(data)} bytes")
    db.commit()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{kind}.xlsx"'},
    )
