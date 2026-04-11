"""
Dual Write — writes to both Obsidian vault (primary) and TiddlyWiki MWS (mirror).

Every write goes to vault first (sync, reliable, source of truth).
Then a best-effort write is scheduled to TiddlyWiki MWS (async, background).
If MWS is down, the pipeline continues with vault-only writes.

All functions are SYNCHRONOUS (matching vault_io signatures) so they can be
called from both sync and async contexts without await.

Reads stay on vault — TiddlyWiki is a presentation/browsing layer only.

Usage (identical to vault_io, just import from dual_write instead):
    from dual_write import write_source_index
    write_source_index(VAULT_ROOT, slug, filename=filename, ...)  # sync
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import vault_io
import wiki_io
from wiki_manager import get_client

logger = logging.getLogger("vault-pipeline")

# Track whether MWS is available (set to False after consecutive failures)
_mws_fail_count: int = 0
_MWS_MAX_FAILS: int = 3  # suppress logging after this many failures
_MWS_ENABLED: bool = True  # global toggle
_ensured_wikis: set = set()  # track slugs that have had their wiki ensured
_ensure_lock = asyncio.Lock()  # prevent concurrent wiki creation for same slug


def _schedule_wiki(coro):
    """Schedule a wiki write coroutine as a background task (fire-and-forget).

    Works from both sync and async contexts because it uses the running
    event loop's create_task method. If no event loop is running (unlikely
    in FastAPI), the coroutine is silently discarded.
    """
    global _mws_fail_count, _MWS_ENABLED

    if not _MWS_ENABLED:
        logger.debug("MWS disabled — skipping wiki write")
        return

    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro)
        logger.debug(f"Scheduled wiki task: {coro}")
    except RuntimeError:
        # No running event loop — can't schedule
        logger.warning(f"No running event loop — can't schedule wiki write: {coro}")


async def _wiki_write_with_retry(func, *args, slug: str = "", **kwargs):
    """Execute a wiki_io write with error handling and retry tracking.

    Ensures the wiki exists before writing (idempotent check).
    """
    global _mws_fail_count, _MWS_ENABLED

    # Ensure the wiki exists before any write
    if slug and slug not in _ensured_wikis:
        await _ensure_wiki_async(slug)

    try:
        result = await func(*args, **kwargs)
        _mws_fail_count = 0  # reset on success
        logger.debug(f"Wiki write succeeded: {func.__name__}")
        return result
    except Exception as e:
        _mws_fail_count += 1
        if _mws_fail_count <= _MWS_MAX_FAILS:
            logger.warning(f"MWS write failed ({_mws_fail_count}) [{func.__name__}]: {e}")
        elif _mws_fail_count == _MWS_MAX_FAILS + 1:
            logger.error(f"MWS write failed {_mws_fail_count} times — suppressing further warnings until restart")
        # Don't disable entirely — MWS might come back up


async def _ensure_wiki_async(slug: str, description: str = ""):
    """Ensure a wiki exists for this slug. Idempotent — only creates once per slug."""
    global _ensured_wikis
    if slug in _ensured_wikis:
        return
    async with _ensure_lock:
        # Double-check after acquiring lock (another task may have created it)
        if slug in _ensured_wikis:
            return
        try:
            client = get_client()
            await wiki_io.init_wiki(client, slug, description)
            _ensured_wikis.add(slug)
            logger.info(f"Wiki ensured: {slug}")
        except Exception as e:
            logger.warning(f"Failed to ensure wiki for {slug}: {e}")


# ──────────────────────────────────────────────────────────────
# Dual-write functions — same signatures as vault_io, sync interface
# ──────────────────────────────────────────────────────────────

def write_source_index(
    vault_root: str | Path,
    slug: str,
    *,
    filename: str,
    total_pages: int,
    total_chars: int,
    source_url: str = "",
    doc_type: str = "other",
    doc_date: str = "",
    parties: List[str] | None = None,
    statutory_refs: List[str] | None = None,
    children: List[str] | None = None,
    pipeline_stage: str = "liteparse",
) -> Path:
    """Write source index to vault, then mirror to TiddlyWiki (fire-and-forget)."""
    result = vault_io.write_source_index(
        vault_root, slug,
        filename=filename, total_pages=total_pages, total_chars=total_chars,
        source_url=source_url, doc_type=doc_type, doc_date=doc_date,
        parties=parties, statutory_refs=statutory_refs, children=children,
        pipeline_stage=pipeline_stage,
    )
    _schedule_wiki(_wiki_write_with_retry(
        wiki_io.write_source_index, get_client(), slug,
        slug=slug,
        filename=filename, total_pages=total_pages, total_chars=total_chars,
        source_url=source_url, doc_type=doc_type, doc_date=doc_date,
        parties=parties, statutory_refs=statutory_refs, children=children,
        pipeline_stage=pipeline_stage,
    ))
    return result


def write_full_text(
    vault_root: str | Path,
    slug: str,
    text: str,
    *,
    filename: str,
) -> Path:
    """Write full text to vault, then mirror to TiddlyWiki."""
    result = vault_io.write_full_text(vault_root, slug, text, filename=filename)
    _schedule_wiki(_wiki_write_with_retry(
        wiki_io.write_full_text, get_client(), slug, text, filename=filename,
        slug=slug,
    ))
    return result


def write_section_note(
    vault_root: str | Path,
    slug: str,
    section_id: str,
    *,
    level: int,
    heading_level: int,
    title: str,
    content: str,
    summary: str = "",
    page_start: int = 1,
    page_end: int = 1,
    word_count: int = 0,
    parent: str = "",
    children: List[str] | None = None,
    is_leaf: bool = False,
) -> Path:
    """Write section note to vault, then mirror to TiddlyWiki."""
    result = vault_io.write_section_note(
        vault_root, slug, section_id,
        level=level, heading_level=heading_level, title=title,
        content=content, summary=summary,
        page_start=page_start, page_end=page_end,
        word_count=word_count, parent=parent,
        children=children, is_leaf=is_leaf,
    )
    _schedule_wiki(_wiki_write_with_retry(
        wiki_io.write_section_note, get_client(), slug, section_id,
        slug=slug,
        level=level, heading_level=heading_level, title=title,
        content=content, summary=summary,
        page_start=page_start, page_end=page_end,
        word_count=word_count, parent=parent,
        children=children, is_leaf=is_leaf,
    ))
    return result


def write_chunk_note(
    vault_root: str | Path,
    slug: str,
    chunk_index: int,
    *,
    total_chunks: int,
    content: str,
    parent_context: str = "",
    page_start: int = 1,
    page_end: int = 1,
    token_count: int = 0,
    level: int = 0,
    has_overlap: bool = False,
    source_wikilink: str = "",
    section_wikilink: str = "",
    doc_type: str = "",
    doc_date: str = "",
    parties: List[str] | None = None,
    statutory_refs: List[str] | None = None,
    akn_element: str = "",
) -> Path:
    """No-op — chunks are RAG artifacts for LightRAG only.

    Neither vault nor TiddlyWiki receives chunk data.
    Returns a dummy path for API compatibility.
    """
    dummy_path = Path(vault_root) / "chunks" / slug / f"chunk-{chunk_index + 1:03d}.md"
    return dummy_path


def write_chunk_index(
    vault_root: str | Path,
    slug: str,
    *,
    total_chunks: int,
    total_tokens: int,
    document_title: str = "",
    document_summary: str = "",
) -> Path:
    """No-op — chunk index is a RAG artifact, not needed in vault or TiddlyWiki."""
    dummy_path = Path(vault_root) / "chunks" / slug / "_index.md"
    return dummy_path


def write_table_note(
    vault_root: str | Path,
    slug: str,
    table_id: str,
    *,
    page: int,
    caption: str,
    headers: List[str],
    rows: List[List[str]],
    markdown: str,
    context_before: str = "",
    context_after: str = "",
    doc_meta: Dict[str, Any] | None = None,
    ibc_table_type: str = "",
) -> Path:
    """Write table note to vault, then mirror to TiddlyWiki."""
    result = vault_io.write_table_note(
        vault_root, slug, table_id,
        page=page, caption=caption, headers=headers, rows=rows,
        markdown=markdown, context_before=context_before,
        context_after=context_after, doc_meta=doc_meta,
        ibc_table_type=ibc_table_type,
    )
    _schedule_wiki(_wiki_write_with_retry(
        wiki_io.write_table_note, get_client(), slug, table_id,
        slug=slug,
        page=page, caption=caption, headers=headers, rows=rows,
        markdown=markdown, context_before=context_before,
        context_after=context_after, doc_meta=doc_meta,
        ibc_table_type=ibc_table_type,
    ))
    return result


def update_pipeline_stage(
    vault_root: str | Path,
    rel_path: str,
    new_stage: str,
    slug: str = "",
    tiddler_title: str = "",
) -> Path:
    """Update pipeline stage in vault, then mirror to TiddlyWiki.

    For the wiki mirror, pass slug + tiddler_title so we can find the right tiddler.
    """
    result = vault_io.update_pipeline_stage(vault_root, rel_path, new_stage)

    if slug and tiddler_title:
        _schedule_wiki(_wiki_write_with_retry(
            wiki_io.update_pipeline_stage, get_client(), slug, tiddler_title, new_stage,
            slug=slug,
        ))
    return result


def write_note(
    vault_root: str | Path,
    rel_path: str,
    metadata: Dict[str, Any],
    body: str,
    slug: str = "",
    tiddler_title: str = "",
    tags: str = "",
) -> Path:
    """Write a generic note to vault, then mirror to TiddlyWiki.

    For the wiki mirror, pass slug + tiddler_title + tags.
    Notes under chunks/ are RAG artifacts — skip both vault and TiddlyWiki.
    """
    if str(rel_path).startswith("chunks/"):
        # Chunks are RAG artifacts — skip vault and TiddlyWiki entirely
        return Path(vault_root) / rel_path
    else:
        result = vault_io.write_note(vault_root, rel_path, metadata, body)

    if slug and tiddler_title:
        fields = {k: str(v) if not isinstance(v, str) else v
                  for k, v in metadata.items() if k != "type"}
        _schedule_wiki(_wiki_write_with_retry(
            wiki_io.write_note_generic, get_client(), slug, tiddler_title,
            slug=slug,
            text=body, tags=tags, fields=fields,
        ))
    return result


# ──────────────────────────────────────────────────────────────
# JSON sidecars — mirror to TiddlyWiki as JSON tiddlers
# ──────────────────────────────────────────────────────────────

def write_parse_json(vault_root: str | Path, slug: str, data: Dict[str, Any]) -> Path:
    """Write parse JSON to vault, then mirror to TiddlyWiki."""
    result = vault_io.write_parse_json(vault_root, slug, data)
    _schedule_wiki(_wiki_write_with_retry(
        wiki_io.write_parse_json, get_client(), slug, data,
        slug=slug,
    ))
    return result


def write_tree_json(vault_root: str | Path, slug: str, data: Dict[str, Any]) -> Path:
    """Write tree JSON to vault, then mirror to TiddlyWiki."""
    result = vault_io.write_tree_json(vault_root, slug, data)
    _schedule_wiki(_wiki_write_with_retry(
        wiki_io.write_tree_json, get_client(), slug, data,
        slug=slug,
    ))
    return result


def write_tables_json(vault_root: str | Path, slug: str, data: Dict[str, Any]) -> Path:
    """Write tables JSON to vault, then mirror to TiddlyWiki."""
    result = vault_io.write_tables_json(vault_root, slug, data)
    _schedule_wiki(_wiki_write_with_retry(
        wiki_io.write_tables_json, get_client(), slug, data,
        slug=slug,
    ))
    return result


def write_akn_json(vault_root: str | Path, slug: str, data: Dict[str, Any]) -> Path:
    """Write AKN JSON to vault, then mirror to TiddlyWiki."""
    result = vault_io.write_akn_json(vault_root, slug, data)
    _schedule_wiki(_wiki_write_with_retry(
        wiki_io.write_akn_json, get_client(), slug, data,
        slug=slug,
    ))
    return result


def write_sidecar_json(
    vault_root: str | Path, slug: str, filename: str, data: Dict[str, Any],
) -> Path:
    """Write sidecar JSON to vault, then mirror to TiddlyWiki."""
    result = vault_io.write_sidecar_json(vault_root, slug, filename, data)
    _schedule_wiki(_wiki_write_with_retry(
        wiki_io.write_sidecar_json, get_client(), slug, filename, data,
        slug=slug,
    ))
    return result