"""
Vault I/O — read/write Obsidian vault markdown files with YAML frontmatter.

Each vault note is a markdown file with YAML frontmatter delimited by ---.
This module provides:
  - read_note() / write_note() — frontmatter + body round-trip
  - slug generation for vault-safe filenames
  - Vault directory structure constants
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import frontmatter  # python-frontmatter
from slugify import slugify


# ──────────────────────────────────────────────────────────────
# Vault directory layout
# ──────────────────────────────────────────────────────────────

VAULT_DIRS = [
    "sources",       # Stage 1: parsed documents
    "chunks",        # Stage 2: semantic chunks
    "compliance",    # Stage 3: verification results
    "audit",         # Ingestion audit trail
    "_templates",    # Obsidian note templates
    "_attachments",  # Binary files (PDFs, images)
    "_karpathy",     # Local search index (RAG2-Desk only)
    "_global",       # Global cross-document indexes (HNSW, BM25)
    "matters",       # Matter groups (cross-document)
]


def init_vault(vault_root: str | Path) -> None:
    """Create vault directory structure if it doesn't exist."""
    vault_root = Path(vault_root)
    vault_root.mkdir(parents=True, exist_ok=True)
    for d in VAULT_DIRS:
        (vault_root / d).mkdir(parents=True, exist_ok=True)
    # Also create compliance subdirs
    (vault_root / "compliance" / "matters").mkdir(parents=True, exist_ok=True)
    (vault_root / "compliance" / "checks").mkdir(parents=True, exist_ok=True)
    (vault_root / "compliance" / "verifications").mkdir(parents=True, exist_ok=True)


def make_slug(text: str) -> str:
    """Generate a filesystem-safe slug from arbitrary text."""
    return slugify(text, lowercase=True, max_length=80, separator="-")


# ──────────────────────────────────────────────────────────────
# Read / Write notes
# ──────────────────────────────────────────────────────────────

class VaultNote:
    """Represents an Obsidian vault note with frontmatter + body."""

    def __init__(self, path: Path, metadata: Dict[str, Any], body: str):
        self.path = path
        self.metadata = metadata
        self.body = body

    @property
    def slug(self) -> str:
        """Filename without .md extension."""
        return self.path.stem

    def __repr__(self):
        return f"VaultNote({self.path})"


def write_note(
    vault_root: str | Path,
    rel_path: str,
    metadata: Dict[str, Any],
    body: str,
) -> Path:
    """
    Write a vault note with YAML frontmatter.

    Args:
        vault_root: Absolute path to vault root directory.
        rel_path: Relative path from vault root (e.g. 'sources/my-doc/_index.md').
        metadata: Dict of frontmatter fields.
        body: Markdown body content.

    Returns:
        Absolute path of the written file.
    """
    vault_root = Path(vault_root)
    full_path = vault_root / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)

    # Use python-frontmatter for clean YAML serialization
    post = frontmatter.Post(content=body, **metadata)
    content = frontmatter.dumps(post)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)

    return full_path


def read_note(vault_root: str | Path, rel_path: str) -> VaultNote:
    """
    Read a vault note, parsing YAML frontmatter.

    Args:
        vault_root: Absolute path to vault root directory.
        rel_path: Relative path from vault root.

    Returns:
        VaultNote with parsed metadata and body.

    Raises:
        FileNotFoundError: If the note doesn't exist.
    """
    vault_root = Path(vault_root)
    full_path = vault_root / rel_path

    if not full_path.exists():
        raise FileNotFoundError(f"Vault note not found: {full_path}")

    post = frontmatter.load(full_path)
    return VaultNote(
        path=full_path,
        metadata=dict(post.metadata),
        body=post.content,
    )


def note_exists(vault_root: str | Path, rel_path: str) -> bool:
    """Check if a vault note exists."""
    return (Path(vault_root) / rel_path).exists()


def list_notes(vault_root: str | Path, rel_dir: str, pattern: str = "*.md") -> List[Path]:
    """List all .md notes in a vault directory (non-recursive)."""
    vault_root = Path(vault_root)
    dir_path = vault_root / rel_dir
    if not dir_path.exists():
        return []
    return sorted(dir_path.glob(pattern))


def list_notes_recursive(vault_root: str | Path, rel_dir: str, pattern: str = "*.md") -> List[Path]:
    """List all .md notes in a vault directory recursively."""
    vault_root = Path(vault_root)
    dir_path = vault_root / rel_dir
    if not dir_path.exists():
        return []
    return sorted(dir_path.rglob(pattern))


