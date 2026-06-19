"""Organization deletion with per-category wipe / reassign.

When an owner deletes an org they choose, per resource category, whether to
**wipe** it (delete the rows) or **keep** it (reassign the rows to a target org —
by default the owner's personal org). Anything not explicitly wiped is moved, so
nothing is lost silently.

Projects are always *reassigned* (moved) to the target org — they are never wiped
through this flow (delete them from the projects UI first if that's the intent).

FK safety: org-scoped rows mostly carry an ``org_id`` column, so reassign is a
bulk ``UPDATE ... SET org_id`` and wipe is a bulk ``DELETE``. The few child tables
without an ``org_id`` (chats and their messages/notes/participants/files, plan and
task steps, agent logs/messages, provider-chain items, issue comments) follow their
parent on reassign and are deleted children-first on wipe. Because wiping a parent
would orphan a kept child that references it, the wipe set is expanded:
``agents`` or ``providers`` ⇒ also wipe ``activity``; ``activity`` ⇒ also wipe
``issues`` (chats/tasks/issues reference agents+providers).
"""
from __future__ import annotations

import logging

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Category -> human label + the org_id-bearing tables it owns. Order within a
# list does not matter for reassign; wipe uses the explicit ordered plan below.
CATEGORIES: dict[str, dict] = {
    "agents":       {"label": "Agents",        "tables": ["agents", "agent_memories"]},
    "activity":     {"label": "Chats & tasks", "tables": ["tasks", "plans", "agent_proposals"]},
    "knowledge":    {"label": "Knowledge bases", "tables": ["knowledge_bases", "knowledge_files", "knowledge_chunks"]},
    "memory":       {"label": "Memory notes",  "tables": ["memory_notes", "memory_links"]},
    "catalog":      {"label": "Personas, skills, tools, MCP", "tables": ["personas", "skills", "tools", "mcp_servers"]},
    "providers":    {"label": "Providers",     "tables": ["providers", "provider_chains"]},
    "integrations": {"label": "Integrations & automation", "tables": ["integrations", "git_credentials", "webhook_rules", "schedules", "model_profiles", "environment_variables"]},
    "issues":       {"label": "Issues",        "tables": ["issues"]},
}

# Always reassigned, never wiped via this flow.
PROJECT_TABLES = ["projects", "project_memories"]

# A simple count query per category for the deletion-summary form.
_COUNT_TABLE = {
    "agents": "agents",
    "activity": "chats",   # chats has no org_id — counted separately below
    "knowledge": "knowledge_bases",
    "memory": "memory_notes",
    "catalog": "personas",
    "providers": "providers",
    "integrations": "integrations",
    "issues": "issues",
}

VALID_CATEGORIES = set(CATEGORIES)


def expand_wipe(wipe: set[str]) -> set[str]:
    """Grow the wipe set so a kept row never references a wiped one."""
    out = {c for c in wipe if c in VALID_CATEGORIES}
    changed = True
    while changed:
        changed = False
        if (("agents" in out) or ("providers" in out)) and "activity" not in out:
            out.add("activity"); changed = True
        if "activity" in out and "issues" not in out:
            out.add("issues"); changed = True
    return out


async def _ids(db: AsyncSession, sql: str, params: dict) -> list[str]:
    rows = (await db.execute(text(sql), params)).fetchall()
    return [r[0] for r in rows]


async def summarize_org(db: AsyncSession, org_id: str) -> dict:
    """Per-category row counts for the deletion form."""
    out: dict[str, dict] = {}
    for key, meta in CATEGORIES.items():
        table = _COUNT_TABLE[key]
        if key == "activity":
            # chats are linked via agent/provider/project, not org_id.
            count = (await db.execute(text(
                "SELECT count(*) FROM chats WHERE "
                "agent_id IN (SELECT id FROM agents WHERE org_id=:o) "
                "OR provider_chain_id IN (SELECT id FROM provider_chains WHERE org_id=:o) "
                "OR direct_provider_id IN (SELECT id FROM providers WHERE org_id=:o) "
                "OR project_id IN (SELECT id FROM projects WHERE org_id=:o)"
            ), {"o": org_id})).scalar() or 0
        else:
            count = (await db.execute(text(
                f"SELECT count(*) FROM {table} WHERE org_id=:o"
            ), {"o": org_id})).scalar() or 0
        out[key] = {"label": meta["label"], "count": int(count)}
    projects = (await db.execute(text(
        "SELECT count(*) FROM projects WHERE org_id=:o"
    ), {"o": org_id})).scalar() or 0
    return {"categories": out, "projects": int(projects)}


