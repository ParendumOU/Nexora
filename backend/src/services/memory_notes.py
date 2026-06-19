"""Memory-note service — upsert markdown notes, parse references, embed.

Source of truth for the agent "memory vault". Parses ``[[wikilinks]]`` and
``#hashtags`` out of the markdown body into MemoryLink edges + a tag list, which
the web 3D reference graph renders. Folders are virtual (derived from ``path``).
"""
from __future__ import annotations
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, delete, func
from src.core.database import AsyncSessionLocal
from src.models.memory_note import MemoryNote, MemoryLink
from src.services import embeddings

logger = logging.getLogger(__name__)

# [[Target]] or [[Target|alias]] — capture the target before any pipe.
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
# #tag — not preceded by a word char or another '#' (so markdown headings "# H" / "## H" are ignored).
_HASHTAG_RE = re.compile(r"(?:^|[^\w#])#([a-zA-Z][\w/-]*)")


def _utcnow():
    return datetime.now(timezone.utc)


def parse_references(body_md: str) -> tuple[list[str], list[str]]:
    """Return (wikilink_targets, hashtags) found in the markdown body, de-duped, order-preserving."""
    seen_links: dict[str, None] = {}
    for m in _WIKILINK_RE.finditer(body_md or ""):
        t = m.group(1).strip()
        if t:
            seen_links.setdefault(t, None)
    seen_tags: dict[str, None] = {}
    for m in _HASHTAG_RE.finditer(body_md or ""):
        t = m.group(1).strip().lower()
        if t:
            seen_tags.setdefault(t, None)
    return list(seen_links.keys()), list(seen_tags.keys())


def normalize_path(path: str, title: str) -> str:
    """Clean a virtual path; default to '<title>.md', ensure .md suffix, strip leading slashes."""
    p = (path or "").strip().strip("/")
    if not p:
        slug = re.sub(r"[^a-zA-Z0-9 _-]", "", title or "note").strip().replace(" ", "-").lower() or "note"
        p = f"{slug}.md"
    if not p.lower().endswith(".md"):
        p = f"{p}.md"
    return p


async def _resolve_wikilink(db, org_id: str, target: str, exclude_id: str | None) -> str | None:
    """Resolve a [[target]] to a note id in the same org by path or title (case-insensitive)."""
    target = target.strip()
    target_md = target if target.lower().endswith(".md") else f"{target}.md"
    q = select(MemoryNote.id).where(
        MemoryNote.org_id == org_id,
        (func.lower(MemoryNote.path) == target_md.lower())
        | (func.lower(MemoryNote.path) == target.lower())
        | (func.lower(MemoryNote.title) == target.lower()),
    )
    if exclude_id:
        q = q.where(MemoryNote.id != exclude_id)
    r = await db.execute(q.limit(1))
    return r.scalar_one_or_none()


async def _rebuild_links(db, note: MemoryNote, wikilinks: list[str], hashtags: list[str]) -> None:
    """Replace all outgoing links for a note from its parsed references."""
    await db.execute(delete(MemoryLink).where(MemoryLink.src_note_id == note.id))
    for target in wikilinks:
        dst = await _resolve_wikilink(db, note.org_id, target, note.id)
        db.add(MemoryLink(
            id=str(uuid.uuid4()), org_id=note.org_id, src_note_id=note.id,
            dst_note_id=dst, via="wikilink", target_ref=target,
        ))
    for tag in hashtags:
        db.add(MemoryLink(
            id=str(uuid.uuid4()), org_id=note.org_id, src_note_id=note.id,
            dst_note_id=None, via="tag", target_ref=tag,
        ))


async def _reresolve_inbound(db, org_id: str, note: MemoryNote) -> None:
    """Point previously-unresolved wikilinks at this note now that it exists."""
    candidates = {note.path.lower(), note.title.lower()}
    if note.path.lower().endswith(".md"):
        candidates.add(note.path[:-3].lower())
    r = await db.execute(
        select(MemoryLink).where(
            MemoryLink.org_id == org_id,
            MemoryLink.via == "wikilink",
            MemoryLink.dst_note_id.is_(None),
            MemoryLink.src_note_id != note.id,
        )
    )
    for link in r.scalars().all():
        ref = link.target_ref.strip().lower()
        ref_noext = ref[:-3] if ref.endswith(".md") else ref
        if ref in candidates or ref_noext in candidates or f"{ref_noext}.md" in candidates:
            link.dst_note_id = note.id
            db.add(link)


