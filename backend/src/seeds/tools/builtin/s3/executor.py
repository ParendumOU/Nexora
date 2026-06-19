"""S3 / object storage tool — boto3, S3-compatible endpoints."""
from __future__ import annotations
import asyncio
import os
import logging
from src.core.pubsub import broadcast as _broadcast

logger = logging.getLogger(__name__)

_MAX_READ_BYTES = 512 * 1024  # 512 KB


def _client(bucket_override: str | None = None):
    """Return (boto3_client, bucket_name) or raise ValueError."""
    import boto3
    access_key = os.environ.get("S3_ACCESS_KEY", "").strip()
    secret_key = os.environ.get("S3_SECRET_KEY", "").strip()
    endpoint = os.environ.get("S3_ENDPOINT", "").strip() or None
    bucket = bucket_override or os.environ.get("S3_BUCKET", "").strip()

    if not access_key or not secret_key:
        raise ValueError("S3_ACCESS_KEY and S3_SECRET_KEY must be configured.")

    kw: dict = {
        "aws_access_key_id": access_key,
        "aws_secret_access_key": secret_key,
    }
    if endpoint:
        kw["endpoint_url"] = endpoint
    region = os.environ.get("AWS_REGION") or os.environ.get("S3_REGION")
    if region:
        kw["region_name"] = region

    client = boto3.client("s3", **kw)
    return client, bucket


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict:
    action = (args.get("action") or "").strip()
    if not action:
        return {"error": "action is required. Use: list_objects, get_object, put_object, delete_object, presign_url, list_buckets."}

    try:
        client, default_bucket = await asyncio.to_thread(_client, args.get("bucket"))
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Failed to initialise S3 client: {e}"}

    bucket = args.get("bucket") or default_bucket

    await _broadcast(chat_id, {
        "type": "activity_status", "status": "running",
        "tool": "s3", "label": f"S3: {action}",
    })

    def _run(fn, *a, **kw):
        return asyncio.to_thread(fn, *a, **kw)

    if action == "list_objects":
        if not bucket:
            return {"error": "bucket is required (set S3_BUCKET or pass bucket argument)"}
        prefix = args.get("prefix", "")
        limit = min(int(args.get("limit") or 50), 1000)
        try:
            resp = await _run(client.list_objects_v2, Bucket=bucket, Prefix=prefix, MaxKeys=limit)
        except Exception as e:
            return {"error": str(e)}
        objects = [
            {"key": o["Key"], "size": o["Size"],
             "last_modified": o["LastModified"].isoformat()}
            for o in resp.get("Contents", [])
        ]
        return {"data": {"objects": objects, "count": len(objects),
                         "truncated": resp.get("IsTruncated", False)}}

    elif action == "get_object":
        key = args.get("key", "")
        if not bucket or not key:
            return {"error": "bucket (or S3_BUCKET) and key are required for get_object"}
        try:
            resp = await _run(client.get_object, Bucket=bucket, Key=key)
            content_length = resp.get("ContentLength", 0)
            if content_length > _MAX_READ_BYTES:
                return {"error": f"Object too large to read ({content_length // 1024} KB). Max {_MAX_READ_BYTES // 1024} KB."}
            body_bytes = await _run(resp["Body"].read)
        except Exception as e:
            return {"error": str(e)}
        try:
            content = body_bytes.decode("utf-8", errors="replace")
        except Exception:
            return {"error": "Object is binary and cannot be returned as text."}
        return {"data": {"key": key, "content": content,
                         "content_type": resp.get("ContentType"),
                         "size": content_length}}

    elif action == "put_object":
        key = args.get("key", "")
        content = args.get("content", "")
        if not bucket or not key:
            return {"error": "bucket (or S3_BUCKET) and key are required for put_object"}
        if content is None or content == "":
            return {"error": "content is required for put_object"}
        content_type = args.get("content_type", "text/plain")
        body = content.encode("utf-8") if isinstance(content, str) else str(content).encode()
        try:
            await _run(client.put_object, Bucket=bucket, Key=key, Body=body,
                       ContentType=content_type)
        except Exception as e:
            return {"error": str(e)}
        return {"data": {"key": key, "bucket": bucket, "size": len(body)}}

    elif action == "delete_object":
        key = args.get("key", "")
        if not bucket or not key:
            return {"error": "bucket (or S3_BUCKET) and key are required for delete_object"}
        try:
            await _run(client.delete_object, Bucket=bucket, Key=key)
        except Exception as e:
            return {"error": str(e)}
        return {"data": {"key": key, "bucket": bucket, "deleted": True}}

    elif action == "presign_url":
        key = args.get("key", "")
        if not bucket or not key:
            return {"error": "bucket (or S3_BUCKET) and key are required for presign_url"}
        expires_in = min(int(args.get("expires_in") or 3600), 604800)  # max 7 days
        try:
            url = await _run(client.generate_presigned_url,
                             "get_object",
                             Params={"Bucket": bucket, "Key": key},
                             ExpiresIn=expires_in)
        except Exception as e:
            return {"error": str(e)}
        return {"data": {"url": url, "key": key, "expires_in": expires_in}}

    elif action == "list_buckets":
        try:
            resp = await _run(client.list_buckets)
        except Exception as e:
            return {"error": str(e)}
        buckets = [{"name": b["Name"], "created": b["CreationDate"].isoformat()}
                   for b in resp.get("Buckets", [])]
        return {"data": {"buckets": buckets, "count": len(buckets)}}

    else:
        return {"error": f"Unknown action '{action}'. Use: list_objects, get_object, put_object, delete_object, presign_url, list_buckets."}
