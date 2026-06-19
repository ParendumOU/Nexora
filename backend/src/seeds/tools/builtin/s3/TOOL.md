# S3 / Object Storage

Read and write S3-compatible object storage via boto3.

## Configuration

**AWS S3:**
```
S3_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE
S3_SECRET_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
S3_BUCKET=my-bucket
```
`S3_ENDPOINT` is optional for AWS (defaults to AWS regional endpoint).

**MinIO / Cloudflare R2 / other S3-compatible:**
```
S3_ACCESS_KEY=your-access-key
S3_SECRET_KEY=your-secret-key
S3_ENDPOINT=https://s3.example.com
S3_BUCKET=my-bucket
```

`S3_BUCKET` sets the default bucket. Override per-call with `bucket` argument.

## Actions

### list_objects
List objects in a bucket (or folder prefix).
```json
{"action": "list_objects", "prefix": "data/2026/", "limit": 50}
```

### get_object
Read object content (text files only, max 512 KB).
```json
{"action": "get_object", "key": "reports/summary.txt"}
```

### put_object
Upload text or JSON content as an object.
```json
{"action": "put_object", "key": "output/result.json", "content": "{\"status\": \"ok\"}", "content_type": "application/json"}
```

### delete_object
Delete an object.
```json
{"action": "delete_object", "key": "tmp/old-file.txt"}
```

### presign_url
Generate a presigned download URL (default 1 hour expiry).
```json
{"action": "presign_url", "key": "reports/report.pdf", "expires_in": 3600}
```

### list_buckets
List all accessible buckets.
```json
{"action": "list_buckets"}
```
