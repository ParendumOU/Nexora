# Docker Build

Build Docker image from Dockerfile.

## Parameters
- `context` (string, required): build context path
- `dockerfile` (string, optional): path to Dockerfile (default: `Dockerfile` in context)
- `tag` (string, optional): image tag (e.g. `myapp:latest`)
- `build_args` (object, optional): build arguments
- `target` (string, optional): multi-stage build target

## Returns
```json
{ "image_id": "sha256:abc...", "tag": "myapp:latest", "build_time_seconds": 42 }
```
