"""Cloudflare R2 storage helpers.

R2 is S3-compatible. We use boto3 with a custom endpoint so the same
client code works for upload, presign, and content lookup.
"""
import os
from typing import Optional, Tuple

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from ..core.config import R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY, R2_BUCKET


# Boto clients are not threadsafe across regions but reusing one per
# Lambda container is fine. Cache it at module scope so warm invocations
# skip the boto3 setup cost.
_S3_CLIENT = None


def _get_s3_client():
    global _S3_CLIENT
    if _S3_CLIENT is not None:
        return _S3_CLIENT

    account = os.getenv("R2_ACCOUNT_ID") or R2_ACCOUNT_ID
    access = os.getenv("R2_ACCESS_KEY") or R2_ACCESS_KEY
    secret = os.getenv("R2_SECRET_KEY") or R2_SECRET_KEY
    endpoint = os.getenv("R2_ENDPOINT") or (
        f"https://{account}.r2.cloudflarestorage.com" if account else None
    )
    if not endpoint:
        raise RuntimeError("R2 endpoint not configured")

    _S3_CLIENT = boto3.client(
        "s3",
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        endpoint_url=endpoint,
        config=Config(signature_version="s3v4"),
    )
    return _S3_CLIENT


def _resolve_bucket(bucket: Optional[str]) -> str:
    return bucket or os.getenv("R2_BUCKET") or R2_BUCKET or ""


def upload_file_to_r2(bucket: Optional[str], key: str, data: bytes,
                      content_type: Optional[str] = None) -> dict:
    """Upload bytes to R2 and return a 1-hour presigned GET URL."""
    bucket_name = _resolve_bucket(bucket)
    client = _get_s3_client()
    extra = {"ContentType": content_type} if content_type else {}
    client.put_object(Bucket=bucket_name, Key=key, Body=data, **extra)
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name, "Key": key},
        ExpiresIn=3600,
    )
    return {"url": url}


def delete_file_from_r2(bucket: Optional[str], key: str) -> bool:
    bucket_name = _resolve_bucket(bucket)
    client = _get_s3_client()
    client.delete_object(Bucket=bucket_name, Key=key)
    return True


def r2_object_exists(key: str, bucket: Optional[str] = None) -> bool:
    """Cheap HEAD check against R2 to see if an object is already cached."""
    bucket_name = _resolve_bucket(bucket)
    client = _get_s3_client()
    try:
        client.head_object(Bucket=bucket_name, Key=key)
        return True
    except ClientError as exc:
        # 404 means the key isn't there. Anything else (auth, network, etc.)
        # we treat as "not present" and let the caller decide whether to
        # try and re-upload.
        code = exc.response.get("Error", {}).get("Code") if exc.response else ""
        if code in ("NoSuchKey", "404", "NotFound"):
            return False
        return False


def r2_presigned_get(key: str, bucket: Optional[str] = None,
                     expires_in: int = 3600) -> str:
    bucket_name = _resolve_bucket(bucket)
    client = _get_s3_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name, "Key": key},
        ExpiresIn=expires_in,
    )


def r2_is_configured() -> bool:
    """Sanity check: do we have all four R2 env vars present?"""
    account = os.getenv("R2_ACCOUNT_ID") or R2_ACCOUNT_ID
    access = os.getenv("R2_ACCESS_KEY") or R2_ACCESS_KEY
    secret = os.getenv("R2_SECRET_KEY") or R2_SECRET_KEY
    bucket = _resolve_bucket(None)
    return bool(account and access and secret and bucket)