def _slug(text: str, fallback: str = "item") -> str:
    s = re.sub(r"[^a-zA-Z0-9 _-]", "", text or "").strip().replace(" ", "-").lower()
    s = re.sub(r"-+", "-", s).strip("-")
    return s or fallback


async def auto_note_for_task(
    *,
    org_id: str,
    agent_id: str | None,
    agent_name: str | None,
    task_title: str,
    output: str,
    chat_id: str | None = None,
    user_id: str | None = None,
    project_name: str | None = None,
) -> dict | None:
    """Deterministically record a completed task as a memory note (no extra LLM call).

    Tagged by agent + project so the graph clusters related work. Returns the
    upsert result, or None when there's nothing worth recording.
    """
    body = (output or "").strip()
    if not body or len(body) < 16:
        return None  # nothing meaningful to remember

    agent_slug = _slug(agent_name or "agent", "agent")
    title_slug = _slug(task_title, "task")[:60]
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"agents/{agent_slug}/{day}-{title_slug}.md"

    tags = [agent_slug, "task"]
    if project_name:
        tags.append(_slug(project_name, "project"))

    md_lines = [
        f"# {task_title}".strip() or "# Task",
        "",
        body[:4000],
        "",
        "---",
        f"_Agent:_ {agent_name or 'unknown'}",
    ]
    if project_name:
        md_lines.append(f"_Project:_ {project_name}")
    md_lines.append(f"_Recorded:_ {day}")
    md_lines.append("")
    md_lines.append(" ".join(f"#{t}" for t in tags))
    body_md = "\n".join(md_lines)

    try:
        return await upsert_note(
            org_id=org_id, title=task_title or "Task", body_md=body_md, path=path,
            agent_id=agent_id, user_id=user_id, chat_id=chat_id, extra_tags=tags,
        )
    except Exception as exc:  # never let memory recording break task flow
        logger.warning("[memory_notes] auto_note_for_task failed: %s", exc)
        return None


async def upsert_note(
    *,
    org_id: str,
    title: str,
    body_md: str,
    path: str | None = None,
    agent_id: str | None = None,
    user_id: str | None = None,
    chat_id: str | None = None,
    extra_tags: list[str] | None = None,
    note_id: str | None = None,
) -> dict:
    """Create or update a memory note, (re)parse its references, and embed it.

    Identity: explicit ``note_id`` wins; else matched by (org_id, normalized path).
    """
    norm_path = normalize_path(path, title)
    wikilinks, hashtags = parse_references(body_md)
    tags = list(dict.fromkeys([*(t.lower() for t in (extra_tags or [])), *hashtags]))

    embedding = await embeddings.embed(f"{title}\n\n{body_md}", org_id)

    async with AsyncSessionLocal() as db:
        note = None
        if note_id:
            note = (await db.execute(select(MemoryNote).where(MemoryNote.id == note_id))).scalar_one_or_none()
        if not note:
            note = (await db.execute(
                select(MemoryNote).where(MemoryNote.org_id == org_id, MemoryNote.path == norm_path)
            )).scalar_one_or_none()

        created = note is None
        if created:
            note = MemoryNote(id=str(uuid.uuid4()), org_id=org_id, path=norm_path)
            db.add(note)

        note.title = title.strip() or norm_path
        note.body_md = body_md or ""
        note.path = norm_path
        note.tags = tags
        if agent_id:
            note.agent_id = agent_id
        if user_id:
            note.user_id = user_id
        if chat_id:
            note.chat_id = chat_id
        if embedding is not None:
            note.embedding = embedding
        note.updated_at = _utcnow()
        await db.flush()  # ensure note.id available for link FKs

        await _rebuild_links(db, note, wikilinks, hashtags)
        if created:
            await _reresolve_inbound(db, org_id, note)

        await db.commit()
        await db.refresh(note)

        logger.info(
            "[memory_notes] %s note %s (path=%s) links=%d tags=%d",
            "created" if created else "updated", note.id, note.path, len(wikilinks), len(tags),
        )
        return {
            "id": note.id, "path": note.path, "title": note.title,
            "tags": note.tags, "links": len(wikilinks), "created": created,
        }
