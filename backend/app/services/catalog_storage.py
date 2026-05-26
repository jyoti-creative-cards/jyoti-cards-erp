"""Upload / delete catalog images on Supabase S3-compatible storage."""

from __future__ import annotations

from typing import Optional

import boto3
from botocore.config import Config

from app.config import get_settings

_PREFIX = "product_images"


def safe_catalog_stem(our_product_id: str) -> str:
    """S3-safe file stem from your product id (for product_images/{stem}.png)."""
    s = (our_product_id or "").strip()
    out: list[str] = []
    for c in s:
        if c.isalnum() or c in "-_":
            out.append(c)
        elif c in " .":
            out.append("_")
        else:
            out.append("_")
    stem = "".join(out).strip("_")[:200]
    return stem or "product"


def _s3():
    s = get_settings()
    if not (s.s3_endpoint_url and s.s3_bucket and s.s3_access_key_id and s.s3_secret_access_key):
        return None
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url.strip(),
        aws_access_key_id=s.s3_access_key_id.strip(),
        aws_secret_access_key=s.s3_secret_access_key.strip(),
        region_name=(s.s3_region or "us-east-1").strip(),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def storage_configured() -> bool:
    return _s3() is not None


def next_image_key(stem: str, existing_keys: list[str]) -> str:
    """
    First image: product_images/{stem}.png
    More: product_images/{stem}_1.png, {stem}_2.png, ...
    """
    names = [k.rsplit("/", 1)[-1] for k in existing_keys]
    pid = stem
    has_primary = any(n.startswith(f"{pid}.") for n in names)
    if not has_primary:
        return f"{_PREFIX}/{pid}.png"

    suffixes: list[int] = []
    for n in names:
        fn_stem = n.rsplit(".", 1)[0]
        if fn_stem == pid:
            continue
        if fn_stem.startswith(f"{pid}_"):
            rest = fn_stem[len(pid) + 1 :]
            if rest.isdigit():
                suffixes.append(int(rest))
    nxt = max(suffixes + [0]) + 1
    return f"{_PREFIX}/{pid}_{nxt}.png"


def upload_bytes(key: str, data: bytes, content_type: str) -> None:
    cli = _s3()
    if cli is None:
        raise RuntimeError("S3 not configured")
    s = get_settings()
    cli.put_object(
        Bucket=s.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type or "application/octet-stream",
    )


def delete_keys(keys: list[str]) -> None:
    if not keys:
        return
    cli = _s3()
    if cli is None:
        return
    s = get_settings()
    for key in keys:
        try:
            cli.delete_object(Bucket=s.s3_bucket, Key=key)
        except Exception:
            pass


def presigned_url(key: str, expires: int = 3600) -> Optional[str]:
    cli = _s3()
    if cli is None:
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
    """One URL per key (empty string if presign failed). Keeps length aligned with image_keys."""
    return [presigned_url(k) or "" for k in keys]
