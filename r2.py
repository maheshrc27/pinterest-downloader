"""Cloudflare R2, via its S3-compatible API.

Object keys MUST match `assets/<ownerId>/<ref>` exactly — that is the same
convention lib/server/r2.ts uses on the Next.js side (see `assetKey` there),
and the app's own `/api/assets` route resolves a stored photo by rebuilding
that exact path from the caller's own verified user id. Write anywhere else
and the app will never be able to read it back.
"""

import uuid

import boto3
from botocore.config import Config

import config

_client = None


def client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=f"https://{config.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=config.R2_ACCESS_KEY_ID,
            aws_secret_access_key=config.R2_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
    return _client


def upload_asset(owner_id: str, body: bytes, content_type: str) -> str:
    """Uploads one photo, returning its `r2:<ref>` pointer — the same shape a
    deck's own photos and a scheduled TikTok post's assetRefs already use."""
    ref = uuid.uuid4().hex
    key = f"assets/{owner_id}/{ref}"
    client().put_object(Bucket=config.R2_BUCKET_NAME, Key=key, Body=body, ContentType=content_type)
    return f"r2:{ref}"