# ──────────────────────────────────────────────────────────────
# Vault writers — one per pipeline stage
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
    """Write the sources/{slug}/_index.md root note for a parsed document."""
    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        "type": "source-document",
        "slug": slug,
        "doc_type": doc_type,
        "doc_date": doc_date,
        "source_url": source_url,
        "filename": filename,
        "total_pages": total_pages,
        "total_chars": total_chars,
        "pipeline_stage": pipeline_stage,
        "created_at": now,
        "updated_at": now,
    }
    if parties:
        metadata["parties"] = parties
    if statutory_refs:
        metadata["statutory_refs"] = statutory_refs
    if children:
        metadata["children"] = children

    body = f"# {filename}\n\n"
    body += f"**Pages:** {total_pages} | **Characters:** {total_chars:,}\n\n"
    if source_url:
        body += f"**Source:** [{source_url}]({source_url})\n\n"
    body += f"**Pipeline stage:** {pipeline_stage}\n"

    return write_note(vault_root, f"sources/{slug}/_index.md", metadata, body)


def write_full_text(
    vault_root: str | Path,
    slug: str,
    text: str,
    *,
    filename: str,
) -> Path:
    """Write the sources/{slug}/full-text.md with the full extracted text."""
    metadata = {
        "type": "full-text",
        "source": f"[[sources/{slug}/_index]]",
        "filename": filename,
    }
    return write_note(vault_root, f"sources/{slug}/full-text.md", metadata, text)


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
    """Write a sources/{slug}/sections/sec-{id}.md section node note."""
    metadata = {
        "type": "section-node",
        "source": f"[[sources/{slug}/_index]]",
        "level": level,
        "heading_level": heading_level,
        "page_start": page_start,
        "page_end": page_end,
        "word_count": word_count,
        "summary": summary,
        "is_leaf": is_leaf,
        "pipeline_stage": "pageindex",
    }
    if parent:
        metadata["parent"] = parent
    if children:
        metadata["children"] = children

    # Section filename: sec-{id}-{slugified-title}.md
    title_slug = make_slug(title) if title else "untitled"
    filename = f"sec-{section_id}-{title_slug}.md"
    return write_note(vault_root, f"sources/{slug}/sections/{filename}", metadata, content)


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
    """Write a chunks/{slug}/chunk-{nnn}.md chunk note."""
    metadata = {
        "type": "contextualized-chunk",
        "source": source_wikilink or f"[[sources/{slug}/_index]]",
        "section": section_wikilink,
        "chunk_index": chunk_index,
        "total_chunks": total_chunks,
        "page_start": page_start,
        "page_end": page_end,
        "token_count": token_count,
        "level": level,
        "parent_context": parent_context,
        "has_overlap": has_overlap,
        "pipeline_stage": "semchunk",
        "lightrag_ingested": False,
        "ingested_at": None,
    }
    if doc_type:
        metadata["doc_type"] = doc_type
    if doc_date:
        metadata["doc_date"] = doc_date
    if parties:
        metadata["parties"] = parties
    if statutory_refs:
        metadata["statutory_refs"] = statutory_refs
    if akn_element:
        metadata["akn_element"] = akn_element

    filename = f"chunk-{chunk_index + 1:03d}.md"  # chunk-001.md, chunk-002.md, ...
    return write_note(vault_root, f"chunks/{slug}/{filename}", metadata, content)


def write_chunk_index(
    vault_root: str | Path,
    slug: str,
    *,
    total_chunks: int,
    total_tokens: int,
    document_title: str = "",
    document_summary: str = "",
) -> Path:
    """Write the chunks/{slug}/_index.md chunk manifest."""
    metadata = {
        "type": "chunk-index",
        "source": f"[[sources/{slug}/_index]]",
        "total_chunks": total_chunks,
        "total_tokens": total_tokens,
        "document_title": document_title,
        "document_summary": document_summary,
        "pipeline_stage": "semchunk",
    }
    body = f"# Chunks: {document_title or slug}\n\n"
    body += f"**Total chunks:** {total_chunks} | **Total tokens:** {total_tokens:,}\n\n"
    body += f"**Pipeline stage:** semchunk\n"

    return write_note(vault_root, f"chunks/{slug}/_index.md", metadata, body)


def update_pipeline_stage(
    vault_root: str | Path,
    rel_path: str,
    new_stage: str,
) -> Path:
    """Update the pipeline_stage field in a vault note's frontmatter."""
    note = read_note(vault_root, rel_path)
    note.metadata["pipeline_stage"] = new_stage
    note.metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
    return write_note(vault_root, rel_path, note.metadata, note.body)


def read_all_chunks(vault_root: str | Path, slug: str) -> List[VaultNote]:
    """Read all chunk notes for a source document, sorted by chunk_index."""
    chunks_dir = Path(vault_root) / "chunks" / slug
    if not chunks_dir.exists():
        return []
    notes = []
    for f in sorted(chunks_dir.glob("chunk-*.md")):
        post = frontmatter.load(f)
        notes.append(VaultNote(path=f, metadata=dict(post.metadata), body=post.content))
    return notes


def read_all_sections(vault_root: str | Path, slug: str) -> List[VaultNote]:
    """Read all section notes for a source document."""
    sections_dir = Path(vault_root) / "sources" / slug / "sections"
    if not sections_dir.exists():
        return []
    notes = []
    for f in sorted(sections_dir.glob("sec-*.md")):
        post = frontmatter.load(f)
        notes.append(VaultNote(path=f, metadata=dict(post.metadata), body=post.content))
    return notes


