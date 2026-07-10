"""Supabase S3-compatible storage for JCC/catalog/{vendor_folder}/"""

from __future__ import annotations

import re
from typing import Optional

import boto3
from botocore.config import Config

from app.config import get_settings

_ROOT = "JCC"
_CATALOG_ROOT = "JCC/catalog"


def customer_folder_slug(business_name: str) -> str:
    return vendor_folder_slug(business_name)


def customer_order_key(customer_slug: str, placement_id: int) -> str:
    return f"{_ROOT}/customer/{customer_slug}/orders/order_{placement_id}.pdf"


def customer_bill_key(customer_slug: str, bill_number: str) -> str:
    safe = re.sub(r"[^\w-]", "_", (bill_number or "bill").strip())[:80]
    return f"{_ROOT}/customer/{customer_slug}/bills/{safe}.pdf"


def vendor_order_key(vendor_folder: str, placement_id: int) -> str:
    return f"{_ROOT}/vendor/{vendor_folder}/orders/placement_{placement_id}.pdf"


def vendor_receipt_key(vendor_folder: str, bill_number: str, receipt_id: int | None = None) -> str:
    safe = re.sub(r"[^\w-]", "_", (bill_number or "receipt").strip())[:80]
    suffix = f"_{receipt_id}" if receipt_id else ""
    return f"{_ROOT}/vendor/{vendor_folder}/receipts/{safe}{suffix}.pdf"


def documents_root() -> str:
    return f"{_ROOT}/documents/"


def vendor_folder_slug(business_name: str) -> str:
    s = (business_name or "").strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "_", s).strip("_")
    return (s[:100] or "vendor")


def bill_key(vendor_folder: str, bill_number: str, ext: str = "pdf") -> str:
    safe = re.sub(r"[^\w-]", "_", (bill_number or "bill").strip())[:80]
    return f"JCC/vendor/{vendor_folder}/bills/{safe}.{ext.lstrip('.')}"


def payment_receipt_key(vendor_folder: str, payment_ref: str, ext: str = "pdf") -> str:
    safe = re.sub(r"[^\w-]", "_", (payment_ref or "payment").strip())[:80]
    return f"JCC/vendor/{vendor_folder}/payments/{safe}.{ext.lstrip('.')}"


def image_key(vendor_folder: str, our_product_id: str, index: int, ext: str = "jpg") -> str:
    safe_id = re.sub(r"[^\w-]", "_", our_product_id.strip())[:120]
    return f"{_CATALOG_ROOT}/{vendor_folder}/{safe_id}_{index}.{ext.lstrip('.')}"


def _client():
    s = get_settings()
    if not (s.s3_endpoint_url and s.s3_bucket and s.s3_access_key_id and s.s3_secret_access_key):
        return None
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url.strip(),
        aws_access_key_id=s.s3_access_key_id.strip(),
        aws_secret_access_key=s.s3_secret_access_key.strip(),
        region_name=(s.s3_region or "ap-southeast-1").strip(),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def storage_configured() -> bool:
    return _client() is not None


def upload_bytes(key: str, data: bytes, content_type: str) -> None:
    cli = _client()
    if cli is None:
        raise RuntimeError("S3 not configured")
    s = get_settings()
    cli.put_object(Bucket=s.s3_bucket, Key=key, Body=data, ContentType=content_type or "application/octet-stream")


def delete_keys(keys: list[str]) -> None:
    cli = _client()
    if cli is None or not keys:
        return
    s = get_settings()
    for key in keys:
        try:
            cli.delete_object(Bucket=s.s3_bucket, Key=key)
        except Exception:
            pass


def presigned_url(key: str, expires: int = 3600) -> Optional[str]:
    cli = _client()
    if cli is None or not key:
        return None
    s = get_settings()
    try:
        return cli.generate_presigned_url(
            "get_object",
            Params={"Bucket": s.s3_bucket, "Key": key},
            ExpiresIn=expires,
        )
    except Exception:
        return None


def presigned_urls(keys: list[str]) -> list[str]:
    return [presigned_url(k) or "" for k in keys]


def rename_vendor_folder(old_slug: str, new_slug: str) -> int:
    """Copy all objects from old vendor folder to new, delete old. Returns count moved."""
    if old_slug == new_slug:
        return 0
    cli = _client()
    if cli is None:
        return 0
    s = get_settings()
    old_prefix = f"{_CATALOG_ROOT}/{old_slug}/"
    new_prefix = f"{_CATALOG_ROOT}/{new_slug}/"
    moved = 0
    paginator = cli.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=s.s3_bucket, Prefix=old_prefix):
        for obj in page.get("Contents", []):
            old_key = obj["Key"]
            new_key = old_key.replace(old_prefix, new_prefix, 1)
            cli.copy_object(
                Bucket=s.s3_bucket,
                CopySource={"Bucket": s.s3_bucket, "Key": old_key},
                Key=new_key,
            )
            cli.delete_object(Bucket=s.s3_bucket, Key=old_key)
            moved += 1
    return moved


def update_image_keys_after_vendor_rename(keys: list[str], old_slug: str, new_slug: str) -> list[str]:
    old_part = f"{_CATALOG_ROOT}/{old_slug}/"
    new_part = f"{_CATALOG_ROOT}/{new_slug}/"
    return [k.replace(old_part, new_part, 1) if k.startswith(old_part) else k for k in keys]


def list_objects(prefix: str, delimiter: str = "/") -> dict:
    cli = _client()
    if cli is None:
        return {"prefixes": [], "objects": []}
    s = get_settings()
    prefixes: list[str] = []
    objects: list[dict] = []
    paginator = cli.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=s.s3_bucket, Prefix=prefix, Delimiter=delimiter):
        for p in page.get("CommonPrefixes", []):
            prefixes.append(p.get("Prefix", ""))
        for obj in page.get("Contents", []):
            key = obj.get("Key", "")
            if key == prefix or key.endswith("/"):
                continue
            objects.append(
                {
                    "key": key,
                    "size": int(obj.get("Size") or 0),
                    "last_modified": obj.get("LastModified").isoformat() if obj.get("LastModified") else None,
                }
            )
    return {"prefixes": prefixes, "objects": objects}


def copy_object(src_key: str, dest_key: str) -> None:
    cli = _client()
    if cli is None:
        raise RuntimeError("S3 not configured")
    s = get_settings()
    cli.copy_object(Bucket=s.s3_bucket, CopySource={"Bucket": s.s3_bucket, "Key": src_key}, Key=dest_key)


def move_object(src_key: str, dest_key: str) -> None:
    copy_object(src_key, dest_key)
    cli = _client()
    if cli is None:
        return
    s = get_settings()
    cli.delete_object(Bucket=s.s3_bucket, Key=src_key)


def delete_key(key: str) -> None:
    cli = _client()
    if cli is None or not key:
        return
    s = get_settings()
    cli.delete_object(Bucket=s.s3_bucket, Key=key)


def create_folder(prefix: str) -> str:
    cli = _client()
    if cli is None:
        raise RuntimeError("S3 not configured")
    s = get_settings()
    folder = prefix if prefix.endswith("/") else f"{prefix}/"
    cli.put_object(Bucket=s.s3_bucket, Key=folder, Body=b"")
    return folder