async def teardown_org(
    db: AsyncSession,
    org_id: str,
    wipe: set[str],
    target_org_id: str,
) -> dict:
    """Wipe the selected categories and reassign the rest to ``target_org_id``.

    Does NOT commit — the caller controls the transaction. Returns a small report.
    """
    wipe = expand_wipe(wipe)
    keep = VALID_CATEGORIES - wipe
    p = {"o": org_id, "t": target_org_id}

    # ── Snapshot id sets BEFORE any mutation (reassign would move them out) ──────
    agent_ids = await _ids(db, "SELECT id FROM agents WHERE org_id=:o", p)
    chain_ids = await _ids(db, "SELECT id FROM provider_chains WHERE org_id=:o", p)
    provider_ids = await _ids(db, "SELECT id FROM providers WHERE org_id=:o", p)
    project_ids = await _ids(db, "SELECT id FROM projects WHERE org_id=:o", p)
    chat_ids = await _ids(db,
        "SELECT id FROM chats WHERE agent_id IN (SELECT id FROM agents WHERE org_id=:o) "
        "OR provider_chain_id IN (SELECT id FROM provider_chains WHERE org_id=:o) "
        "OR direct_provider_id IN (SELECT id FROM providers WHERE org_id=:o) "
        "OR project_id IN (SELECT id FROM projects WHERE org_id=:o)", p)
    task_ids = await _ids(db,
        "SELECT id FROM tasks WHERE org_id=:o "
        "OR chat_id IN (SELECT id FROM chats WHERE agent_id IN (SELECT id FROM agents WHERE org_id=:o) "
        "OR provider_chain_id IN (SELECT id FROM provider_chains WHERE org_id=:o) "
        "OR direct_provider_id IN (SELECT id FROM providers WHERE org_id=:o))", p)
    plan_ids = await _ids(db,
        "SELECT id FROM plans WHERE org_id=:o "
        "OR chat_id IN (SELECT id FROM chats WHERE agent_id IN (SELECT id FROM agents WHERE org_id=:o) "
        "OR provider_chain_id IN (SELECT id FROM provider_chains WHERE org_id=:o) "
        "OR direct_provider_id IN (SELECT id FROM providers WHERE org_id=:o))", p)
    issue_ids = await _ids(db, "SELECT id FROM issues WHERE org_id=:o", p)

    async def _del_in(table: str, col: str, ids: list[str]) -> None:
        if not ids:
            return
        stmt = text(f"DELETE FROM {table} WHERE {col} IN :ids").bindparams(
            bindparam("ids", expanding=True)
        )
        await db.execute(stmt, {"ids": ids})

    async def _del_org(table: str) -> None:
        await db.execute(text(f"DELETE FROM {table} WHERE org_id=:o"), p)

    # ── WIPE (children first; only for categories in the expanded set) ──────────
    if "activity" in wipe:
        await _del_in("task_steps", "task_id", task_ids)
        await _del_in("plan_steps", "plan_id", plan_ids)
        await _del_in("plans", "id", plan_ids)
        await _del_in("agent_messages", "chat_id", chat_ids)
        await _del_in("agent_logs", "chat_id", chat_ids)
    if "issues" in wipe:
        await _del_in("issue_comments", "issue_id", issue_ids)
        await _del_org("issues")
    if "activity" in wipe:
        # tasks reference messages (parent_message_id) + chats → delete before them
        await _del_in("tasks", "id", task_ids)
        await _del_in("messages", "chat_id", chat_ids)
        await _del_in("chat_participants", "chat_id", chat_ids)
        await _del_in("chat_notes", "chat_id", chat_ids)
        await _del_in("chat_files", "chat_id", chat_ids)
        await _del_org("agent_proposals")
        await _del_in("chats", "id", chat_ids)
    if "agents" in wipe:
        await _del_in("agent_versions", "agent_id", agent_ids)
        await _del_org("agent_memories")
    if "memory" in wipe:
        await _del_org("memory_links")
        await _del_org("memory_notes")
    if "knowledge" in wipe:
        await _del_org("knowledge_chunks")
        await _del_org("knowledge_files")
        await _del_org("knowledge_bases")
    if "catalog" in wipe:
        for t in ("personas", "skills", "tools", "mcp_servers"):
            await _del_org(t)
    if "integrations" in wipe:
        for t in ("integrations", "git_credentials", "webhook_rules", "schedules", "model_profiles", "environment_variables"):
            await _del_org(t)
    if "providers" in wipe:
        await _del_in("provider_chain_items", "chain_id", chain_ids)
        await _del_org("providers")
        await _del_org("provider_chains")
    if "agents" in wipe:
        await _del_in("agents", "id", agent_ids)  # last — chats/tasks/issues gone

    # ── REASSIGN kept categories + projects to the target org ───────────────────
    reassign_tables: list[str] = list(PROJECT_TABLES)
    for cat in keep:
        reassign_tables.extend(CATEGORIES[cat]["tables"])
    for table in reassign_tables:
        await db.execute(text(f"UPDATE {table} SET org_id=:t WHERE org_id=:o"), p)

    # Members of the deleted org fall back to their personal org on next login.
    await db.execute(text("UPDATE users SET active_org_id=NULL WHERE active_org_id=:o"), p)
    await db.execute(text("DELETE FROM org_members WHERE org_id=:o"), p)

    logger.info("Org %s torn down: wiped=%s reassigned=%s -> %s",
                org_id, sorted(wipe), sorted(keep), target_org_id)
    return {"wiped": sorted(wipe), "reassigned": sorted(keep | {"projects"}), "target_org_id": target_org_id}
