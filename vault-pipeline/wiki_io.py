"""
Wiki I/O — TiddlyWiki MWS equivalent of vault_io.py.

Maps all Obsidian vault operations to TiddlyWiki tiddler operations.
Each PDF document corresponds to one wiki (recipe) in MWS, named by slug.

Tiddler naming convention:
  - "Source Index"          → sources/{slug}/_index.md
  - "Full Text"            → sources/{slug}/full-text.md
  - "Section {id}: {title}" → sources/{slug}/sections/sec-{id}-{title}.md
  - "Chunk {nnn}"          → chunks/{slug}/chunk-{nnn}.md
  - "Chunk Index"           → chunks/{slug}/_index.md
  - "Table {id}: {caption}" → sources/{slug}/tables/table-{id}-{caption}.md
  - "Parse Data"            → sources/{slug}/_parse.json
  - "Tree Data"             → sources/{slug}/_tree.json
  - "Tables Data"           → sources/{slug}/_tables.json
  - "AKN Data"              → sources/{slug}/_akn.json
  - etc.

All functions are async and take (client: MWSClient, slug: str, ...) instead of
(vault_root: str | Path, slug: str, ...).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from mws_client import MWSClient

logger = logging.getLogger("vault-pipeline")


# ──────────────────────────────────────────────────────────────
# Helper classes and functions
# ──────────────────────────────────────────────────────────────

class WikiNote:
    """Parallel to VaultNote — represents a tiddler with metadata + body."""

    def __init__(self, title: str, metadata: Dict[str, Any], body: str):
        self.title = title
        self.metadata = metadata
        self.body = body

    @property
    def slug(self) -> str:
        """Tiddler title as identifier."""
        return self.title

    def __repr__(self):
        return f"WikiNote({self.title!r})"


def _make_tags(*tags: str) -> str:
    """Format tags for TiddlyWiki (space-separated, [[brackets]] for multi-word)."""
    parts = []
    for t in tags:
        if " " in t:
            parts.append(f"[[{t}]]")
        else:
            parts.append(t)
    return " ".join(parts)


def _serialize_list(lst: List[str]) -> str:
    """Serialize a Python list to a JSON string for tiddler field storage."""
    return json.dumps(lst, ensure_ascii=False)


def _deserialize_list(s: Optional[str]) -> List[str]:
    """Deserialize a JSON string back to a Python list."""
    if not s:
        return []
    try:
        result = json.loads(s)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


# ──────────────────────────────────────────────────────────────
# Wiki initialization
# ──────────────────────────────────────────────────────────────

async def init_wiki(client: MWSClient, slug: str, description: str = "") -> None:
    """Create a wiki (recipe + bag) for a document. Parallel to init_vault().

    Idempotent — does nothing if the wiki already exists.
    """
    if not await client.wiki_exists(slug):
        await client.create_wiki(slug, description)
        logger.info(f"Created wiki for: {slug}")


# ──────────────────────────────────────────────────────────────
# Write operations — one per pipeline stage (parallel to vault_io.py)
# ──────────────────────────────────────────────────────────────

async def write_source_index(
    client: MWSClient,
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
) -> None:
    """Write the Source Index tiddler. Parallel to vault_io.write_source_index()."""
    now = datetime.now(timezone.utc).isoformat()
    fields = {
        "slug": slug,
        "doc_type": doc_type,
        "doc_date": doc_date,
        "source_url": source_url,
        "filename": filename,
        "total_pages": str(total_pages),
        "total_chars": str(total_chars),
        "pipeline_stage": pipeline_stage,
        "created_at": now,
        "updated_at": now,
    }
    if parties:
        fields["parties"] = _serialize_list(parties)
    if statutory_refs:
        fields["statutory_refs"] = _serialize_list(statutory_refs)
    if children:
        fields["children"] = _serialize_list(children)

    body = f"# {filename}\n\n"
    body += f"**Pages:** {total_pages} | **Characters:** {total_chars:,}\n\n"
    if source_url:
        body += f"**Source:** [{source_url}]({source_url})\n\n"
    body += f"**Pipeline stage:** {pipeline_stage}\n"

    await client.put_tiddler(
        slug, "Source Index",
        text=body,
        tags=_make_tags("source-document"),
        fields=fields,
    )


async def write_full_text(
    client: MWSClient,
    slug: str,
    text: str,
    *,
    filename: str,
) -> None:
    """Write the Full Text tiddler. Parallel to vault_io.write_full_text()."""
    fields = {
        "source": "[[Source Index]]",
        "filename": filename,
    }
    await client.put_tiddler(
        slug, "Full Text",
        text=text,
        tags=_make_tags("full-text"),
        fields=fields,
    )


async def write_section_note(
    client: MWSClient,
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
) -> None:
    """Write a Section tiddler. Parallel to vault_io.write_section_note()."""
    tiddler_title = f"Section {section_id}: {title}"
    fields = {
        "source": "[[Source Index]]",
        "level": str(level),
        "heading_level": str(heading_level),
        "page_start": str(page_start),
        "page_end": str(page_end),
        "word_count": str(word_count),
        "summary": summary,
        "is_leaf": str(is_leaf).lower(),
        "pipeline_stage": "pageindex",
        "section_id": section_id,
    }
    if parent:
        fields["parent"] = parent
    if children:
        fields["children"] = _serialize_list(children)

    await client.put_tiddler(
        slug, tiddler_title,
        text=content,
        tags=_make_tags("section-node"),
        fields=fields,
    )


async def write_chunk_note(
    client: MWSClient,
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
) -> None:
    """Write a Chunk tiddler. Parallel to vault_io.write_chunk_note()."""
    tiddler_title = f"Chunk {chunk_index + 1:03d}"
    fields = {
        "source": source_wikilink or "[[Source Index]]",
        "section": section_wikilink,
        "chunk_index": str(chunk_index),
        "total_chunks": str(total_chunks),
        "page_start": str(page_start),
        "page_end": str(page_end),
        "token_count": str(token_count),
        "level": str(level),
        "parent_context": parent_context,
        "has_overlap": str(has_overlap).lower(),
        "pipeline_stage": "semchunk",
        "lightrag_ingested": "false",
        "ingested_at": "",
    }
    if doc_type:
        fields["doc_type"] = doc_type
    if doc_date:
        fields["doc_date"] = doc_date
    if parties:
        fields["parties"] = _serialize_list(parties)
    if statutory_refs:
        fields["statutory_refs"] = _serialize_list(statutory_refs)
    if akn_element:
        fields["akn_element"] = akn_element

    await client.put_tiddler(
        slug, tiddler_title,
        text=content,
        tags=_make_tags("contextualized-chunk"),
        fields=fields,
    )


async def write_chunk_index(
    client: MWSClient,
    slug: str,
    *,
    total_chunks: int,
    total_tokens: int,
    document_title: str = "",
    document_summary: str = "",
) -> None:
    """Write the Chunk Index tiddler. Parallel to vault_io.write_chunk_index()."""
    fields = {
        "source": "[[Source Index]]",
        "total_chunks": str(total_chunks),
        "total_tokens": str(total_tokens),
        "document_title": document_title,
        "document_summary": document_summary,
        "pipeline_stage": "semchunk",
    }
    body = f"# Chunks: {document_title or slug}\n\n"
    body += f"**Total chunks:** {total_chunks} | **Total tokens:** {total_tokens:,}\n\n"
    body += f"**Pipeline stage:** semchunk\n"

    await client.put_tiddler(
        slug, "Chunk Index",
        text=body,
        tags=_make_tags("chunk-index"),
        fields=fields,
    )


async def update_pipeline_stage(
    client: MWSClient,
    slug: str,
    tiddler_title: str,
    new_stage: str,
) -> None:
    """Update the pipeline_stage field in a tiddler. Parallel to vault_io.update_pipeline_stage()."""
    tiddler = await client.get_tiddler(slug, tiddler_title)
    if tiddler is None:
        logger.warning(f"Tiddler '{tiddler_title}' not found in wiki '{slug}'")
        return

    fields = tiddler.get("fields", {})
    fields["pipeline_stage"] = new_stage
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()

    await client.put_tiddler(
        slug, tiddler_title,
        text=tiddler.get("text", ""),
        tags=tiddler.get("tags", ""),
        fields=fields,
    )


async def write_table_note(
    client: MWSClient,
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
) -> None:
    """Write a Table tiddler. Parallel to vault_io.write_table_note()."""
    tiddler_title = f"Table {table_id}: {caption}"
    fields = {
        "source": "[[Source Index]]",
        "table_id": table_id,
        "page": str(page),
        "caption": caption,
        "headers": _serialize_list(headers),
        "rows_count": str(len(rows)),
        "has_structured_data": "true",
        "pipeline_stage": "indexed",
    }
    if ibc_table_type:
        fields["ibc_table_type"] = ibc_table_type
    if doc_meta:
        for k, v in doc_meta.items():
            if v:
                fields[k] = str(v)

    body = ""
    if context_before:
        body += f"**Context:** {context_before.strip()}\n\n"
    body += markdown
    if context_after:
        body += f"\n\n*{context_after.strip()}*"
    body += f"\n\n*Source: Page {page}*"

    await client.put_tiddler(
        slug, tiddler_title,
        text=body,
        tags=_make_tags("table-note"),
        fields=fields,
    )


# ──────────────────────────────────────────────────────────────
# Read operations
# ──────────────────────────────────────────────────────────────

async def read_all_chunks(client: MWSClient, slug: str) -> List[WikiNote]:
    """Read all chunk tiddlers for a wiki, sorted by chunk_index.
    Parallel to vault_io.read_all_chunks().
    """
    tiddlers = await client.get_tiddlers_by_tag(slug, "contextualized-chunk")
    chunks = []
    for t in tiddlers:
        full = await client.get_tiddler(slug, t.get("title", ""))
        if full is None:
            continue
        metadata = {k: v for k, v in full.items() if k not in ("text",)}
        metadata["fields"] = full.get("fields", {})
        chunks.append(WikiNote(
            title=full.get("title", ""),
            metadata=metadata,
            body=full.get("text", ""),
        ))
    # Sort by chunk_index field
    chunks.sort(key=lambda n: int(n.metadata.get("fields", {}).get("chunk_index", "0")))
    return chunks


async def read_all_sections(client: MWSClient, slug: str) -> List[WikiNote]:
    """Read all section tiddlers for a wiki.
    Parallel to vault_io.read_all_sections().
    """
    tiddlers = await client.get_tiddlers_by_tag(slug, "section-node")
    sections = []
    for t in tiddlers:
        full = await client.get_tiddler(slug, t.get("title", ""))
        if full is None:
            continue
        metadata = {k: v for k, v in full.items() if k not in ("text",)}
        metadata["fields"] = full.get("fields", {})
        sections.append(WikiNote(
            title=full.get("title", ""),
            metadata=metadata,
            body=full.get("text", ""),
        ))
    return sections


async def read_all_tables(client: MWSClient, slug: str) -> List[WikiNote]:
    """Read all table tiddlers for a wiki.
    Parallel to vault_io.read_all_tables().
    """
    tiddlers = await client.get_tiddlers_by_tag(slug, "table-note")
    tables = []
    for t in tiddlers:
        full = await client.get_tiddler(slug, t.get("title", ""))
        if full is None:
            continue
        metadata = {k: v for k, v in full.items() if k not in ("text",)}
        metadata["fields"] = full.get("fields", {})
        tables.append(WikiNote(
            title=full.get("title", ""),
            metadata=metadata,
            body=full.get("text", ""),
        ))
    return tables


# ──────────────────────────────────────────────────────────────
# Intermediate data caching (JSON sidecars)
# ──────────────────────────────────────────────────────────────

async def write_parse_json(client: MWSClient, slug: str, data: Dict[str, Any]) -> None:
    """Cache the LiteParse response as a JSON tiddler."""
    await client.put_json_tiddler(slug, "Parse Data", data, tags=_make_tags("parse-data"))


async def read_parse_json(client: MWSClient, slug: str) -> Optional[Dict[str, Any]]:
    """Read the cached LiteParse response. Returns None if not yet extracted."""
    return await client.get_json_tiddler(slug, "Parse Data")


async def write_tree_json(client: MWSClient, slug: str, data: Dict[str, Any]) -> None:
    """Cache the PageIndex tree as a JSON tiddler."""
    await client.put_json_tiddler(slug, "Tree Data", data, tags=_make_tags("tree-data"))


async def read_tree_json(client: MWSClient, slug: str) -> Optional[Dict[str, Any]]:
    """Read the cached PageIndex tree. Returns None if not yet built."""
    return await client.get_json_tiddler(slug, "Tree Data")


async def write_tables_json(client: MWSClient, slug: str, data: Dict[str, Any]) -> None:
    """Write structured table data as a JSON tiddler."""
    await client.put_json_tiddler(slug, "Tables Data", data, tags=_make_tags("tables-data"))


async def read_tables_json(client: MWSClient, slug: str) -> Optional[Dict[str, Any]]:
    """Read the cached tables JSON. Returns None if not yet extracted."""
    return await client.get_json_tiddler(slug, "Tables Data")


async def write_akn_json(client: MWSClient, slug: str, data: Dict[str, Any]) -> None:
    """Write AKN-lite annotation as a JSON tiddler."""
    await client.put_json_tiddler(slug, "AKN Data", data, tags=_make_tags("akn-data"))


async def read_akn_json(client: MWSClient, slug: str) -> Optional[Dict[str, Any]]:
    """Read the AKN-lite annotation. Returns None if stage_akn hasn't run."""
    return await client.get_json_tiddler(slug, "AKN Data")


