"""Structured audit log (#178) + custom-webhook signature verification (#182)."""
import hashlib
import hmac

import pytest
from sqlalchemy import select

from src.models.user import User
from src.models.audit_log import AuditLog
from src.services.audit import record_audit


# ── #178 audit log ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_audit_persists_row(db):
    await record_audit(db, action="test.action", org_id="org-x",
                       resource_type="thing", resource_id="r1", detail={"k": "v"})
    await db.commit()
    rows = (await db.execute(
        select(AuditLog).where(AuditLog.action == "test.action")
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].org_id == "org-x"
    assert rows[0].resource_id == "r1"
    assert rows[0].detail == {"k": "v"}


@pytest.mark.asyncio
async def test_record_audit_never_raises_on_bad_input(db):
    # A non-serializable detail or odd value must not bubble up to the caller.
    await record_audit(db, action="x", org_id=None, resource_id=12345)
    await db.commit()


@pytest.mark.asyncio
async def test_audit_endpoint_scopes_non_superuser_to_active_org(client, auth_headers, db):
    u = (await db.execute(
        select(User).where(User.email == "fixture@example.com")
    )).scalar_one()
    my_org = u.active_org_id
    await record_audit(db, action="org.member.add", org_id=my_org,
                       resource_type="org_member", resource_id="mine")
    await record_audit(db, action="org.member.add", org_id="other-org",
                       resource_type="org_member", resource_id="theirs")
    await db.commit()

    resp = await client.get("/api/audit", headers=auth_headers)
    assert resp.status_code == 200
    orgs = {i["org_id"] for i in resp.json()["items"]}
    assert my_org in orgs
    assert "other-org" not in orgs  # owner of own org cannot see other orgs' trail


@pytest.mark.asyncio
async def test_audit_endpoint_superuser_sees_other_orgs(client, auth_headers, db):
    u = (await db.execute(
        select(User).where(User.email == "fixture@example.com")
    )).scalar_one()
    u.is_superuser = True
    await record_audit(db, action="platform.export", org_id="other-org",
                       resource_type="backup_job", resource_id="job1")
    await db.commit()

    resp = await client.get("/api/audit?org_id=other-org", headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert any(i["org_id"] == "other-org" for i in items)


# ── #182 webhook signature ───────────────────────────────────────────────────


def test_verify_signature_accepts_valid_hmac():
    from src.api.routers.custom_webhook import _verify_signature
    body = b'{"event_type":"alert"}'
    secret = "s3cr3t"
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert _verify_signature(body, secret, sig) is True
    # bare hex (no prefix) also accepted
    assert _verify_signature(body, secret, sig.split("=", 1)[1]) is True


def test_verify_signature_rejects_tampered_body():
    from src.api.routers.custom_webhook import _verify_signature
    secret = "s3cr3t"
    sig = "sha256=" + hmac.new(secret.encode(), b"original", hashlib.sha256).hexdigest()
    assert _verify_signature(b"tampered", secret, sig) is False
