"""Supabase Storage (S3-compatible). Env-only credentials — never commit secrets."""
from __future__ import annotations

import os
from typing import Optional, Sequence


def _endpoint() -> str:
    return (
        (os.environ.get("S3_ENDPOINT_URL") or os.environ.get("AWS_ENDPOINT_URL") or "")
        .strip()
        .rstrip("/")
    )


def _bucket() -> str:
    return (os.environ.get("S3_BUCKET") or os.environ.get("AWS_S3_BUCKET") or "files").strip()


def _region() -> str:
    return (os.environ.get("S3_REGION") or os.environ.get("AWS_REGION") or "ap-southeast-1").strip()


def _ak() -> str:
    return (os.environ.get("S3_ACCESS_KEY_ID") or os.environ.get("AWS_ACCESS_KEY_ID") or "").strip()


def _sk() -> str:
    return (os.environ.get("S3_SECRET_ACCESS_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY") or "").strip()


def s3_enabled() -> bool:
    return bool(_endpoint() and _bucket() and _ak() and _sk())


def _client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=_endpoint(),
        aws_access_key_id=_ak(),
        aws_secret_access_key=_sk(),
        region_name=_region(),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    )


def put_bytes(key: str, data: bytes, content_type: str) -> None:
    """Upload object; key is path inside bucket e.g. products/12.png."""
    c = _client()
    c.put_object(
        Bucket=_bucket(),
        Key=key.lstrip("/"),
        Body=data,
        ContentType=content_type,
    )


def delete_key(key: str) -> None:
    key = key.lstrip("/")
    if not key:
        return
    c = _client()
    c.delete_object(Bucket=_bucket(), Key=key)


def presigned_get_url(key: str, expires_s: int = 3600) -> str:
    key = key.lstrip("/")
    c = _client()
    return c.generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": key},
        ExpiresIn=expires_s,
    )


def put_product_uploads(product_id: int, uploaded_files: Optional[Sequence[object]]) -> list[str]:
    """Upload Streamlit uploads; returns DB paths like s3:products/12_1.png."""
    if not uploaded_files:
        return []
    out: list[str] = []
    n = len(uploaded_files)
    for i, u in enumerate(uploaded_files):
        name = getattr(u, "name", None) or "upload"
        _, ext = os.path.splitext(name)
        ext = ((ext or "").lower() if ext else ".bin") or ".bin"
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".bin"):
            ext = ".bin"
        if n == 1:
            fname = f"{product_id}{ext}"
        else:
            fname = f"{product_id}_{i + 1}{ext}"
        key = f"products/{fname}"
        data = u.getvalue()  # type: ignore[union-attr]
        ct = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }.get(ext, "application/octet-stream")
        put_bytes(key, bytes(data), ct)
        out.append(f"s3:{key}")
    return out


def put_vendor_bill_pdf(po_id: int, pdf_bytes: bytes) -> str:
    key = f"vendor_bills/{int(po_id)}.pdf"
    put_bytes(key, pdf_bytes, "application/pdf")
    return f"s3:{key}"


def put_customer_bill_pdf(customer_order_id: int, pdf_bytes: bytes) -> str:
    key = f"customer_bills/{int(customer_order_id)}.pdf"
    put_bytes(key, pdf_bytes, "application/pdf")
    return f"s3:{key}"
