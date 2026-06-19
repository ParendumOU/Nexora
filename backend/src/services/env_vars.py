"""Resolve tool credentials from org/user environment variables.

Resolution precedence for a given env KEY:
  1. an explicit selection (key -> variable name) if provided,
  2. an ORG-scoped variable with that key,
  3. a USER-scoped variable with that key,
  4. (caller falls back to the real OS environment).

Multiple stored variables may share a KEY (e.g. prod + test STRIPE_SECRET_KEY);
each has a unique `name`. Without a selection, the first org match (then user
match), ordered by name, wins — deterministic, and the install modal lets users
pick which named var maps to which tool.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select

from src.core.security import decrypt
from src.models.env_var import EnvVar

logger = logging.getLogger(__name__)

_SEEDS_ROOT = Path(__file__).parent.parent / "seeds"
_TOOL_ROOTS = [
    _SEEDS_ROOT / "tools" / "builtin",
    _SEEDS_ROOT / "tools" / "custom",
    _SEEDS_ROOT / "skills" / "builtin",
    _SEEDS_ROOT / "skills" / "custom",
]


_KEYS_CACHE: dict[str, list[str]] = {}


def tool_env_keys(key: str) -> list[str]:
    """Declared env_vars for a tool/skill key (from its tool.json/skill.json).
    Cached per key — call reload_env_keys() after a marketplace import adds seeds."""
    if key in _KEYS_CACHE:
        return _KEYS_CACHE[key]
    result: list[str] = []
    for root in _TOOL_ROOTS:
        d = root / key
        for manifest in ("tool.json", "skill.json"):
            mf = d / manifest
            if mf.exists():
                try:
                    data = json.loads(mf.read_text(encoding="utf-8"))
                    result = [str(x) for x in (data.get("env_vars") or []) if x]
                except Exception:  # noqa: BLE001
                    result = []
                break
        if result:
            break
    _KEYS_CACHE[key] = result
    return result


def reload_env_keys() -> None:
    """Drop the env_vars cache (after importing/removing a custom seed)."""
    _KEYS_CACHE.clear()


async def resolve(db, keys, org_id=None, user_id=None, selections=None) -> dict[str, str]:
    """Return {KEY: decrypted_value} for the subset of `keys` configured at the
    org or user scope. `selections` optionally maps KEY -> stored variable name."""
    keys = [k for k in (keys or []) if k]
    if not keys:
        return {}
    selections = selections or {}

    conds = []
    if org_id:
        conds.append((EnvVar.scope == "org") & (EnvVar.org_id == org_id))
    if user_id:
        conds.append((EnvVar.scope == "user") & (EnvVar.user_id == user_id))
    if not conds:
        return {}
    cond = conds[0]
    for c in conds[1:]:
        cond = cond | c

    rows = (await db.execute(
        select(EnvVar).where(EnvVar.key.in_(keys), cond)
    )).scalars().all()
    if not rows:
        return {}

    # Index: key -> {"org": {name: row}, "user": {name: row}}
    by_key: dict[str, dict[str, dict[str, EnvVar]]] = {}
    for r in rows:
        by_key.setdefault(r.key, {"org": {}, "user": {}})[r.scope][r.name] = r

    out: dict[str, str] = {}
    for k in keys:
        scoped = by_key.get(k)
        if not scoped:
            continue
        chosen: EnvVar | None = None
        want_name = selections.get(k)
        if want_name:
            chosen = scoped["org"].get(want_name) or scoped["user"].get(want_name)
        if chosen is None:
            for scope in ("org", "user"):
                names = sorted(scoped[scope])
                if names:
                    chosen = scoped[scope][names[0]]
                    break
        if chosen is None:
            continue
        try:
            out[k] = decrypt(chosen.value_enc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[env_vars] failed to decrypt %s/%s: %s", chosen.scope, chosen.name, exc)
    return out


async def resolve_for_tool(db, tool_key, org_id=None, user_id=None, selections=None) -> dict[str, str]:
    """Resolve env values for a single tool's declared env_vars."""
    keys = tool_env_keys(tool_key)
    if not keys:
        return {}
    return await resolve(db, keys, org_id=org_id, user_id=user_id, selections=selections)


async def _org_user_for_chat(db, chat_id, agent_id):
    """Best-effort (org_id, user_id) for a tool call. Org: agent.org_id, else
    chat→project.org_id, else the chat owner's first membership. User: chat.user_id."""
    from src.models.agent import Agent
    from src.models.chat import Chat
    from src.models.project import Project
    from src.models.org import OrgMember

    org_id = None
    user_id = None
    if agent_id:
        ag = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
        if ag:
            org_id = ag.org_id
    chat = None
    if chat_id:
        chat = (await db.execute(select(Chat).where(Chat.id == chat_id))).scalar_one_or_none()
    if chat:
        user_id = getattr(chat, "user_id", None)
        if not org_id and getattr(chat, "project_id", None):
            pr = (await db.execute(select(Project).where(Project.id == chat.project_id))).scalar_one_or_none()
            if pr:
                org_id = pr.org_id
        if not org_id and user_id:
            om = (await db.execute(
                select(OrgMember).where(OrgMember.user_id == user_id))).scalars().first()
            if om:
                org_id = om.org_id
    return org_id, user_id


async def resolve_for_chat(tool_key, chat_id, agent_id) -> dict[str, str]:
    """Resolve a tool's declared env_vars to {KEY: value} using the org/user the
    chat belongs to. Opens its own DB session; never raises (returns {} on error)."""
    keys = tool_env_keys(tool_key)
    if not keys:
        return {}
    try:
        from src.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            org_id, user_id = await _org_user_for_chat(db, chat_id, agent_id)
            if not org_id and not user_id:
                return {}
            return await resolve(db, keys, org_id=org_id, user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[env_vars] resolve_for_chat failed for %s: %s", tool_key, exc)
        return {}