# ──────────────────────────────────────────────────────────────
# Intermediate data caching (LiteParse JSON, PageIndex tree)
# ──────────────────────────────────────────────────────────────

import json as _json


def write_parse_json(vault_root: str | Path, slug: str, data: Dict[str, Any]) -> Path:
    """Cache the LiteParse response as JSON for re-processing."""
    path = Path(vault_root) / "sources" / slug / "_parse.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def read_parse_json(vault_root: str | Path, slug: str) -> Optional[Dict[str, Any]]:
    """Read the cached LiteParse response."""
    path = Path(vault_root) / "sources" / slug / "_parse.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return _json.load(f)


def write_tree_json(vault_root: str | Path, slug: str, data: Dict[str, Any]) -> Path:
    """Cache the PageIndex tree as JSON for re-processing."""
    path = Path(vault_root) / "sources" / slug / "_tree.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def read_tree_json(vault_root: str | Path, slug: str) -> Optional[Dict[str, Any]]:
    """Read the cached PageIndex tree."""
    path = Path(vault_root) / "sources" / slug / "_tree.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return _json.load(f)


# ──────────────────────────────────────────────────────────────
# Tables JSON — structured table extraction (_tables.json)
# ──────────────────────────────────────────────────────────────

def write_tables_json(vault_root: str | Path, slug: str, data: Dict[str, Any]) -> Path:
    """Write structured table data extracted by the parser (LlamaParse or LiteParse).

    Schema:
      { schema_version: "1.0", parser: str, total_tables: int,
        tables: [ { table_id, page, caption, headers[], rows[][], markdown,
                    context_before, context_after } ] }
    """
    path = Path(vault_root) / "sources" / slug / "_tables.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def read_tables_json(vault_root: str | Path, slug: str) -> Optional[Dict[str, Any]]:
    """Read the cached tables JSON. Returns None if not yet extracted."""
    path = Path(vault_root) / "sources" / slug / "_tables.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return _json.load(f)


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
    """Write sources/{slug}/tables/table-{id}-{caption}.md — one note per table."""
    caption_slug = make_slug(caption) if caption else "table"
    filename = f"table-{table_id}-{caption_slug}.md"

    metadata = {
        "type": "table-note",
        "source": f"[[sources/{slug}/_index]]",
        "table_id": table_id,
        "page": page,
        "caption": caption,
        "headers": headers,
        "rows_count": len(rows),
        "has_structured_data": True,
        "pipeline_stage": "indexed",
    }
    if ibc_table_type:
        metadata["ibc_table_type"] = ibc_table_type
    if doc_meta:
        for k, v in doc_meta.items():
            if v:
                metadata[k] = v

    body = ""
    if context_before:
        body += f"**Context:** {context_before.strip()}\n\n"
    body += markdown
    if context_after:
        body += f"\n\n*{context_after.strip()}*"
    body += f"\n\n*Source: Page {page}*"

    return write_note(vault_root, f"sources/{slug}/tables/{filename}", metadata, body)


def read_all_tables(vault_root: str | Path, slug: str) -> List["VaultNote"]:
    """Read all table notes for a source document."""
    tables_dir = Path(vault_root) / "sources" / slug / "tables"
    if not tables_dir.exists():
        return []
    notes = []
    for f in sorted(tables_dir.glob("table-*.md")):
        post = _fm_load(f)
        notes.append(VaultNote(path=f, metadata=dict(post.metadata), body=post.content))
    return notes


def write_akn_json(vault_root: str | Path, slug: str, data: Dict[str, Any]) -> Path:
    """Write AKN-lite annotation as JSON alongside _parse.json."""
    path = Path(vault_root) / "sources" / slug / "_akn.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def read_akn_json(vault_root: str | Path, slug: str) -> Optional[Dict[str, Any]]:
    """Read the AKN-lite annotation. Returns None if stage_akn hasn't run."""
    path = Path(vault_root) / "sources" / slug / "_akn.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return _json.load(f)


def _fm_load(path: Path):
    """Lazy import of frontmatter.load to avoid circular import."""
    import frontmatter
    return frontmatter.load(path)


# ──────────────────────────────────────────────────────────────
# Generic sidecar JSON — _timeline.json, _obligations.json, etc.
# ──────────────────────────────────────────────────────────────

def write_sidecar_json(vault_root: str | Path, slug: str, filename: str, data: Dict[str, Any]) -> Path:
    """Write any sidecar JSON file under sources/{slug}/{filename}.

    Used for _timeline.json, _obligations.json, _entities.json, _citations.json.
    """
    path = Path(vault_root) / "sources" / slug / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def read_sidecar_json(vault_root: str | Path, slug: str, filename: str) -> Optional[Dict[str, Any]]:
    """Read a sidecar JSON file. Returns None if not yet produced."""
    path = Path(vault_root) / "sources" / slug / filename
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return _json.load(f)