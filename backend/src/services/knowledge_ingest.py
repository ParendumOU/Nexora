"""Knowledge base ingestion — chunk files and embed chunks in background."""
from __future__ import annotations
import logging
import re
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Chunking strategies ────────────────────────────────────────────────────────

def _chunk_fixed(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Split text into fixed-size character chunks with overlap."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - chunk_overlap
    return chunks


def _chunk_sentence(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Split on sentence boundaries (.!?), respect max chunk_size."""
    # Split on sentence-ending punctuation followed by whitespace/end
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sentence in sentences:
        sentence_len = len(sentence)
        # If a single sentence exceeds chunk_size, fall back to fixed splitting
        if sentence_len > chunk_size:
            # Flush current buffer first
            if current:
                chunks.append(" ".join(current))
                current = []
                current_len = 0
            sub_chunks = _chunk_fixed(sentence, chunk_size, chunk_overlap)
            chunks.extend(sub_chunks)
            continue

        if current_len + sentence_len + (1 if current else 0) > chunk_size:
            if current:
                chunks.append(" ".join(current))
            # Apply overlap: carry forward last sentences that fit within overlap budget
            overlap_buf: list[str] = []
            overlap_len = 0
            for s in reversed(current):
                if overlap_len + len(s) + 1 <= chunk_overlap:
                    overlap_buf.insert(0, s)
                    overlap_len += len(s) + 1
                else:
                    break
            current = overlap_buf
            current_len = overlap_len

        current.append(sentence)
        current_len += sentence_len + (1 if len(current) > 1 else 0)

    if current:
        chunks.append(" ".join(current))
    return chunks


def _chunk_paragraph(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Split on double newlines (paragraph boundaries), respect max chunk_size."""
    paragraphs = re.split(r'\n{2,}', text.strip())
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        # Oversized paragraph: fall back to fixed splitting
        if para_len > chunk_size:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0
            sub_chunks = _chunk_fixed(para, chunk_size, chunk_overlap)
            chunks.extend(sub_chunks)
            continue

        separator_len = 2 if current else 0  # "\n\n"
        if current_len + separator_len + para_len > chunk_size:
            if current:
                chunks.append("\n\n".join(current))
            # Overlap: carry last paragraph(s) that fit
            overlap_buf: list[str] = []
            overlap_len = 0
            for p in reversed(current):
                if overlap_len + len(p) + 2 <= chunk_overlap:
                    overlap_buf.insert(0, p)
                    overlap_len += len(p) + 2
                else:
                    break
            current = overlap_buf
            current_len = overlap_len

        current.append(para)
        current_len += para_len + (2 if len(current) > 1 else 0)

    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _chunk_text(
    text: str,
    strategy: str = "fixed",
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> list[str]:
    """Dispatch to the appropriate chunking strategy."""
    if strategy == "sentence":
        return _chunk_sentence(text, chunk_size, chunk_overlap)
    if strategy == "paragraph":
        return _chunk_paragraph(text, chunk_size, chunk_overlap)
    # Default: fixed
    return _chunk_fixed(text, chunk_size, chunk_overlap)


def _extract_text(data: bytes, content_type: str, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    try:
        if content_type == "application/pdf" or ext == ".pdf":
            import pdfplumber, io
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages)
        if content_type in (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ) or ext == ".docx":
            import docx, io
            doc = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs)
    except Exception as exc:
        logger.warning("Extraction failed for %s: %s", filename, exc)
    # Fallback: decode as UTF-8 text
    return data.decode("utf-8", errors="replace")


async def ingest_file(file_id: str, org_id: str, kb_id: str, data: bytes,
                      content_type: str, filename: str) -> None:
    """Extract text, chunk, embed, and persist KnowledgeChunk rows.

    Chunking parameters are loaded from the KnowledgeBase record so that
    each KB can use its own configured strategy/size/overlap.
    """
    from sqlalchemy import select, update
    from src.core.database import AsyncSessionLocal
    from src.models.knowledge_base import KnowledgeBase, KnowledgeFile, KnowledgeChunk
    from src.services.embeddings import embed

    # Load KB chunking config
    async with AsyncSessionLocal() as db:
        kb_r = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
        kb = kb_r.scalar_one_or_none()
        chunk_strategy = kb.chunk_strategy if kb else "fixed"
        chunk_size = kb.chunk_size if kb else 512
        chunk_overlap = kb.chunk_overlap if kb else 50

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(KnowledgeFile).where(KnowledgeFile.id == file_id)
            .values(status="processing")
        )
        await db.commit()

    try:
        text = _extract_text(data, content_type, filename)
        chunks = _chunk_text(text, strategy=chunk_strategy, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        if not chunks:
            raise ValueError("No text content extracted from file")

        chunk_rows = []
        for i, chunk in enumerate(chunks):
            embedding = await embed(chunk, org_id)
            chunk_rows.append(KnowledgeChunk(
                id=str(uuid.uuid4()),
                file_id=file_id, kb_id=kb_id, org_id=org_id,
                chunk_index=i, content=chunk, embedding=embedding,
            ))

        async with AsyncSessionLocal() as db:
            for row in chunk_rows:
                db.add(row)
            await db.execute(
                update(KnowledgeFile).where(KnowledgeFile.id == file_id)
                .values(status="ready", chunk_count=len(chunk_rows), error=None)
            )
            await db.commit()

        logger.info(
            "Ingested %d chunks for file %s (strategy=%s, size=%d, overlap=%d)",
            len(chunk_rows), file_id, chunk_strategy, chunk_size, chunk_overlap,
        )

    except Exception as exc:
        logger.error("Ingest failed for file %s: %s", file_id, exc)
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(KnowledgeFile).where(KnowledgeFile.id == file_id)
                .values(status="error", error=str(exc)[:500])
            )
            await db.commit()
