from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/system", tags=["system"])


def _read_version() -> str:
    p = Path(__file__).parent.parent.parent.parent.parent / "VERSION"
    if p.exists():
        return p.read_text().strip()
    return "unknown"


NEXORA_VERSION: str = _read_version()


@router.get("/version")
async def get_version():
    """Public — returns this instance's running version."""
    return {"version": NEXORA_VERSION, "product": "nexora"}
