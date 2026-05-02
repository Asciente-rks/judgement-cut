import os
from typing import Optional
import boto3
from botocore.client import Config
from ..core.config import R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY, R2_BUCKET


def _get_s3_client():
    # Cloudflare R2 is S3-compatible. Requires endpoint "https://{account_id}.r2.cloudflarestorage.com"
    account = os.getenv("R2_ACCOUNT_ID")
    access = os.getenv("R2_ACCESS_KEY")
    secret = os.getenv("R2_SECRET_KEY")
    endpoint = os.getenv("R2_ENDPOINT") or (f"https://{account}.r2.cloudflarestorage.com" if account else None)
    if not endpoint:
        raise RuntimeError("R2 endpoint not configured")

    s3 = boto3.client(
        "s3",
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        endpoint_url=endpoint,
        config=Config(signature_version="s3v4"),
    )
    return s3


def upload_file_to_r2(bucket: Optional[str], key: str, data: bytes) -> dict:
    bucket = bucket or os.getenv("R2_BUCKET")
    client = _get_s3_client()
    client.put_object(Bucket=bucket, Key=key, Body=data)
    # Return a presigned URL
    url = client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600)
    return {"url": url}


def delete_file_from_r2(bucket: Optional[str], key: str) -> bool:
    bucket = bucket or os.getenv("R2_BUCKET")
    client = _get_s3_client()
    client.delete_object(Bucket=bucket, Key=key)
    return True
