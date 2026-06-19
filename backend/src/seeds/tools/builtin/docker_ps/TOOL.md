# Docker PS

List running Docker containers.

## Parameters
- `all` (boolean, optional): show all containers including stopped (default: false)
- `filter` (string, optional): filter expression (e.g. `name=backend`)

## Returns
```json
[
  {
    "id": "abc123def456",
    "name": "backend",
    "image": "nexora-backend:latest",
    "status": "Up 2 hours",
    "ports": "0.0.0.0:8000->8000/tcp"
  }
]
```
