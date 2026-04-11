"""
Wiki I/O — TiddlyWiki MWS equivalent of vault_io.py.

Maps Obsidian vault operations to TiddlyWiki tiddler operations.
Each PDF document corresponds to one wiki (recipe) in MWS, named by slug.

Tag hierarchy model:
  Each section tiddler is tagged with:
    - The document slug (e.g. "demo-resolution-plan") → groups all sections in one doc
    - The parent section title → TiddlyWiki renders this as a tag tree
    - Content tags (doc_type, IBC section refs) → cross-document navigation

  This gives a collapsible tag tree in TiddlyWiki:
    demo-resolution-plan
    ├── Section 1: demo-resolution-plan.pdf
    │   ├── Section 10: IBBI/IPA-001/...
    │   └── Section 14: Resolution Applicant...
    └── Section 2: Untitled

Tiddler naming convention:
  - "Source Index"               → document dashboard
  - "Full Text"                  → complete document text
  - "Section {id}: {title}"      → section paragraph (tagged with hierarchy)
  - "Table {id}: {caption}"      → extracted table
  - JSON sidecars                → Parse Data, Tree Data, etc.

Chunk tiddlers are NO LONGER written — chunks are RAG artifacts
that go to LightRAG only, not TiddlyWiki.

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
        if not t:
            continue
        if " " in t or "/" in t:
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


def _extract_section_title(parent: str) -> str:
    """Extract a TiddlyWiki-compatible tag from a parent wikilink.

    Turns '[[sources/slug/sections/sec-1-foo.md]]' into 'Section 1: foo'
    or returns the raw string if it's already a tiddler title like 'Section 1: foo'.
    """
    if not parent:
        return ""
    # If it's already a tiddler title reference like [[Section 1: foo]]
    stripped = parent.strip("[]")
    if stripped.startswith("Section "):
        return stripped
    # Vault-style wikilink: [[sources/slug/sections/sec-N-title.md]]
    # Extract section ID and title from filename
    if "sections/" in stripped:
        filename = stripped.split("sections/")[-1].rstrip(".md")
        # sec-N-title -> Section N: title
        if filename.startswith("sec-"):
            parts = filename[4:].split("-", 1)
            sec_num = parts[0]
            sec_title = parts[1].replace("-", " ") if len(parts) > 1 else ""
            if sec_title:
                return f"Section {sec_num}: {sec_title}"
            return f"Section {sec_num}"
    return stripped


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
    """Write the Source Index tiddler — the document dashboard.

    Tagged with the slug so all sections can find their root.
    """
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

    # Build dashboard body
    body = f"# {filename}\n\n"
    body += f"**Pages:** {total_pages} | **Characters:** {total_chars:,}\n\n"
    if source_url:
        body += f"**Source:** [{source_url}]({source_url})\n\n"
    if doc_type and doc_type != "other":
        body += f"**Type:** {doc_type}\n\n"
    if doc_date:
        body += f"**Date:** {doc_date}\n\n"
    if parties:
        body += f"**Parties:** {', '.join(parties)}\n\n"
    body += f"**Pipeline stage:** {pipeline_stage}\n"

    # Tag with slug + doc_type so sections can reference it
    tags = [slug]
    if doc_type and doc_type != "other":
        tags.append(doc_type)

    await client.put_tiddler(
        slug, "Source Index",
        text=body,
        tags=_make_tags(*tags),
        fields=fields,
    )


async def write_full_text(
    client: MWSClient,
    slug: str,
    text: str,
    *,
    filename: str,
) -> None:
    """Write the Full Text tiddler — complete document text."""
    fields = {
        "source": "[[Source Index]]",
        "filename": filename,
    }
    await client.put_tiddler(
        slug, "Full Text",
        text=text,
        tags=_make_tags(slug, "full-text"),
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
    """Write a Section tiddler with tag-based hierarchy.

    Tags create a navigable tree in TiddlyWiki:
      - slug → groups all sections in this document
      - parent section title → TiddlyWiki renders parent→child tree
      - doc-level tags for cross-document navigation

    Content is the clean paragraph text (no enrichment headers).
    """
    tiddler_title = f"Section {section_id}: {title}"
    parent_tag = _extract_section_title(parent)

    fields = {
        "level": str(level),
        "heading_level": str(heading_level),
        "page_start": str(page_start),
        "page_end": str(page_end),
        "word_count": str(word_count),
        "is_leaf": str(is_leaf).lower(),
        "pipeline_stage": "pageindex",
        "section_id": section_id,
    }
    if summary:
        fields["summary"] = summary
    if children:
        fields["children"] = _serialize_list(children)

    # Build tag hierarchy: slug + parent section + doc tag
    tags = [slug]
    if parent_tag:
        tags.append(parent_tag)

    await client.put_tiddler(
        slug, tiddler_title,
        text=content,
        tags=_make_tags(*tags),
        fields=fields,
    )


# ──────────────────────────────────────────────────────────────
# Chunk operations — stubs only (chunks go to LightRAG, not TiddlyWiki)
# ──────────────────────────────────────────────────────────────

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
    """No-op — chunks are RAG artifacts, sent to LightRAG only."""
    pass


async def write_chunk_index(
    client: MWSClient,
    slug: str,
    *,
    total_chunks: int,
    total_tokens: int,
    document_title: str = "",
    document_summary: str = "",
) -> None:
    """No-op — chunk index is a RAG artifact, not needed in TiddlyWiki."""
    pass


async def update_pipeline_stage(
    client: MWSClient,
    slug: str,
    tiddler_title: str,
    new_stage: str,
) -> None:
    """Update the pipeline_stage field in a tiddler."""
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
    """Write a Table tiddler — tagged with slug for document grouping."""
    tiddler_title = f"Table {table_id}: {caption}"
    fields = {
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

    # Tag with slug so tables appear in the document's tag tree
    tags = [slug, "table"]
    if ibc_table_type:
        tags.append(ibc_table_type)

    await client.put_tiddler(
        slug, tiddler_title,
        text=body,
        tags=_make_tags(*tags),
        fields=fields,
    )


# ──────────────────────────────────────────────────────────────
# Read operations
# ──────────────────────────────────────────────────────────────

async def read_all_sections(client: MWSClient, slug: str) -> List[WikiNote]:
    """Read all section tiddlers for a wiki."""
    tiddlers = await client.get_tiddlers_by_tag(slug, slug)
    sections = []
    for t in tiddlers:
        full = await client.get_tiddler(slug, t.get("title", ""))
        if full is None:
            continue
        # Only return tiddlers that are sections (have section_id field)
        fields = full.get("fields", {})
        if "section_id" not in fields:
            continue
        metadata = {k: v for k, v in full.items() if k not in ("text",)}
        metadata["fields"] = fields
        sections.append(WikiNote(
            title=full.get("title", ""),
            metadata=metadata,
            body=full.get("text", ""),
        ))
    return sections


async def read_all_tables(client: MWSClient, slug: str) -> List[WikiNote]:
    """Read all table tiddlers for a wiki."""
    tiddlers = await client.get_tiddlers_by_tag(slug, "table")
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
    await client.put_json_tiddler(slug, "Parse Data", data, tags=_make_tags(slug, "parse-data"))


async def read_parse_json(client: MWSClient, slug: str) -> Optional[Dict[str, Any]]:
    """Read the cached LiteParse response. Returns None if not yet extracted."""
    return await client.get_json_tiddler(slug, "Parse Data")


async def write_tree_json(client: MWSClient, slug: str, data: Dict[str, Any]) -> None:
    """Cache the PageIndex tree as a JSON tiddler."""
    await client.put_json_tiddler(slug, "Tree Data", data, tags=_make_tags(slug, "tree-data"))


async def read_tree_json(client: MWSClient, slug: str) -> Optional[Dict[str, Any]]:
    """Read the cached PageIndex tree. Returns None if not yet built."""
    return await client.get_json_tiddler(slug, "Tree Data")


async def write_tables_json(client: MWSClient, slug: str, data: Dict[str, Any]) -> None:
    """Write structured table data as a JSON tiddler."""
    await client.put_json_tiddler(slug, "Tables Data", data, tags=_make_tags(slug, "tables-data"))


async def read_tables_json(client: MWSClient, slug: str) -> Optional[Dict[str, Any]]:
    """Read the cached tables JSON. Returns None if not yet extracted."""
    return await client.get_json_tiddler(slug, "Tables Data")


async def write_akn_json(client: MWSClient, slug: str, data: Dict[str, Any]) -> None:
    """Write AKN-lite annotation as a JSON tiddler."""
    await client.put_json_tiddler(slug, "AKN Data", data, tags=_make_tags(slug, "akn-data"))


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
    "_rpv.json": "RPV Data",
}


async def write_sidecar_json(
    client: MWSClient,
    slug: str,
    filename: str,
    data: Dict[str, Any],
) -> None:
    """Write any sidecar JSON as a tiddler."""
    title = _SIDECAR_TITLE_MAP.get(filename, filename.replace("_", " ").replace(".json", " Data").title())
    tag_name = filename.replace("_", "").replace(".json", "-data")
    await client.put_json_tiddler(slug, title, data, tags=_make_tags(slug, tag_name))


async def read_sidecar_json(
    client: MWSClient,
    slug: str,
    filename: str,
) -> Optional[Dict[str, Any]]:
    """Read a sidecar JSON tiddler. Returns None if not yet produced."""
    title = _SIDECAR_TITLE_MAP.get(filename, filename.replace("_", " ").replace(".json", " Data").title())
    return await client.get_json_tiddler(slug, title)


# ──────────────────────────────────────────────────────────────
# Generic note write (for vault_io.write_note equivalent)
# ──────────────────────────────────────────────────────────────

async def write_note_generic(
    client: MWSClient,
    slug: str,
    title: str,
    *,
    text: str = "",
    tags: str = "",
    fields: Optional[Dict[str, str]] = None,
) -> None:
    """Write a generic tiddler. Used for vault_io.write_note() equivalent
    where the vault path maps to a tiddler title.

    This is the catch-all for notes that don't have a specific wiki_io
    function (e.g., _links.md, _rpv.md, _financials.md, karpathy notes, etc.).
    """
    await client.put_tiddler(slug, title, text=text, tags=tags, fields=fields or {})