# ──────────────────────────────────────────────────────────────
# Generic sidecar JSON
# ──────────────────────────────────────────────────────────────

# Map of filename → tiddler title for sidecar JSONs
_SIDECAR_TITLE_MAP = {
    "_timeline.json": "Timeline Data",
    "_obligations.json": "Obligations Data",
    "_entities.json": "Entities Data",
    "_citations.json": "Citations Data",
    "_meta.json": "Meta Data",
}


async def write_sidecar_json(
    client: MWSClient,
    slug: str,
    filename: str,
    data: Dict[str, Any],
) -> None:
    """Write any sidecar JSON as a tiddler.
    Parallel to vault_io.write_sidecar_json().

    Used for _timeline.json, _obligations.json, _entities.json, _citations.json.
    """
    title = _SIDECAR_TITLE_MAP.get(filename, filename.replace("_", " ").replace(".json", " Data").title())
    tag_name = filename.replace("_", "").replace(".json", "-data")
    await client.put_json_tiddler(slug, title, data, tags=_make_tags(tag_name))


async def read_sidecar_json(
    client: MWSClient,
    slug: str,
    filename: str,
) -> Optional[Dict[str, Any]]:
    """Read a sidecar JSON tiddler. Returns None if not yet produced."""
    title = _SIDECAR_TITLE_MAP.get(filename, filename.replace("_", " ").replace(".json", " Data").title())
    return await client.get_json_tiddler(slug, title)