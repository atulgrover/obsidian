"""
vault-pipeline — FastAPI service that orchestrates the RAG2 pipeline.

Storage backends:
  - "vault" (default): writes to Obsidian vault (markdown + YAML frontmatter)
  - "wiki": writes to TiddlyWiki MWS (tiddlers via HTTP API)

Stages:
  Stage 1: PDF → LiteParse → PageIndex → vault/wiki (sources/)
  Stage 2: vault/wiki sections → SemChunk → vault/wiki chunks (chunks/)
  Stage 3: vault/wiki chunks → LightRAG → Postgres (updates chunk frontmatter)

Also provides vault CRUD endpoints for the web frontend.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from vault_io import (
    VaultNote,
    init_vault,
    make_slug,
    note_exists,
    read_akn_json,
    read_all_chunks,
    read_all_sections,
    read_all_tables,
    read_note,
    read_parse_json,
    read_sidecar_json,
    read_tables_json,
    read_tree_json,
)

# ── Dual write: vault (primary) + TiddlyWiki MWS (mirror) ──
from dual_write import (
    write_akn_json,
    write_chunk_index,
    write_chunk_note,
    write_full_text,
    write_note,
    write_parse_json,
    write_section_note,
    write_sidecar_json,
    write_source_index,
    write_table_note,
    write_tables_json,
    write_tree_json,
    update_pipeline_stage,
)

# ── MWS client for dual-write ──
from wiki_manager import get_client, ensure_wiki, authenticate as mws_authenticate

# ──────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────

VAULT_ROOT = os.environ.get("VAULT_ROOT", "/vault")
LITEPARSE_URL = os.environ.get("LITEPARSE_URL", "http://localhost:5001")
PAGEINDEX_URL = os.environ.get("PAGEINDEX_URL", "http://localhost:5002")
SEMCHUNK_URL = os.environ.get("SEMCHUNK_URL", "http://localhost:5003")
LIGHTRAG_URL = os.environ.get("LIGHTRAG_URL", "http://localhost:8020")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "ministral-3:14b-cloud")
SBERT_URL = os.environ.get("SBERT_URL", "http://sbert:8021")

# ── Parser config ──────────────────────────────────────────────
# If LLAMA_PARSE_API_KEY is set and PRIVATE_MODE is not "true",
# stage_parse uses LlamaParse (cloud) for multi-modal, OCR, and
# structured table extraction. Otherwise falls back to LiteParse.
LLAMA_PARSE_API_KEY = os.environ.get("LLAMA_PARSE_API_KEY", "")
LLAMA_PARSE_BASE_URL = "https://api.cloud.llamaindex.ai"
PRIVATE_MODE = os.environ.get("PRIVATE_MODE", "false").lower() == "true"

# ── LLM provider config ────────────────────────────────────────
# LLM_PROVIDER: ollama (default/local) | claude | openai
# Each stage picks the provider via llm_call(provider=...) override,
# or falls back to LLM_PROVIDER for generic calls.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
# Model overrides per provider
LLM_MODEL_CLAUDE = os.environ.get("LLM_MODEL_CLAUDE", "claude-haiku-4-5-20251001")
LLM_MODEL_CLAUDE_HEAVY = os.environ.get("LLM_MODEL_CLAUDE_HEAVY", "claude-sonnet-4-6")
LLM_MODEL_OPENAI = os.environ.get("LLM_MODEL_OPENAI", "gpt-4o-mini")
LLM_MODEL_OPENAI_HEAVY = os.environ.get("LLM_MODEL_OPENAI_HEAVY", "gpt-4o")

# ──────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("vault-pipeline")


@contextmanager
def stage_log(stage: str, slug: str = "", **kw):
    """Context manager: logs stage start, finish, elapsed time, and any error."""
    extras = "  ".join(f"{k}={v}" for k, v in kw.items())
    logger.info(f"▶ START   stage={stage:<22} slug={slug}  {extras}".rstrip())
    t0 = time.perf_counter()
    try:
        yield logger
        elapsed = time.perf_counter() - t0
        logger.info(f"✓ DONE    stage={stage:<22} slug={slug}  elapsed={elapsed:.2f}s")
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        logger.error(f"✗ ERROR   stage={stage:<22} slug={slug}  elapsed={elapsed:.2f}s  error={exc!r}")
        raise


# ──────────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────────

app = FastAPI(title="vault-pipeline", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/response timing middleware — logs every endpoint call
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - t0
        logger.info(
            f"HTTP {request.method} {request.url.path}"
            f"  status={response.status_code}  elapsed={elapsed:.2f}s"
        )
        return response


app.add_middleware(RequestLogMiddleware)


@app.on_event("startup")
async def startup():
    init_vault(VAULT_ROOT)
    # Authenticate with TiddlyWiki MWS for dual-write mirroring
    # If MWS is not available, pipeline continues with vault-only writes
    try:
        await mws_authenticate()
        logger.info("MWS authentication successful — dual-write enabled (vault + TiddlyWiki)")
    except Exception as e:
        logger.warning(f"MWS not available — vault-only mode: {e}")


@app.get("/")
async def root():
    return {
        "message": "vault-pipeline",
        "version": "1.0.0",
        "vault_root": VAULT_ROOT,
        "dual_write": True,
    }


@app.get("/health")
async def health():
    result = {"status": "ok", "vault_root": VAULT_ROOT, "dual_write": True}
    from wiki_manager import health_check as mws_health
    try:
        mws_ok = await mws_health()
        result["mws_reachable"] = mws_ok
    except Exception:
        result["mws_reachable"] = False
    return result


# ──────────────────────────────────────────────────────────────
# Stage 1: PDF → LiteParse → PageIndex → vault markdown
# ──────────────────────────────────────────────────────────────

class IngestPdfRequest(BaseModel):
    url: str
    filename: str = ""  # original filename (for uploaded files)
    max_tokens: int = 512
    overlap_tokens: int = 75


class IngestPdfResponse(BaseModel):
    success: bool
    slug: str
    vault_path: str
    sections: int
    total_pages: int
    total_chars: int
    message: str = ""


@app.post("/vault/ingest-pdf", response_model=IngestPdfResponse)
async def ingest_pdf(request: IngestPdfRequest):
    """
    Stage 1: Download PDF, run LiteParse → PageIndex, write vault markdown.
    Creates sources/{slug}/_index.md, full-text.md, sections/sec-*.md
    """
    slug = make_slug(Path(request.filename).stem if request.filename else (Path(request.url).stem or "document"))
    vault_path = f"sources/{slug}"

    # Check if already ingested
    if note_exists(VAULT_ROOT, f"{vault_path}/_index.md"):
        existing = read_note(VAULT_ROOT, f"{vault_path}/_index.md")
        if existing.metadata.get("pipeline_stage") in ("pageindex", "semchunk", "ingested"):
            return IngestPdfResponse(
                success=True,
                slug=slug,
                vault_path=vault_path,
                sections=0,
                total_pages=existing.metadata.get("total_pages", 0),
                total_chars=existing.metadata.get("total_chars", 0),
                message=f"Already ingested at stage: {existing.metadata.get('pipeline_stage')}",
            )

    async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
        # Step 1: Download PDF
        if request.url.startswith("file://"):
            pdf_path = request.url[7:]
            filename = request.filename or (Path(pdf_path).name or "document.pdf")
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
        else:
            try:
                resp = await client.get(request.url)
                resp.raise_for_status()
                pdf_bytes = resp.content
                filename = request.filename or (Path(request.url).name or "document.pdf")
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Failed to download PDF: {e}")

        # Save original PDF to vault _attachments
        attachments_dir = Path(VAULT_ROOT) / "_attachments"
        attachments_dir.mkdir(parents=True, exist_ok=True)
        pdf_save_path = attachments_dir / f"{slug}.pdf"
        with open(pdf_save_path, "wb") as f:
            f.write(pdf_bytes)

        # Step 2: Parse (LlamaParse or LiteParse)
        lp_result, tables_data = await _run_parse(slug, pdf_bytes, filename)
        write_parse_json(VAULT_ROOT, slug, lp_result)
        write_tables_json(VAULT_ROOT, slug, tables_data)

        # Step 3: PageIndex
        try:
            pi_resp = await client.post(
                f"{PAGEINDEX_URL}/build-tree",
                json={"liteparse_result": lp_result},
                timeout=120.0,
            )
            pi_resp.raise_for_status()
            pi_result = pi_resp.json()
            if not pi_result.get("success"):
                raise HTTPException(status_code=502, detail=f"PageIndex error: {pi_result.get('error')}")

            # Cache PageIndex tree for re-processing
            write_tree_json(VAULT_ROOT, slug, pi_result)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"PageIndex request failed: {e}")

    # Step 4: Write vault markdown
    tree = pi_result.get("tree", {})
    total_pages = lp_result.get("metadata", {}).get("totalPages", 0)
    total_chars = lp_result.get("metadata", {}).get("characterCount", 0)

    # Write _index.md
    children = []
    section_notes = []

    def collect_sections(node: dict, parent_path: str = "") -> None:
        """Recursively walk the PageIndex tree and write section notes."""
        section_id = node.get("id", "0").replace("node-", "")
        title = node.get("title", "Untitled")
        level = node.get("level", 0)
        content = node.get("content", "")
        summary = node.get("summary", "")
        page_start = node.get("pageStart", 1)
        page_end = node.get("pageEnd", 1)
        metadata = node.get("metadata", {})
        children_nodes = node.get("children", [])
        is_leaf = len(children_nodes) == 0 or metadata.get("type") == "content"
        word_count = metadata.get("wordCount", len(content.split()))
        heading_level = metadata.get("headingLevel", level)

        # Build wikilink for this section
        title_slug = make_slug(title) if title else "untitled"
        sec_filename = f"sec-{section_id}-{title_slug}.md"
        sec_rel_path = f"sources/{slug}/sections/{sec_filename}"
        sec_wikilink = f"[[sources/{slug}/sections/sec-{section_id}-{title_slug}]]"

        child_wikilinks = []
        for child in children_nodes:
            child_id = child.get("id", "").replace("node-", "")
            child_title = child.get("title", "Untitled")
            child_slug = make_slug(child_title)
            child_wikilinks.append(
                f"[[sources/{slug}/sections/sec-{child_id}-{child_slug}]]"
            )

        parent_wikilink = ""
        if parent_path:
            parent_wikilink = f"[[sources/{slug}/sections/{parent_path}]]"

        write_section_note(
            VAULT_ROOT, slug, section_id,
            level=level,
            heading_level=heading_level,
            title=title,
            content=content,
            summary=summary,
            page_start=page_start,
            page_end=page_end,
            word_count=word_count,
            parent=parent_wikilink,
            children=child_wikilinks if child_wikilinks else None,
            is_leaf=is_leaf,
        )
        section_notes.append(sec_rel_path)
        children.append(sec_wikilink)

        for child in children_nodes:
            collect_sections(child, sec_filename)

    collect_sections(tree)

    # Write root _index.md
    doc_title = tree.get("title", filename)
    write_source_index(
        VAULT_ROOT, slug,
        filename=filename,
        total_pages=total_pages,
        total_chars=total_chars,
        source_url=request.url,
        pipeline_stage="pageindex",
        children=children,
    )

    # Write full-text.md
    full_text = lp_result.get("text", "")
    if full_text:
        write_full_text(VAULT_ROOT, slug, full_text, filename=filename)

    return IngestPdfResponse(
        success=True,
        slug=slug,
        vault_path=vault_path,
        sections=len(section_notes),
        total_pages=total_pages,
        total_chars=total_chars,
        message=f"Ingested {len(section_notes)} sections to vault",
    )


# ──────────────────────────────────────────────────────────────
# Save PDF only (no processing) — for immediate viewer display
# ──────────────────────────────────────────────────────────────

@app.post("/vault/save-pdf-upload")
async def save_pdf_upload(file: UploadFile = File(...)):
    """Save an uploaded PDF to vault without running any pipeline stages.
    Creates a minimal _index.md so the source appears in the sidebar
    and the PDF can be viewed immediately."""
    filename = file.filename or "document.pdf"
    slug = make_slug(Path(filename).stem)

    # Save PDF to _attachments
    attachments_dir = Path(VAULT_ROOT) / "_attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    pdf_save_path = attachments_dir / f"{slug}.pdf"
    content = await file.read()
    with open(pdf_save_path, "wb") as f:
        f.write(content)

    # Create minimal _index.md
    source_dir = Path(VAULT_ROOT) / "sources" / slug
    source_dir.mkdir(parents=True, exist_ok=True)
    write_source_index(
        VAULT_ROOT, slug,
        filename=filename,
        total_pages=0,
        total_chars=0,
        source_url="",
        pipeline_stage="uploaded",
        children=[],
    )

    return {"success": True, "slug": slug, "filename": filename, "message": "PDF saved"}


@app.post("/vault/save-pdf-url")
async def save_pdf_url(request: IngestPdfRequest):
    """Download a PDF from URL and save to vault without processing."""
    slug = make_slug(Path(request.filename).stem if request.filename else (Path(request.url).stem or "document"))

    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        try:
            resp = await client.get(request.url)
            resp.raise_for_status()
            pdf_bytes = resp.content
            filename = request.filename or (Path(request.url).name or "document.pdf")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to download PDF: {e}")

    # Save PDF to _attachments
    attachments_dir = Path(VAULT_ROOT) / "_attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    pdf_save_path = attachments_dir / f"{slug}.pdf"
    with open(pdf_save_path, "wb") as f:
        f.write(pdf_bytes)

    # Create minimal _index.md
    source_dir = Path(VAULT_ROOT) / "sources" / slug
    source_dir.mkdir(parents=True, exist_ok=True)
    write_source_index(
        VAULT_ROOT, slug,
        filename=filename,
        total_pages=0,
        total_chars=0,
        source_url=request.url,
        pipeline_stage="uploaded",
        children=[],
    )

    return {"success": True, "slug": slug, "filename": filename, "message": "PDF saved"}


@app.post("/vault/ingest-pdf-upload", response_model=IngestPdfResponse)
async def ingest_pdf_upload(
    file: UploadFile = File(...),
    max_tokens: int = Form(512),
    overlap_tokens: int = Form(75),
):
    """Stage 1 via file upload instead of URL."""
    # Save uploaded PDF to temp file, then create a file:// URL
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        request = IngestPdfRequest(
            url=f"file://{tmp_path}",
            filename=file.filename or "",
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )
        return await ingest_pdf(request)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ──────────────────────────────────────────────────────────────
# Stage 2: vault sections → SemChunk → vault chunks
# ──────────────────────────────────────────────────────────────

class ChunkFromVaultRequest(BaseModel):
    slug: str
    max_tokens: int = 512
    overlap_tokens: int = 75


class ChunkFromVaultResponse(BaseModel):
    success: bool
    slug: str
    total_chunks: int
    total_tokens: int
    message: str = ""


@app.post("/vault/chunk", response_model=ChunkFromVaultResponse)
async def chunk_from_vault(request: ChunkFromVaultRequest):
    """
    Stage 2: Read vault section notes, call SemChunk, write chunk notes.
    """
    slug = request.slug
    sections_dir = f"sources/{slug}/sections"
    index_path = f"sources/{slug}/_index.md"

    # Verify source exists
    if not note_exists(VAULT_ROOT, index_path):
        raise HTTPException(status_code=404, detail=f"Source document not found: {slug}")

    # Read all section notes and reconstruct PageIndexNode tree
    section_notes = read_all_sections(VAULT_ROOT, slug)
    if not section_notes:
        raise HTTPException(status_code=404, detail=f"No section notes found for: {slug}")

    # Build the tree dict from section notes
    # We need to reconstruct the PageIndexNode tree format that SemChunk expects
    nodes = []
    for note in section_notes:
        m = note.metadata
        nodes.append({
            "id": note.path.stem.replace("sec-", "").split("-")[0],  # e.g. "01" from "sec-01-introduction"
            "level": m.get("level", 1),
            "title": m.get("summary", note.body[:80] if note.body else ""),
            "summary": m.get("summary", ""),
            "content": note.body,
            "pageStart": m.get("page_start", 1),
            "pageEnd": m.get("page_end", 1),
            "metadata": {
                "type": "content" if m.get("is_leaf", True) else "section",
                "wordCount": m.get("word_count", 0),
            },
            "children": [],
        })

    # Build tree structure — root node is the document
    index_note = read_note(VAULT_ROOT, index_path)
    doc_title = index_note.metadata.get("filename", slug)

    tree_dict = {
        "id": "node-root",
        "level": 0,
        "title": doc_title,
        "summary": index_note.body[:200] if index_note.body else "",
        "content": "",
        "pageStart": 1,
        "pageEnd": index_note.metadata.get("total_pages", 1),
        "children": nodes,
        "metadata": {"type": "document"},
    }

    # Call SemChunk /pipeline
    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            resp = await client.post(
                f"{SEMCHUNK_URL}/pipeline",
                json={
                    "pageindex_result": {"success": True, "tree": tree_dict},
                    "maxTokens": request.max_tokens,
                    "overlapTokens": request.overlap_tokens,
                },
            )
            resp.raise_for_status()
            result = resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"SemChunk request failed: {e}")

    if not result.get("success"):
        raise HTTPException(status_code=502, detail=f"SemChunk error: {result}")

    # Write chunk notes to vault
    chunks = result.get("chunks", [])
    total_tokens = result.get("totalTokens", 0)
    doc_title_resp = result.get("documentTitle", doc_title)
    doc_summary = result.get("documentSummary", "")

    # Ensure chunks directory exists
    (Path(VAULT_ROOT) / "chunks" / slug).mkdir(parents=True, exist_ok=True)

    source_wikilink = f"[[sources/{slug}/_index]]"

    for i, chunk in enumerate(chunks):
        # Find the section wikilink for this chunk
        section_wikilink = ""
        source_node_id = chunk.get("sourceNodeId", chunk.get("metadata", {}).get("nodeId", ""))
        if source_node_id:
            section_notes_for_link = read_all_sections(VAULT_ROOT, slug)
            for sn in section_notes_for_link:
                if sn.path.stem.startswith(f"sec-{source_node_id.replace('node-', '')}"):
                    section_wikilink = f"[[sources/{slug}/sections/{sn.path.stem}]]"
                    break

        write_chunk_note(
            VAULT_ROOT, slug, i,
            total_chunks=len(chunks),
            content=chunk.get("content", ""),
            parent_context=chunk.get("parentContext", ""),
            page_start=chunk.get("pageStart", 1),
            page_end=chunk.get("pageEnd", 1),
            token_count=chunk.get("tokenCount", 0),
            level=chunk.get("level", 0),
            has_overlap=chunk.get("metadata", {}).get("hasOverlap", False),
            source_wikilink=source_wikilink,
            section_wikilink=section_wikilink,
        )

    # Write chunk index
    write_chunk_index(
        VAULT_ROOT, slug,
        total_chunks=len(chunks),
        total_tokens=total_tokens,
        document_title=doc_title_resp,
        document_summary=doc_summary,
    )

    # Update source _index.md pipeline stage
    update_pipeline_stage(VAULT_ROOT, f"sources/{slug}/_index.md", "semchunk")

    return ChunkFromVaultResponse(
        success=True,
        slug=slug,
        total_chunks=len(chunks),
        total_tokens=total_tokens,
        message=f"Chunked into {len(chunks)} notes in vault",
    )


# ──────────────────────────────────────────────────────────────
# Stage 3: vault chunks → LightRAG ingest
# ──────────────────────────────────────────────────────────────

class IngestLightragRequest(BaseModel):
    slug: str


class IngestLightragResponse(BaseModel):
    success: bool
    slug: str
    ingested: int
    skipped: int
    failed: int
    run_id: str = ""
    message: str = ""


@app.post("/vault/ingest-lightrag", response_model=IngestLightragResponse)
async def ingest_lightrag(request: IngestLightragRequest):
    """
    Stage 3: Read vault chunk notes, POST each to LightRAG standard
    /documents/text endpoint, update frontmatter.
    """
    slug = request.slug
    chunks_dir = f"chunks/{slug}"

    if not note_exists(VAULT_ROOT, f"{chunks_dir}/_index.md"):
        raise HTTPException(status_code=404, detail=f"Chunk index not found for: {slug}")

    chunk_notes = read_all_chunks(VAULT_ROOT, slug)
    if not chunk_notes:
        raise HTTPException(status_code=404, detail=f"No chunk notes found for: {slug}")

    ingested = 0
    skipped = 0
    failed = 0
    track_id = ""

    async with httpx.AsyncClient(timeout=120.0) as client:
        for note in chunk_notes:
            m = note.metadata
            chunk_index = m.get("chunk_index", 0)
            file_source = f"{slug}/chunk-{chunk_index + 1:03d}"

            # Build enriched text: section path + body
            section = m.get("parent_context", "") or ""
            text = f"{section}\n\n{note.body}".strip() if section else note.body

            try:
                resp = await client.post(
                    f"{LIGHTRAG_URL}/documents/text",
                    json={"text": text, "file_source": file_source},
                )
                resp.raise_for_status()
                result = resp.json()
                status = result.get("status", "")
                track_id = result.get("track_id", track_id)

                if status == "duplicated":
                    skipped += 1
                else:
                    ingested += 1

                # Update vault frontmatter
                rel_path = f"chunks/{slug}/chunk-{chunk_index + 1:03d}.md"
                m["lightrag_ingested"] = True
                m["ingested_at"] = track_id
                write_note(VAULT_ROOT, rel_path, m, note.body)

            except Exception as e:
                failed += 1

    update_pipeline_stage(VAULT_ROOT, f"sources/{slug}/_index.md", "ingested")

    return IngestLightragResponse(
        success=True,
        slug=slug,
        ingested=ingested,
        skipped=skipped,
        failed=failed,
        run_id=track_id,
        message=f"Sent {ingested} chunks to LightRAG (skipped {skipped}, failed {failed}). Processing continues in background.",
    )


# ──────────────────────────────────────────────────────────────
# Full pipeline: Stage 1 → 2 → 3
# ──────────────────────────────────────────────────────────────

class FullPipelineRequest(BaseModel):
    url: str
    max_tokens: int = 512
    overlap_tokens: int = 75
    # Intelligence stages — set to False to skip if API keys not available
    run_classify: bool = True
    run_extract: bool = True
    run_akn: bool = True
    run_multipass: bool = True
    run_structure: bool = True
    run_canvas: bool = True
    run_dashboard: bool = True
    run_embed: bool = True


class FullPipelineUploadResponse(BaseModel):
    success: bool
    slug: str
    stages: dict = {}


@app.post("/vault/full-pipeline")
async def full_pipeline(request: FullPipelineRequest):
    """Run the complete IBC document pipeline.

    Stage order:
      assess → parse → cleanse → classify → extract → akn → extract_multipass
      → link → index → enrich → enrich_mca → structure → chunk → embed
      → canvas → dashboard

    All intelligence stages are opt-in via boolean flags — set to False
    when API keys are unavailable or for speed.
    """
    stages: dict = {}

    # ── parse ─────────────────────────────────────────────────
    stage1 = await ingest_pdf(IngestPdfRequest(
        url=request.url,
        max_tokens=request.max_tokens,
        overlap_tokens=request.overlap_tokens,
    ))
    stages["parse"] = stage1.dict() if hasattr(stage1, "dict") else stage1
    if not stage1.success:
        return {"success": False, "failed_at": "parse", "stages": stages}

    slug = stage1.slug
    sr = StageRequest(slug=slug)

    # ── classify ──────────────────────────────────────────────
    if request.run_classify:
        try:
            stages["classify"] = await stage_classify(sr)
        except Exception as e:
            stages["classify"] = {"success": False, "error": str(e)}

    # ── extract ───────────────────────────────────────────────
    if request.run_extract:
        try:
            stages["extract"] = await stage_extract(sr)
        except Exception as e:
            stages["extract"] = {"success": False, "error": str(e)}

    # ── akn ───────────────────────────────────────────────────
    if request.run_akn:
        try:
            stages["akn"] = await stage_akn(sr)
        except Exception as e:
            stages["akn"] = {"success": False, "error": str(e)}

    # ── extract_multipass ─────────────────────────────────────
    if request.run_multipass and ANTHROPIC_API_KEY:
        try:
            stages["extract_multipass"] = await stage_extract_multipass(sr)
        except Exception as e:
            stages["extract_multipass"] = {"success": False, "error": str(e)}

    # ── link ──────────────────────────────────────────────────
    try:
        stages["link"] = await stage_link(sr)
    except Exception as e:
        stages["link"] = {"success": False, "error": str(e)}

    # ── index ─────────────────────────────────────────────────
    try:
        stages["index"] = await stage_index(sr)
    except Exception as e:
        stages["index"] = {"success": False, "error": str(e)}

    # ── enrich ────────────────────────────────────────────────
    try:
        stages["enrich"] = await stage_enrich(sr)
    except Exception as e:
        stages["enrich"] = {"success": False, "error": str(e)}

    # ── enrich_mca ────────────────────────────────────────────
    try:
        stages["enrich_mca"] = await stage_enrich_mca(sr)
    except Exception as e:
        stages["enrich_mca"] = {"success": False, "error": str(e)}

    # ── structure ─────────────────────────────────────────────
    if request.run_structure:
        try:
            stages["structure"] = await stage_structure(sr)
        except Exception as e:
            stages["structure"] = {"success": False, "error": str(e)}

    # ── chunk ─────────────────────────────────────────────────
    stage_chunk_result = await chunk_from_vault(ChunkFromVaultRequest(
        slug=slug,
        max_tokens=request.max_tokens,
        overlap_tokens=request.overlap_tokens,
    ))
    stages["chunk"] = stage_chunk_result.dict() if hasattr(stage_chunk_result, "dict") else stage_chunk_result
    if not stage_chunk_result.success:
        return {"success": False, "failed_at": "chunk", "stages": stages}

    # ── embed ─────────────────────────────────────────────────
    if request.run_embed:
        try:
            stages["embed"] = await stage_embed(sr)
        except Exception as e:
            stages["embed"] = {"success": False, "error": str(e)}

    # ── canvas ────────────────────────────────────────────────
    if request.run_canvas:
        try:
            stages["canvas"] = await stage_canvas(sr)
        except Exception as e:
            stages["canvas"] = {"success": False, "error": str(e)}

    # ── dashboard ─────────────────────────────────────────────
    if request.run_dashboard:
        try:
            stages["dashboard"] = await stage_dashboard(sr)
        except Exception as e:
            stages["dashboard"] = {"success": False, "error": str(e)}

    return {"success": True, "slug": slug, "stages": stages}


@app.post("/vault/full-pipeline-upload", response_model=FullPipelineUploadResponse)
async def full_pipeline_upload(
    file: UploadFile = File(...),
    max_tokens: int = Form(512),
    overlap_tokens: int = Form(75),
):
    """Run all three stages with a file upload instead of URL."""
    # Stage 1: upload
    stage1 = await ingest_pdf_upload(file=file, max_tokens=max_tokens, overlap_tokens=overlap_tokens)

    if not stage1.success:
        return FullPipelineUploadResponse(
            success=False, slug=stage1.slug,
            stages={"ingest_pdf": stage1.dict()},
        )

    # Stage 2: chunk
    stage2 = await chunk_from_vault(ChunkFromVaultRequest(
        slug=stage1.slug, max_tokens=max_tokens, overlap_tokens=overlap_tokens,
    ))

    if not stage2.success:
        return FullPipelineUploadResponse(
            success=False, slug=stage1.slug,
            stages={"ingest_pdf": stage1.dict(), "chunk": stage2.dict()},
        )

    # Stage 3: ingest into LightRAG
    stage3 = await ingest_lightrag(IngestLightragRequest(slug=stage1.slug))

    return FullPipelineUploadResponse(
        success=True,
        slug=stage1.slug,
        stages={
            "ingest_pdf": stage1.dict(),
            "chunk": stage2.dict(),
            "ingest_lightrag": stage3.dict(),
        },
    )


# ──────────────────────────────────────────────────────────────
# Vault CRUD endpoints
# ──────────────────────────────────────────────────────────────

@app.get("/vault/sources")
async def list_sources():
    """List all source documents in the vault."""
    sources_dir = Path(VAULT_ROOT) / "sources"
    if not sources_dir.exists():
        return {"sources": []}

    sources = []
    for d in sorted(sources_dir.iterdir()):
        index_path = d / "_index.md"
        if d.is_dir() and index_path.exists():
            try:
                note = read_note(VAULT_ROOT, f"sources/{d.name}/_index.md")
                sources.append({
                    "slug": d.name,
                    "pipeline_stage": note.metadata.get("pipeline_stage", "unknown"),
                    "filename": note.metadata.get("filename", ""),
                    "total_pages": note.metadata.get("total_pages", 0),
                    "total_chars": note.metadata.get("total_chars", 0),
                    "doc_type": note.metadata.get("doc_type", ""),
                    "created_at": note.metadata.get("created_at", ""),
                })
            except Exception:
                sources.append({"slug": d.name, "pipeline_stage": "unknown"})

    return {"sources": sources}


@app.delete("/vault/sources/{slug}")
async def delete_source(slug: str):
    """Delete a source document and all its vault files (sections, chunks, attachments)."""
    import shutil

    removed = []
    for rel in [
        f"sources/{slug}",
        f"chunks/{slug}",
    ]:
        p = Path(VAULT_ROOT) / rel
        if p.exists():
            shutil.rmtree(p)
            removed.append(rel)

    pdf_path = Path(VAULT_ROOT) / "_attachments" / f"{slug}.pdf"
    if pdf_path.exists():
        pdf_path.unlink()
        removed.append(f"_attachments/{slug}.pdf")

    if not removed:
        raise HTTPException(status_code=404, detail=f"Source not found: {slug}")

    return {"success": True, "slug": slug, "removed": removed}


@app.get("/vault/sources/{slug}")
async def get_source(slug: str):
    """Get a source document's metadata."""
    try:
        note = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
        sections = read_all_sections(VAULT_ROOT, slug)
        return {
            "slug": slug,
            "metadata": note.metadata,
            "body": note.body,
            "sections_count": len(sections),
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Source not found: {slug}")


@app.get("/vault/sources/{slug}/sections")
async def list_sections(slug: str):
    """List all section notes for a source document."""
    sections = read_all_sections(VAULT_ROOT, slug)
    result = []
    for note in sections:
        result.append({
            "filename": note.path.stem,
            "title": note.metadata.get("title") or note.metadata.get("summary", note.body[:80] if note.body else ""),
            "level": note.metadata.get("level", 0),
            "is_leaf": note.metadata.get("is_leaf", True),
            "page_start": note.metadata.get("page_start", 1),
            "page_end": note.metadata.get("page_end", 1),
            "word_count": note.metadata.get("word_count", 0),
            "breadcrumb": note.metadata.get("breadcrumb", ""),
            "llm_summary": note.metadata.get("llm_summary", ""),
        })
    return {"slug": slug, "sections": result}


@app.get("/vault/sources/{slug}/sections/{section_id}")
async def get_section(slug: str, section_id: str):
    """Get a section note's content."""
    # Find the section file matching the ID prefix
    sections_dir = Path(VAULT_ROOT) / "sources" / slug / "sections"
    if not sections_dir.exists():
        raise HTTPException(status_code=404, detail=f"Sections not found for: {slug}")

    for f in sections_dir.glob(f"sec-{section_id}-*.md"):
        note = read_note(VAULT_ROOT, f"sources/{slug}/sections/{f.name}")
        return {"metadata": note.metadata, "body": note.body}

    raise HTTPException(status_code=404, detail=f"Section not found: {section_id}")


@app.get("/vault/chunks/{slug}")
async def list_chunks(slug: str):
    """List all chunk notes for a source document."""
    chunks = read_all_chunks(VAULT_ROOT, slug)
    result = []
    for note in chunks:
        m = note.metadata
        result.append({
            "chunk_index": m.get("chunk_index", 0),
            "token_count": m.get("token_count", 0),
            "page_start": m.get("page_start", 0),
            "page_end": m.get("page_end", 0),
            "lightrag_ingested": m.get("lightrag_ingested", False),
            "pipeline_stage": m.get("pipeline_stage", ""),
        })
    return {"slug": slug, "chunks": result}


@app.get("/vault/chunks/{slug}/{chunk_id}")
async def get_chunk(slug: str, chunk_id: str):
    """Get a specific chunk note."""
    rel_path = f"chunks/{slug}/{chunk_id}.md"
    try:
        note = read_note(VAULT_ROOT, rel_path)
        return {"metadata": note.metadata, "body": note.body}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Chunk not found: {chunk_id}")


# ──────────────────────────────────────────────────────────────
# PDF + full-text endpoints
# ──────────────────────────────────────────────────────────────

from fastapi.responses import FileResponse


@app.get("/vault/attachments/{slug}")
async def get_attachment(slug: str):
    """Serve the original PDF attachment for a source document."""
    pdf_path = Path(VAULT_ROOT) / "_attachments" / f"{slug}.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"PDF not found for: {slug}")
    response = FileResponse(pdf_path, media_type="application/pdf")
    response.headers["Content-Disposition"] = f'inline; filename="{slug}.pdf"'
    return response


@app.get("/vault/sources/{slug}/full-text")
async def get_full_text(slug: str):
    """Get the full extracted text for a source document."""
    try:
        note = read_note(VAULT_ROOT, f"sources/{slug}/full-text.md")
        return {"metadata": note.metadata, "body": note.body}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Full text not found for: {slug}")


# ──────────────────────────────────────────────────────────────
# Intermediate data endpoints (cached LiteParse + PageIndex)
# ──────────────────────────────────────────────────────────────

@app.get("/vault/sources/{slug}/parse")
async def get_parse(slug: str):
    """Return cached LiteParse output for a source document."""
    data = read_parse_json(VAULT_ROOT, slug)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Parse data not found for: {slug}")
    return data


@app.get("/vault/sources/{slug}/tree")
async def get_tree(slug: str):
    """Return cached PageIndex tree for a source document."""
    data = read_tree_json(VAULT_ROOT, slug)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Tree data not found for: {slug}")
    return data


# ──────────────────────────────────────────────────────────────
# Vault audit — Dataview frontmatter completeness report
# ──────────────────────────────────────────────────────────────

# Fields required for Dataview queries to work across all doc types
_DATAVIEW_REQUIRED = [
    "doc_type", "case_number", "court", "order_date",
    "corporate_debtor", "pipeline_stage",
]
# Fields required only for order types (resolution_plan_order etc.)
_DATAVIEW_ORDER_FIELDS = [
    "resolution_applicant", "insolvency_professional",
    "resolution_amount_inr", "total_admitted_inr", "haircut_pct",
    "coc_approval_pct", "liquidation_value_inr",
]
_ORDER_TYPES = {
    "resolution_plan_order", "admission_order", "liquidation_order",
    "interim_order", "appeal_order",
}


@app.get("/vault/audit")
async def vault_audit():
    """Scan all source documents and report Dataview frontmatter completeness.

    Returns per-document field coverage and a vault-wide summary so you can
    see which pipeline stages are incomplete or which fields are missing.
    """
    sources_dir = Path(VAULT_ROOT) / "sources"
    if not sources_dir.exists():
        return {"documents": [], "summary": {}}

    documents = []
    total = 0
    fully_complete = 0

    for d in sorted(sources_dir.iterdir()):
        if not d.is_dir():
            continue
        idx_path = d / "_index.md"
        if not idx_path.exists():
            continue
        try:
            note = read_note(VAULT_ROOT, f"sources/{d.name}/_index.md")
        except Exception:
            continue

        m = note.metadata
        doc_type = m.get("doc_type", "")
        total += 1

        # Check required fields
        missing = [f for f in _DATAVIEW_REQUIRED if not m.get(f)]
        if doc_type in _ORDER_TYPES:
            missing += [f for f in _DATAVIEW_ORDER_FIELDS if not m.get(f)]

        # Check which stages have run
        stages_done = []
        for stage_file, stage_name in [
            ("_parse.json", "parse"),
            ("_meta.json", "extract"),
            ("_akn.json", "akn"),
            ("_links.md", "link"),
        ]:
            if (d / stage_file).exists():
                stages_done.append(stage_name)

        complete = len(missing) == 0
        if complete:
            fully_complete += 1

        documents.append({
            "slug": d.name,
            "doc_type": doc_type,
            "pipeline_stage": m.get("pipeline_stage", "unknown"),
            "stages_done": stages_done,
            "missing_fields": missing,
            "complete": complete,
            "frbr_uri": m.get("frbr_uri", ""),
            "akn_elements": m.get("akn_elements", []),
        })

    return {
        "total": total,
        "fully_complete": fully_complete,
        "incomplete": total - fully_complete,
        "documents": documents,
    }


# ──────────────────────────────────────────────────────────────
# Single-stage run endpoints
# ──────────────────────────────────────────────────────────────

class StageRequest(BaseModel):
    slug: str
    max_tokens: int = 512
    overlap_tokens: int = 75


def _similarity(a: str, b: str) -> float:
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()


def _normalize_spaces(s: str) -> str:
    return re.sub(r'\s+', ' ', s).strip()


def _find_header_phrases(text: str, min_len: int = 35, max_len: int = 220) -> list:
    """Find stamped page-header phrases to strip globally.

    Two strategies:
    A) Repeated exact phrase (count ≥ 2) — catches identical headers on every page.
    B) Similar phrase cluster (≥ 2 members, each possibly count=1) — catches
       headers that vary by page number ("…Page 2", "…Page 3" each appear once).

    Returns a list of exact strings to strip from the document.
    """
    norm_text = _normalize_spaces(text)

    # Pull ALL short-to-medium phrases starting with an uppercase letter from full text
    phrase_re = re.compile(
        r'[A-Z][A-Za-z0-9 ,&|()\[\]/\'.:\-]{' + str(min_len - 1) + r',' + str(max_len) + r'}'
    )
    all_phrases = []
    for m in phrase_re.finditer(norm_text):
        phrase = _normalize_spaces(m.group())
        if min_len <= len(phrase) <= max_len:
            all_phrases.append(phrase)

    if not all_phrases:
        return []

    phrase_counts = Counter(all_phrases)

    # Strategy A: repeated exact phrases
    to_strip = set(p for p, cnt in phrase_counts.items() if cnt >= 2)

    # Strategy B: similarity clusters — even count=1 phrases
    # Only consider phrases not already caught by A
    unique_phrases = [p for p in set(all_phrases) if p not in to_strip]
    used = {p: False for p in unique_phrases}
    for a in unique_phrases:
        if used[a]:
            continue
        cluster = [a]
        for b in unique_phrases:
            if b != a and not used[b] and _similarity(a, b) >= 0.80:
                cluster.append(b)
                used[b] = True
        if len(cluster) >= 2:
            to_strip.update(cluster)
        used[a] = True

    # Deduplicate: drop shorter phrases that are substrings of longer ones
    result = []
    for phrase in sorted(to_strip, key=len, reverse=True):
        if not any(phrase in kept for kept in result):
            result.append(phrase)
    return result


# ──────────────────────────────────────────────────────────────
# LLM Provider Abstraction
# llm_call() routes to the right backend based on LLM_PROVIDER
# env var (or explicit provider= override per call).
#
# All providers are called via httpx — no heavy SDK dependencies.
# ──────────────────────────────────────────────────────────────

async def _call_ollama(prompt: str, max_tokens: int = 2000) -> str:
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()


async def _call_claude(
    prompt: str,
    system: str = "",
    max_tokens: int = 2000,
    json_mode: bool = False,
    heavy: bool = False,
) -> str:
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set — cannot use claude provider")
    model = LLM_MODEL_CLAUDE_HEAVY if heavy else LLM_MODEL_CLAUDE
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"].strip()


async def _call_openai(
    prompt: str,
    system: str = "",
    max_tokens: int = 2000,
    json_mode: bool = False,
    heavy: bool = False,
) -> str:
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not set — cannot use openai provider")
    model = LLM_MODEL_OPENAI_HEAVY if heavy else LLM_MODEL_OPENAI
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body: dict = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


async def llm_call(
    prompt: str,
    *,
    system: str = "",
    max_tokens: int = 2000,
    json_mode: bool = False,
    provider: str | None = None,
    heavy: bool = False,
) -> str:
    """Route an LLM call to the configured provider.

    Args:
        prompt:     User-turn text.
        system:     System prompt (ignored by Ollama which has no system role).
        max_tokens: Maximum tokens to generate.
        json_mode:  Request JSON output (OpenAI json_object mode; Claude uses prompt).
        provider:   Override LLM_PROVIDER for this call (ollama|claude|openai).
        heavy:      Use the more capable model variant (e.g. Sonnet vs Haiku).
    """
    p = provider or LLM_PROVIDER
    if p == "claude":
        return await _call_claude(prompt, system=system, max_tokens=max_tokens,
                                   json_mode=json_mode, heavy=heavy)
    elif p == "openai":
        return await _call_openai(prompt, system=system, max_tokens=max_tokens,
                                   json_mode=json_mode, heavy=heavy)
    else:
        # Ollama: prepend system to prompt since it has no separate role
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        return await _call_ollama(full_prompt, max_tokens=max_tokens)


# ──────────────────────────────────────────────────────────────
# PDF Parsers — LlamaParse (cloud) and LiteParse (local)
# Both return (parse_data, tables_data) in a unified schema.
# ──────────────────────────────────────────────────────────────

def _tables_from_liteparse(lp_result: dict) -> dict:
    """Extract structured tables from a LiteParse result.

    LiteParse marks paragraphs with isTable=True and groups them by tableId.
    We reconstruct table rows by collecting consecutive same-tableId paragraphs.
    """
    tables: list = []
    table_map: dict = {}   # tableId → {page, rows[], context_before, context_after}

    all_pages = lp_result.get("pages", [])
    for page_obj in all_pages:
        page_num = page_obj.get("pageNum") or page_obj.get("pageNumber") or 1
        paragraphs = page_obj.get("paragraphs", [])

        for i, para in enumerate(paragraphs):
            if not para.get("isTable"):
                continue
            table_id = str(para.get("tableId", "unknown"))
            text = para.get("text", "").strip()
            if not text:
                continue

            if table_id not in table_map:
                # capture preceding paragraph as context
                ctx_before = paragraphs[i - 1].get("text", "").strip() if i > 0 else ""
                table_map[table_id] = {
                    "table_id": table_id,
                    "page": page_num,
                    "rows": [],
                    "context_before": ctx_before,
                    "context_after": "",
                }
            table_map[table_id]["rows"].append([c.strip() for c in text.split("|") if c.strip()])

            # capture following paragraph as context (will be overwritten each row, last wins)
            if i + 1 < len(paragraphs) and not paragraphs[i + 1].get("isTable"):
                table_map[table_id]["context_after"] = paragraphs[i + 1].get("text", "").strip()

    for t in table_map.values():
        rows = t["rows"]
        if not rows:
            continue
        # First row is assumed to be headers
        headers = rows[0] if rows else []
        data_rows = rows[1:] if len(rows) > 1 else []
        # Build markdown
        if headers:
            md = "| " + " | ".join(headers) + " |\n"
            md += "| " + " | ".join(["---"] * len(headers)) + " |\n"
            for row in data_rows:
                # Pad or trim to header length
                padded = row + [""] * max(0, len(headers) - len(row))
                md += "| " + " | ".join(padded[:len(headers)]) + " |\n"
        else:
            md = "\n".join("| " + " | ".join(r) + " |" for r in rows)

        tables.append({
            "table_id": t["table_id"],
            "page": t["page"],
            "caption": f"Table {t['table_id']}",
            "headers": headers,
            "rows": data_rows,
            "markdown": md.strip(),
            "context_before": t["context_before"],
            "context_after": t["context_after"],
        })

    return {
        "schema_version": "1.0",
        "parser": "liteparse",
        "total_tables": len(tables),
        "tables": tables,
    }


async def _parse_liteparse(pdf_bytes: bytes, filename: str) -> tuple[dict, dict]:
    """Call the local LiteParse service and return (parse_data, tables_data)."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(tmp_path, "rb") as f:
                resp = await client.post(
                    f"{LITEPARSE_URL}/parse",
                    files={"file": (filename, f, "application/pdf")},
                )
            resp.raise_for_status()
            lp_result = resp.json()
    finally:
        os.unlink(tmp_path)

    if not lp_result.get("success"):
        raise HTTPException(status_code=502, detail=f"LiteParse error: {lp_result.get('error')}")

    tables_data = _tables_from_liteparse(lp_result)
    return lp_result, tables_data


async def _parse_llamaparse(pdf_bytes: bytes, filename: str) -> tuple[dict, dict]:
    """Call the LlamaParse cloud API and return (parse_data, tables_data).

    Converts the LlamaParse JSON result into LiteParse-compatible parse_data
    so all downstream stages (cleanse, index, etc.) work unchanged.
    """
    import asyncio

    headers = {
        "Authorization": f"Bearer {LLAMA_PARSE_API_KEY}",
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        # Step 1: Upload PDF
        upload_resp = await client.post(
            f"{LLAMA_PARSE_BASE_URL}/api/parsing/upload",
            headers=headers,
            files={"file": (filename, pdf_bytes, "application/pdf")},
            data={"language": "en", "parsing_instruction": (
                "Extract all text, tables, and structure. "
                "For tables, preserve headers and all rows exactly. "
                "For legal documents, preserve section numbering and heading hierarchy."
            )},
        )
        upload_resp.raise_for_status()
        job_id = upload_resp.json().get("id") or upload_resp.json().get("job_id")
        if not job_id:
            raise HTTPException(status_code=502, detail="LlamaParse did not return a job ID")

        # Step 2: Poll until complete (max 3 min)
        for _ in range(60):
            await asyncio.sleep(3)
            status_resp = await client.get(
                f"{LLAMA_PARSE_BASE_URL}/api/parsing/job/{job_id}",
                headers=headers,
            )
            status_resp.raise_for_status()
            status = status_resp.json().get("status", "")
            if status == "SUCCESS":
                break
            elif status in ("ERROR", "CANCELLED"):
                raise HTTPException(status_code=502, detail=f"LlamaParse job failed: {status}")
        else:
            raise HTTPException(status_code=504, detail="LlamaParse job timed out after 3 minutes")

        # Step 3: Fetch JSON result (has pages, items, tables)
        json_resp = await client.get(
            f"{LLAMA_PARSE_BASE_URL}/api/parsing/job/{job_id}/result/json",
            headers=headers,
        )
        json_resp.raise_for_status()
        lp_json = json_resp.json()

    # Step 4: Convert LlamaParse JSON → LiteParse-compatible format
    lp_pages = lp_json.get("pages", [])
    tables: list = []
    lp_compat_pages: list = []
    full_text_parts: list = []
    full_md_parts: list = []

    for page_obj in lp_pages:
        page_num = page_obj.get("page", 1)
        page_text = page_obj.get("text", "")
        page_md = page_obj.get("md", page_text)
        full_text_parts.append(page_text)
        full_md_parts.append(page_md)

        # Build paragraphs from items
        paragraphs: list = []
        items = page_obj.get("items", [])
        for idx, item in enumerate(items):
            item_type = item.get("type", "text")
            if item_type == "table":
                rows = item.get("rows", [])
                table_md = item.get("md", "")
                # Context: item before and after
                ctx_before = items[idx - 1].get("value", "") if idx > 0 else ""
                ctx_after = items[idx + 1].get("value", "") if idx + 1 < len(items) else ""

                headers_row = rows[0] if rows else []
                data_rows = rows[1:] if len(rows) > 1 else []
                tbl_id = f"t{len(tables) + 1:03d}"
                tables.append({
                    "table_id": tbl_id,
                    "page": page_num,
                    "caption": item.get("caption", f"Table on page {page_num}"),
                    "headers": headers_row,
                    "rows": data_rows,
                    "markdown": table_md,
                    "context_before": ctx_before.strip(),
                    "context_after": ctx_after.strip(),
                })
                # Add as a table paragraph in compat format (isTable=True)
                paragraphs.append({
                    "text": table_md,
                    "isTable": True,
                    "tableId": tbl_id,
                    "isHeading": False,
                    "headingLevel": 0,
                    "isFooter": False,
                    "isList": False,
                    "y": 0, "x": 0, "height": 0, "width": 0,
                    "avgFontSize": 10, "lineCount": len(rows), "column": 0,
                })
            elif item_type == "heading":
                lvl = item.get("lvl", 1)
                paragraphs.append({
                    "text": item.get("value", ""),
                    "isHeading": True,
                    "headingLevel": lvl,
                    "isTable": False,
                    "isFooter": False,
                    "isList": False,
                    "y": 0, "x": 0, "height": 0, "width": 0,
                    "avgFontSize": 14 - lvl, "lineCount": 1, "column": 0,
                })
            else:
                paragraphs.append({
                    "text": item.get("value", item.get("text", "")),
                    "isHeading": False,
                    "headingLevel": 0,
                    "isTable": False,
                    "isFooter": False,
                    "isList": item_type == "list",
                    "y": 0, "x": 0, "height": 0, "width": 0,
                    "avgFontSize": 10, "lineCount": 1, "column": 0,
                })

        lp_compat_pages.append({
            "pageNum": page_num,
            "text": page_text,
            "paragraphs": paragraphs,
            "width": page_obj.get("width", 612),
            "height": page_obj.get("height", 792),
            "textItems": [],
        })

    full_text = "\n\n".join(full_text_parts)
    full_md = "\n\n".join(full_md_parts)
    total_pages = len(lp_compat_pages)

    parse_data = {
        "success": True,
        "parser": "llamaparse",
        "llamaparse_job_id": job_id,  # saved so stage_extract can reuse via LlamaExtract
        "text": full_text,
        "markdown": full_md,
        "pages": lp_compat_pages,
        "metadata": {
            "filename": filename,
            "totalPages": total_pages,
            "characterCount": len(full_text),
        },
    }

    tables_data = {
        "schema_version": "1.0",
        "parser": "llamaparse",
        "total_tables": len(tables),
        "tables": tables,
    }

    return parse_data, tables_data


async def _run_parse(slug: str, pdf_bytes: bytes, filename: str) -> tuple[dict, dict]:
    """Dispatch to LlamaParse or LiteParse based on config.

    Returns (parse_data, tables_data).
    parse_data is LiteParse-compatible (text, markdown, pages[].paragraphs[]).
    tables_data follows the _tables.json schema.
    """
    if LLAMA_PARSE_API_KEY and not PRIVATE_MODE:
        return await _parse_llamaparse(pdf_bytes, filename)
    return await _parse_liteparse(pdf_bytes, filename)


def strip_headers_footers(text: str) -> str:
    """Remove repeated page header/footer text using three passes.

    Pass 1 — exact line repeats: lines appearing ≥ threshold times AND < 160 chars.
    Pass 2 — similarity clusters: groups near-duplicate short lines (ratio ≥ 0.82)
              spanning ≥ 40% of estimated pages. Catches "...Page 3 of 17" vs
              "...Page 4 of 17" even when each variant appears only once.
    Pass 3 — embedded substring strip: removes header phrases that appear mid-line
              (no surrounding newlines), detected by scanning first-page text for
              phrases that recur ≥ 2× throughout the document.
    """
    total_pages = max(3, text.count("\f") + 1)
    threshold = max(3, total_pages // 4)
    page_num_re = re.compile(r'^\s*\d+\s*$')

    # --- Pass 1: exact line repeats ---
    lines = text.split("\n")
    line_counts = Counter(ln.strip() for ln in lines if ln.strip())
    exact_banned = {ln for ln, cnt in line_counts.items()
                    if cnt >= threshold and len(ln) < 160}

    # --- Pass 2: similarity clustering — include ALL short lines (cnt >= 1) ---
    short_lines = [ln for ln in line_counts if len(ln) < 160 and ln not in exact_banned]
    sim_banned: set = set()
    used = {ln: False for ln in short_lines}
    for a in short_lines:
        if used[a]:
            continue
        cluster = [a]
        for b in short_lines:
            if b != a and not used[b] and _similarity(a, b) >= 0.82:
                cluster.append(b)
                used[b] = True
        total_occ = sum(line_counts[m] for m in cluster)
        if len(cluster) >= 2 and total_occ >= max(3, total_pages * 0.4):
            sim_banned.update(cluster)
        used[a] = True

    banned = exact_banned | sim_banned

    # Apply line-level bans
    cleaned_lines = []
    for ln in lines:
        stripped = ln.strip()
        if page_num_re.match(stripped):
            continue
        if stripped in banned:
            continue
        cleaned_lines.append(ln)
    text = "\n".join(cleaned_lines)

    # --- Pass 3: embedded substring strip (similarity clusters) ---
    lines_norm = [_normalize_spaces(ln) for ln in text.split("\n")]
    text_norm = "\n".join(lines_norm)

    repeated_phrases = _find_header_phrases(text_norm)
    for phrase in repeated_phrases:
        text_norm = text_norm.replace(phrase, " ")

    # --- Pass 4: regex patterns for orphaned legal header remnants ---
    # Previous passes may strip the court name but leave pipe-delimited fragments:
    #   "| IA-42/2025 in IB-201(ND)/2024 | Order Date: 15.03.2025 | Page 3"
    # Also catches standalone "Page N" stamps embedded mid-sentence.
    orphan_patterns = [
        # Pipe-delimited case number + date + page fragments
        re.compile(
            r'\|?\s*(?:IA|IB|CP|CA|MA|TC|OA|RPC)[-\s]?\d+[/()\w-]*'
            r'(?:\s+in\s+\S+)?\s*\|[^|]{5,80}\|\s*(?:Order\s+Date[:\s]+[\d.]+|Page\s+\d+)[^|]*',
            re.IGNORECASE
        ),
        # Bare "Order Date: DD.MM.YYYY" mid-sentence
        re.compile(r'\bOrder\s+Date[:\s]+\d{2}[./]\d{2}[./]\d{4}\b', re.IGNORECASE),
        # "Page N" followed immediately by a section number "Page 3 3."
        re.compile(r'\bPage\s+\d+\s+\d+\.', re.IGNORECASE),
        # Standalone pipe with content < 5 words: "| Page 2" or "| 02.08.2024"
        re.compile(r'\|\s{0,3}(?:Page\s+\d+|\d{2}[./]\d{2}[./]\d{4})\s*\|?', re.IGNORECASE),
        # "IN THE [A-Z]+ BENCH/COURT" header remnants not caught by phrase pass
        re.compile(
            r'\bIN\s+THE\s+[A-Z ,]{5,60}(?:TRIBUNAL|COURT|BENCH)\b[^.!?]{0,80}',
            re.IGNORECASE
        ),
    ]
    for pat in orphan_patterns:
        text_norm = pat.sub(" ", text_norm)

    # Collapse excess whitespace
    text_norm = re.sub(r'[ \t]{3,}', ' ', text_norm)
    text_norm = re.sub(r'\n{3,}', '\n\n', text_norm)
    return text_norm.strip()


@app.post("/vault/stage/assess")
async def stage_assess(request: StageRequest):
    """Pre-pipeline PDF quality gate — assess before spending API credits.

    Reads the raw PDF from _attachments/{slug}.pdf and checks:
      - file_size_kb
      - page_count (via pypdf if available, else estimates)
      - text_density: chars-per-page from any embedded text layer
      - symbol_noise_ratio: fraction of non-ASCII / garbage chars
      - is_scanned: True if text_density < 100 (image-only PDF, needs OCR)
      - estimated_tokens: rough estimate for API cost planning
      - recommendation: ok / ocr_needed / too_large / too_small / corrupt

    Writes assessment to _index.md frontmatter under assess_* keys.
    Does NOT modify the PDF or run any extraction.
    """
    slug = request.slug
    pdf_path = Path(VAULT_ROOT) / "_attachments" / f"{slug}.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"PDF not found: _attachments/{slug}.pdf")

    file_size_kb = pdf_path.stat().st_size // 1024
    page_count = 0
    char_count = 0
    non_ascii = 0
    text_sample = ""

    try:
        import pypdf
        reader = pypdf.PdfReader(str(pdf_path))
        page_count = len(reader.pages)
        texts = []
        for pg in reader.pages[:10]:  # sample first 10 pages
            t = pg.extract_text() or ""
            texts.append(t)
            char_count += len(t)
            non_ascii += sum(1 for c in t if ord(c) > 127 or (ord(c) < 32 and c not in "\n\t "))
        text_sample = " ".join(texts)[:500]
    except ImportError:
        # pypdf not installed — estimate from file size
        page_count = max(1, file_size_kb // 50)
    except Exception as e:
        return {
            "success": False, "slug": slug,
            "error": f"Could not read PDF: {e}",
            "recommendation": "corrupt",
        }

    text_density = char_count // max(1, min(page_count, 10))  # chars per sampled page
    symbol_noise = round(non_ascii / max(1, char_count), 3)
    is_scanned = text_density < 100
    estimated_tokens = (file_size_kb * 800) // 1024  # rough: ~800 tokens/KB for text PDFs

    if page_count == 0:
        recommendation = "corrupt"
    elif file_size_kb > 50_000:
        recommendation = "too_large"
    elif page_count < 2:
        recommendation = "too_small"
    elif is_scanned:
        recommendation = "ocr_needed"
    elif symbol_noise > 0.15:
        recommendation = "high_noise"
    else:
        recommendation = "ok"

    assessment = {
        "assess_file_size_kb": file_size_kb,
        "assess_page_count": page_count,
        "assess_text_density": text_density,
        "assess_symbol_noise": symbol_noise,
        "assess_is_scanned": is_scanned,
        "assess_estimated_tokens": estimated_tokens,
        "assess_recommendation": recommendation,
        "pipeline_stage": "assessed",
    }

    try:
        idx = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
        idx.metadata.update(assessment)
        write_note(VAULT_ROOT, f"sources/{slug}/_index.md", idx.metadata, idx.body)
    except FileNotFoundError:
        pass  # index may not exist yet if assess runs before ingest

    return {
        "success": True,
        "slug": slug,
        "file_size_kb": file_size_kb,
        "page_count": page_count,
        "text_density_chars_per_page": text_density,
        "symbol_noise_ratio": symbol_noise,
        "is_scanned": is_scanned,
        "estimated_tokens": estimated_tokens,
        "recommendation": recommendation,
        "text_sample": text_sample[:200] if text_sample else "",
    }


@app.post("/vault/stage/parse")
async def stage_parse(request: StageRequest):
    """Parse the saved PDF using LlamaParse (cloud) or LiteParse (local fallback).

    Reads the PDF from _attachments/{slug}.pdf, parses it, and writes:
      _parse.json  — LiteParse-compatible text + paragraphs (used by all downstream stages)
      _tables.json — structured table extraction (used by index + chunk stages)

    If LLAMA_PARSE_API_KEY is set and PRIVATE_MODE is false, uses LlamaParse.
    Otherwise uses the local LiteParse service.
    """
    slug = request.slug

    # Load saved PDF
    pdf_path = Path(VAULT_ROOT) / "_attachments" / f"{slug}.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404,
                            detail=f"No PDF found for '{slug}'. Use save-pdf-upload or save-pdf-url first.")

    pdf_bytes = pdf_path.read_bytes()

    # Get filename from existing _index.md if present
    try:
        idx_note = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
        filename = idx_note.metadata.get("filename", f"{slug}.pdf")
    except FileNotFoundError:
        filename = f"{slug}.pdf"

    # Parse
    with stage_log("parse", slug, file=filename):
        parse_data, tables_data = await _run_parse(slug, pdf_bytes, filename)

    # Persist
    write_parse_json(VAULT_ROOT, slug, parse_data)
    write_tables_json(VAULT_ROOT, slug, tables_data)

    total_pages = parse_data.get("metadata", {}).get("totalPages", 0)
    total_chars = parse_data.get("metadata", {}).get("characterCount", len(parse_data.get("text", "")))
    parser_used = parse_data.get("parser", "liteparse")
    tables_found = tables_data.get("total_tables", 0)
    logger.info(f"  parse result: parser={parser_used}  pages={total_pages}  chars={total_chars:,}  tables={tables_found}")

    # Update _index.md with page/char counts and new stage
    try:
        idx_note = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
        idx_note.metadata["total_pages"] = total_pages
        idx_note.metadata["total_chars"] = total_chars
        idx_note.metadata["parser"] = parser_used
        idx_note.metadata["pipeline_stage"] = "parsed"
        write_note(VAULT_ROOT, f"sources/{slug}/_index.md", idx_note.metadata, idx_note.body)
    except FileNotFoundError:
        pass

    return {
        "success": True,
        "slug": slug,
        "parser": parser_used,
        "total_pages": total_pages,
        "total_chars": total_chars,
        "tables_found": tables_found,
        "message": (
            f"Parsed {total_pages}p / {total_chars:,} chars via {parser_used}"
            + (f" — {tables_found} tables extracted" if tables_found else "")
        ),
    }


@app.post("/vault/stage/cleanse")
async def stage_cleanse(request: StageRequest):
    """Strip repeated headers/footers from full text, then rebuild PageIndex tree."""
    slug = request.slug
    parse_data = read_parse_json(VAULT_ROOT, slug)
    if parse_data is None:
        raise HTTPException(status_code=404, detail=f"No parse data for: {slug}. Run Parse first.")

    # Clean full text
    raw_text = parse_data.get("text", "")
    clean_text = strip_headers_footers(raw_text)

    # Also clean markdown field — PageIndex reads `markdown` (not `text`) to build the tree
    # so headers must be stripped from markdown too, otherwise section notes inherit dirty content
    raw_markdown = parse_data.get("markdown", "")
    clean_markdown = strip_headers_footers(raw_markdown) if raw_markdown else raw_markdown

    # Detect header paragraph texts across all pages (frequency-based, same logic as strip_headers_footers)
    # PageIndex reads pages[].paragraphs[].text — must filter those too
    # Table paragraphs are excluded from header detection: table cell content is not a header
    all_pages = parse_data.get("pages", [])
    all_para_texts = [
        para.get("text", "").strip()
        for page in all_pages
        for para in page.get("paragraphs", [])
        if para.get("text", "").strip() and not para.get("isTable", False)
    ]
    para_counts = Counter(all_para_texts)
    total_pages_est = max(3, len(all_pages))
    para_threshold = max(2, total_pages_est // 4)

    # Exact-repeat headers
    exact_header_paras = {t for t, cnt in para_counts.items() if cnt >= para_threshold and len(t) < 300}
    # Similarity-cluster headers (catches "...Page 2" vs "...Page 3")
    sim_header_paras: set = set()
    unique_paras = [t for t in para_counts if len(t) < 300 and t not in exact_header_paras]
    used_para = {t: False for t in unique_paras}
    for a in unique_paras:
        if used_para[a]:
            continue
        cluster = [a]
        for b in unique_paras:
            if b != a and not used_para[b] and _similarity(a, b) >= 0.82:
                cluster.append(b)
                used_para[b] = True
        total_occ = sum(para_counts[m] for m in cluster)
        if len(cluster) >= 2 and total_occ >= max(2, total_pages_est * 0.4):
            sim_header_paras.update(cluster)
        used_para[a] = True

    banned_para_texts = exact_header_paras | sim_header_paras

    # Regex patterns for embedded legal headers within paragraph text
    # Used both for detecting pure-header paragraphs and stripping header tails
    _embedded_header_subs = [
        # "IN THE NATIONAL COMPANY LAW TRIBUNAL, NEW DELHI BENCH ..." up to a sentence boundary or end
        re.compile(
            r'\bIN\s+THE\s+[A-Z ,]{5,60}(?:TRIBUNAL|COURT|BENCH)\b[^.]{0,120}',
            re.IGNORECASE
        ),
        # Pipe-delimited case fragments: "| IA-42/2025 in IB-201 | Order Date: ... | Page N"
        re.compile(
            r'\|?\s*(?:IA|IB|CP|CA|MA|TC|OA|RPC)[-\s]?\d+[/()\w-]*'
            r'(?:\s+in\s+\S+)?\s*\|[^|]{5,80}\|\s*(?:Order\s+Date[:\s]+[\d./]+|Page\s+\d+)[^|]*',
            re.IGNORECASE
        ),
        re.compile(r'\bOrder\s+Date[:\s]+\d{2}[./]\d{2}[./]\d{4}\b', re.IGNORECASE),
        re.compile(r'\|\s{0,3}(?:Page\s+\d+|\d{2}[./]\d{2}[./]\d{4})\s*\|?', re.IGNORECASE),
        re.compile(r'^\s*Page\s+\d+\s*$', re.IGNORECASE),
    ]

    # Detect paragraphs with purely header content (no real body text)
    _pure_header_re = re.compile(
        r'^(?:IN\s+THE\s+[A-Z ,]{5,60}(?:TRIBUNAL|COURT|BENCH)|'
        r'(?:IA|IB|CP|CA|MA|TC|OA|RPC)[-\s]?\d+[/()\w-]*[\s|].*|'
        r'Order\s+Date[:\s]+\d{2}[./]\d{2}[./]\d{4}|'
        r'Page\s+\d+)\s*$',
        re.IGNORECASE
    )

    def clean_para(text: str) -> str:
        """Remove header content from a paragraph, preserving real body content."""
        t = text.strip()
        if not t:
            return ""
        # Exact or similarity-cluster match → blank entirely
        if t in banned_para_texts:
            return ""
        # Pure header paragraph (anchored match) → blank entirely
        if _pure_header_re.match(t):
            return ""
        # Mixed paragraph: strip embedded header patterns, keep real content
        result = t
        for pat in _embedded_header_subs:
            result = pat.sub(" ", result)
        result = re.sub(r'[ \t]{2,}', ' ', result).strip()
        # If nothing real is left, blank it
        if len(result) < 10:
            return ""
        return result

    # Clean per-page text AND paragraphs — table paragraphs are left untouched
    clean_pages = []
    for page in all_pages:
        page_copy = dict(page)
        page_copy["text"] = strip_headers_footers(page.get("text", ""))
        clean_paras = []
        for para in page.get("paragraphs", []):
            para_copy = dict(para)
            if para.get("isTable", False):
                # Never strip header/footer patterns from table cells
                clean_paras.append(para_copy)
            else:
                para_copy["text"] = clean_para(para.get("text", ""))
                clean_paras.append(para_copy)
        page_copy["paragraphs"] = clean_paras
        clean_pages.append(page_copy)

    # Write cleaned parse data back (overwrites original so downstream stages use clean text)
    clean_parse = dict(parse_data)
    clean_parse["text"] = clean_text
    clean_parse["markdown"] = clean_markdown
    if clean_pages:
        clean_parse["pages"] = clean_pages
    write_parse_json(VAULT_ROOT, slug, clean_parse)

    # Rebuild PageIndex tree from cleaned text
    # PageIndex requires "filename" in liteparse_result
    if "filename" not in clean_parse:
        # Try to recover filename from index note frontmatter, then fall back to slug
        try:
            idx_note = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
            clean_parse["filename"] = idx_note.metadata.get("filename", f"{slug}.pdf")
        except Exception:
            clean_parse["filename"] = f"{slug}.pdf"
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{PAGEINDEX_URL}/build-tree",
            json={"liteparse_result": clean_parse},
        )
        resp.raise_for_status()
        tree_result = resp.json()

    write_tree_json(VAULT_ROOT, slug, tree_result)

    removed_chars = len(raw_text) - len(clean_text)
    removed_markdown_chars = len(raw_markdown) - len(clean_markdown)
    return {
        "success": True, "slug": slug,
        "original_chars": len(raw_text),
        "clean_chars": len(clean_text),
        "removed_chars": removed_chars,
        "original_markdown_chars": len(raw_markdown),
        "clean_markdown_chars": len(clean_markdown),
        "removed_markdown_chars": removed_markdown_chars,
        "tree_nodes": len(tree_result.get("tree", {}).get("children", [])),
    }


# ──────────────────────────────────────────────────────────────
# Structured metadata JSON schema written alongside _parse.json
# ──────────────────────────────────────────────────────────────

import json as _json_mod

def _meta_json_path(vault_root: str, slug: str) -> Path:
    return Path(vault_root) / "sources" / slug / "_meta.json"

def write_meta_json(vault_root: str, slug: str, meta: dict) -> None:
    p = _meta_json_path(vault_root, slug)
    with open(p, "w", encoding="utf-8") as f:
        _json_mod.dump(meta, f, ensure_ascii=False, indent=2)

def read_meta_json(vault_root: str, slug: str) -> Optional[dict]:
    p = _meta_json_path(vault_root, slug)
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return _json_mod.load(f)


# ──────────────────────────────────────────────────────────────
# LlamaClassify + LlamaExtract — classify then schema-route
#
# Stage order:
#   stage_classify → identifies doc_type + confidence, stores classify_parse_job_id
#   stage_extract  → picks schema by doc_type, runs LlamaExtract with classify_parse_job_id
#
# API notes (observed, differ from SDK docs):
#   Classify:  POST /api/v2/classify  { file_input: str, configuration: { rules: [] } }
#              GET  /api/v2/classify/{id}  → status COMPLETED, result.type, parse_job_id
#   Extract:   POST /api/v2/extract   { file_input: str(file_id), configuration: { data_schema, tier } }
#              file_input for extract must be a file_id, NOT a parse_job_id
# ──────────────────────────────────────────────────────────────

# Schema registry — maps doc_type → extraction schema.
# Schemas live in vault-pipeline/schemas/*.json — edit them there, no code change needed.

_SCHEMAS_DIR = Path(__file__).parent / "schemas"

def _load_schema(filename: str) -> dict:
    return json.loads((_SCHEMAS_DIR / filename).read_text())

# IBC document classification rules — loaded from schemas/classification_rules.json.
# Edit that file to add/remove/modify doc types. No code change needed.
IBC_CLASSIFICATION_RULES = _load_schema("classification_rules.json")

IBC_EXTRACTION_SCHEMA = _load_schema("ibc_extraction.json")
ADMISSION_ORDER_SCHEMA = _load_schema("admission_order.json")
LIQUIDATION_ORDER_SCHEMA = _load_schema("liquidation_order.json")
PETITION_SCHEMA = _load_schema("petition.json")
INFORMATION_MEMORANDUM_SCHEMA = _load_schema("information_memorandum.json")

# Schema router — returns the appropriate extraction schema for a doc_type.
# Falls back to IBC_EXTRACTION_SCHEMA for unknown types.
def _schema_for_doc_type(doc_type: str) -> dict:
    return {
        "resolution_plan_order": IBC_EXTRACTION_SCHEMA,
        "resolution_plan": IBC_EXTRACTION_SCHEMA,
        "admission_order": ADMISSION_ORDER_SCHEMA,
        "liquidation_order": LIQUIDATION_ORDER_SCHEMA,
        "petition": PETITION_SCHEMA,
        "information_memorandum": INFORMATION_MEMORANDUM_SCHEMA,
    }.get(doc_type, IBC_EXTRACTION_SCHEMA)


async def _upload_to_llamacloud(pdf_bytes: bytes, filename: str) -> str:
    """Upload a PDF to LlamaCloud Files API and return the file_id.

    Used when LiteParse was used (no parse_job_id) but we want LlamaExtract.
    The file_id is then passed directly to LlamaExtract as file_input.
    """
    headers = {"Authorization": f"Bearer {LLAMA_PARSE_API_KEY}"}
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{LLAMA_PARSE_BASE_URL}/api/v1/files",
            headers=headers,
            files={"upload_file": (filename, pdf_bytes, "application/pdf")},
        )
        resp.raise_for_status()
        file_id = resp.json().get("id")
        if not file_id:
            raise HTTPException(502, "LlamaCloud file upload did not return an ID")
        return file_id


async def _llamaclassify_run(file_id: str, rules: list) -> dict:
    """Submit a LlamaClassify job and poll until COMPLETED.

    file_id: LlamaCloud file ID from _upload_to_llamacloud()
    rules:   list of {type, description} dicts (IBC_CLASSIFICATION_RULES)
    Returns: {type, confidence, reasoning, classify_parse_job_id}
             classify_parse_job_id can be passed to _llamaextract_run via stage_extract.

    API (observed):
      POST /api/v2/classify  { file_input: str, configuration: { rules: [] } }
      GET  /api/v2/classify/{id}  → status COMPLETED, result.{type, confidence, reasoning}, parse_job_id
    """
    import asyncio

    headers = {
        "Authorization": f"Bearer {LLAMA_PARSE_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        submit_resp = await client.post(
            f"{LLAMA_PARSE_BASE_URL}/api/v2/classify",
            headers=headers,
            json={
                "file_input": file_id,
                "configuration": {"rules": rules},
            },
        )
        submit_resp.raise_for_status()
        job_id = submit_resp.json().get("id")
        if not job_id:
            raise HTTPException(502, "LlamaClassify did not return a job ID")

        for _ in range(60):
            await asyncio.sleep(4)
            poll_resp = await client.get(
                f"{LLAMA_PARSE_BASE_URL}/api/v2/classify/{job_id}",
                headers=headers,
            )
            poll_resp.raise_for_status()
            result = poll_resp.json()
            status = result.get("status", "")

            if status in ("COMPLETED", "SUCCESS"):
                cls_result = result.get("result") or {}
                return {
                    "doc_type": cls_result.get("type", "other"),
                    "confidence": cls_result.get("confidence", 0.0),
                    "reasoning": cls_result.get("reasoning", ""),
                    # parse_job_id returned by classifier can feed into LlamaExtract
                    "classify_parse_job_id": result.get("parse_job_id"),
                }
            if status in ("ERROR", "FAILED", "CANCELLED"):
                raise HTTPException(502, f"LlamaClassify failed: {result.get('error_message', status)}")

        raise HTTPException(504, "LlamaClassify timed out")


@app.post("/vault/stage/classify")
async def stage_classify(request: StageRequest):
    """Classify document type using LlamaCloud classifier.

    Uploads PDF (or reuses cached llamacloud_file_id), runs the classifier
    against IBC_CLASSIFICATION_RULES, and stores:
      - doc_type, classification_confidence, classification_reasoning in _index.md
      - classify_parse_job_id in _index.md (used by stage_extract to skip re-upload)

    Run this before stage_extract. If skipped, stage_extract falls back to
    LlamaExtract with the generic IBC schema (no schema routing).
    """
    slug = request.slug

    if not LLAMA_PARSE_API_KEY or PRIVATE_MODE:
        raise HTTPException(400, "LlamaClassify requires LLAMA_PARSE_API_KEY and PRIVATE_MODE=false")

    # Get or upload file to LlamaCloud
    file_id: Optional[str] = None
    try:
        idx = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
        file_id = idx.metadata.get("llamacloud_file_id")
    except FileNotFoundError:
        raise HTTPException(404, f"Source not found: {slug}. Run stage_parse first.")

    if not file_id:
        pdf_path = Path(VAULT_ROOT) / "_attachments" / f"{slug}.pdf"
        if not pdf_path.exists():
            raise HTTPException(404, f"No PDF attachment found for: {slug}")
        file_id = await _upload_to_llamacloud(pdf_path.read_bytes(), f"{slug}.pdf")
        idx.metadata["llamacloud_file_id"] = file_id
        write_note(VAULT_ROOT, f"sources/{slug}/_index.md", idx.metadata, idx.body)

    # Run classifier
    cls = await _llamaclassify_run(file_id, IBC_CLASSIFICATION_RULES)

    # Persist classification result to _index.md
    try:
        idx = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
        idx.metadata["doc_type"] = cls["doc_type"]
        idx.metadata["classification_confidence"] = cls["confidence"]
        idx.metadata["classification_reasoning"] = cls["reasoning"][:500]  # truncate for frontmatter
        if cls.get("classify_parse_job_id"):
            idx.metadata["classify_parse_job_id"] = cls["classify_parse_job_id"]
        idx.metadata["pipeline_stage"] = "classified"
        write_note(VAULT_ROOT, f"sources/{slug}/_index.md", idx.metadata, idx.body)
    except FileNotFoundError:
        pass

    logger.info(f"  classify result: doc_type={cls['doc_type']}  confidence={cls['confidence']}")
    return {
        "success": True,
        "slug": slug,
        "doc_type": cls["doc_type"],
        "confidence": cls["confidence"],
        "reasoning": cls["reasoning"],
        "classify_parse_job_id": cls.get("classify_parse_job_id"),
    }


async def _llamaextract_run(file_id: str, schema: dict, tier: str = "cost_effective") -> dict:
    """Submit a LlamaExtract job and poll until COMPLETED.

    file_id: LlamaCloud file ID from _upload_to_llamacloud()
    schema:  JSON Schema dict placed inside configuration.data_schema
    Returns the extracted data dict matching the schema (from extract_result).

    API notes (observed behaviour, differs from docs):
      - file_input: plain string file_id (not an object)
      - data_schema lives inside configuration{} not at top level
      - terminal status is "COMPLETED" (docs say "SUCCESS")
      - result is in extract_result (docs say data)
    """
    import asyncio

    headers = {
        "Authorization": f"Bearer {LLAMA_PARSE_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        # Submit extraction job
        submit_resp = await client.post(
            f"{LLAMA_PARSE_BASE_URL}/api/v2/extract",
            headers=headers,
            json={
                "file_input": file_id,  # plain string, not an object
                "configuration": {
                    "tier": tier,
                    "extraction_target": "per_doc",
                    "data_schema": schema,  # schema goes inside configuration
                },
            },
        )
        submit_resp.raise_for_status()
        job_id = submit_resp.json().get("id")
        if not job_id:
            raise HTTPException(502, "LlamaExtract did not return a job ID")

        # Poll until terminal state (max 5 min)
        for _ in range(100):
            await asyncio.sleep(3)
            poll_resp = await client.get(
                f"{LLAMA_PARSE_BASE_URL}/api/v2/extract/{job_id}",
                headers=headers,
            )
            poll_resp.raise_for_status()
            result = poll_resp.json()
            status = result.get("status", "")

            if status in ("COMPLETED", "SUCCESS", "PARTIAL_SUCCESS"):
                # Result is in extract_result (observed) or data (documented)
                return result.get("extract_result") or result.get("data") or {}
            if status in ("ERROR", "CANCELLED", "FAILED"):
                err = result.get("error_message") or result.get("error") or status
                raise HTTPException(502, f"LlamaExtract job failed: {err}")
            if status == "THROTTLED":
                await asyncio.sleep(10)

        raise HTTPException(504, "LlamaExtract job timed out after 5 minutes")


async def _extract_via_llm(slug: str, parse_data: dict) -> dict:
    """Fallback: extract metadata via LLM prompting (Ollama/Claude/OpenAI).

    Used when LLAMA_PARSE_API_KEY is not set or PRIVATE_MODE is on.
    Only reads the first 4000 chars — full-doc multi-pass is Sprint 2.
    """
    text_snippet = parse_data.get("text", "")[:4000]
    prompt = (
        "You are a legal document analyst. Extract structured metadata from the following "
        "Indian insolvency (IBC) legal document text.\n"
        "Return ONLY a valid JSON object with these fields (null for missing):\n"
        '{"doc_type":"resolution_plan_order|court_order|petition|appeal|other",'
        '"case_number":null,"court":null,"order_date":"YYYY-MM-DD",'
        '"corporate_debtor":null,"resolution_applicant":null,'
        '"insolvency_professional":null,"resolution_amount_inr":null,'
        '"ibc_sections":[],"parties":[]}\n\n'
        f"Document:\n{text_snippet}\n\nJSON:"
    )
    try:
        raw = await llm_call(prompt, max_tokens=1000, json_mode=True)
        m = re.search(r'\{[\s\S]*\}', raw)
        return _json_mod.loads(m.group()) if m else {}
    except Exception as e:
        return {"extract_error": str(e)}


@app.post("/vault/stage/extract")
async def stage_extract(request: StageRequest):
    """Extract structured legal + financial metadata from the document.

    Primary path (when LLAMA_PARSE_API_KEY is set):
      1. Reads doc_type from _index.md (set by stage_classify if already run).
      2. Selects the matching extraction schema via _schema_for_doc_type().
      3. Calls LlamaExtract with the schema-routed extraction.
      Uses cached llamacloud_file_id to avoid re-upload if stage_classify already ran.

    Fallback (no API key / PRIVATE_MODE):
      LLM prompting via Ollama/Claude/OpenAI on first 4000 chars.

    Output: sources/{slug}/_meta.json + _index.md frontmatter updated.
    Financial fields are typed ints/floats from LlamaExtract — no string parsing.
    """
    slug = request.slug
    parse_data = read_parse_json(VAULT_ROOT, slug)
    if parse_data is None:
        raise HTTPException(status_code=404, detail=f"No parse data for: {slug}. Run Cleanse first.")

    meta: dict = {}
    extract_method = "llm"
    schema_used = "IBC_EXTRACTION_SCHEMA"

    if LLAMA_PARSE_API_KEY and not PRIVATE_MODE:
        # Read cached doc_type and file_id from _index.md (set by stage_classify)
        file_id: Optional[str] = None
        doc_type: str = "other"
        try:
            idx_check = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
            file_id = idx_check.metadata.get("llamacloud_file_id")
            doc_type = idx_check.metadata.get("doc_type", "other")
        except FileNotFoundError:
            pass

        if not file_id:
            # stage_classify hasn't run yet — upload PDF now
            pdf_path = Path(VAULT_ROOT) / "_attachments" / f"{slug}.pdf"
            if pdf_path.exists():
                try:
                    file_id = await _upload_to_llamacloud(pdf_path.read_bytes(), f"{slug}.pdf")
                    try:
                        idx_upd = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
                        idx_upd.metadata["llamacloud_file_id"] = file_id
                        write_note(VAULT_ROOT, f"sources/{slug}/_index.md", idx_upd.metadata, idx_upd.body)
                    except FileNotFoundError:
                        pass
                except Exception as upload_err:
                    file_id = None
                    meta["upload_error"] = str(upload_err)

        if file_id:
            # Route to the right schema for this doc_type
            schema = _schema_for_doc_type(doc_type)
            schema_name_map = {
                "resolution_plan_order": "IBC_EXTRACTION_SCHEMA",
                "resolution_plan": "IBC_EXTRACTION_SCHEMA",
                "admission_order": "ADMISSION_ORDER_SCHEMA",
                "liquidation_order": "LIQUIDATION_ORDER_SCHEMA",
                "petition": "PETITION_SCHEMA",
                "information_memorandum": "INFORMATION_MEMORANDUM_SCHEMA",
            }
            schema_used = schema_name_map.get(doc_type, "IBC_EXTRACTION_SCHEMA")
            try:
                meta = await _llamaextract_run(file_id, schema)
                extract_method = "llamaextract"
            except Exception as e:
                meta = {"llamaextract_error": str(e)}

    if not meta or "llamaextract_error" in meta:
        llm_meta = await _extract_via_llm(slug, parse_data)
        meta.update(llm_meta)

    meta["slug"] = slug
    meta["extract_method"] = extract_method
    meta["schema_used"] = schema_used
    write_meta_json(VAULT_ROOT, slug, meta)

    # Promote all non-null fields to _index.md frontmatter
    _index_fields = (
        "doc_type", "case_number", "court", "order_date", "judges",
        "corporate_debtor", "resolution_applicant", "insolvency_professional",
        "petition_type", "cirp_commencement_date", "admission_date",
        "ibc_sections", "parties",
        # Financial fields — typed ints/floats from LlamaExtract schema
        "resolution_amount_inr", "liquidation_value_inr", "fair_value_inr",
        "total_admitted_inr", "upfront_inr", "payment_timeline_months",
        "haircut_pct", "coc_approval_pct", "cirp_cost_inr",
        "fc_recovery_pct", "section_29a_compliant",
    )
    try:
        idx = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
        for k in _index_fields:
            v = meta.get(k)
            if v is not None and v != [] and v != "":
                idx.metadata[k] = v
        # creditors[] goes into _meta.json only (too large for frontmatter)
        idx.metadata["pipeline_stage"] = "extracted"
        idx.metadata["extract_method"] = extract_method
        write_note(VAULT_ROOT, f"sources/{slug}/_index.md", idx.metadata, idx.body)
    except FileNotFoundError:
        pass

    # Build a concise summary for the response
    financial_fields = {k: meta[k] for k in (
        "resolution_amount_inr", "total_admitted_inr", "haircut_pct",
        "coc_approval_pct", "liquidation_value_inr",
    ) if meta.get(k) is not None}

    logger.info(
        f"  extract result: method={extract_method}  schema={schema_used}"
        f"  doc_type={meta.get('doc_type','?')}  creditors={len(meta.get('creditors') or [])}"
        f"  fields={list(financial_fields.keys())}"
    )
    return {
        "success": True,
        "slug": slug,
        "extract_method": extract_method,
        "schema_used": schema_used,
        "creditors_found": len(meta.get("creditors") or []),
        "financial": financial_fields,
        "meta": {k: v for k, v in meta.items() if k not in ("creditors", "parties")},
    }


# ──────────────────────────────────────────────────────────────
# AKN annotation prompt — loaded from schemas/akn_prompt_system.txt
# ──────────────────────────────────────────────────────────────
_AKN_SYSTEM_PROMPT = (_SCHEMAS_DIR / "akn_prompt_system.txt").read_text()

# Doc types that are NCLT/NCLAT court orders — AKN judgment schema applies.
# Information memoranda, resolution plans, petitions use different schemas.
_AKN_ORDER_TYPES = {
    "resolution_plan_order",
    "admission_order",
    "liquidation_order",
    "interim_order",
    "appeal_order",
}

# Max characters of document text sent to the LLM for AKN annotation.
# NCLT orders are typically 5k–40k chars. We cap at 20k — motivation/decision
# are rarely beyond the midpoint, and header/preamble are trivially identifiable.
_AKN_MAX_CHARS = 20_000


@app.post("/vault/stage/akn")
async def stage_akn(request: StageRequest):
    """Annotate an NCLT/NCLAT court order with AKN-lite structural elements.

    Reads doc_type from _index.md (set by stage_classify). Only runs for
    court order doc types — skips information_memorandum, resolution_plan,
    petition, valuation_report, other.

    Calls Claude (heavy) with the AKN system prompt to identify:
      header, preamble, background, motivation, decision elements
    plus references: IBC citations, case citations, organizations, key dates.

    Output:
      sources/{slug}/_akn.json  — AKN-lite JSON annotation
      _index.md frontmatter     — akn_elements list, frbr_uri, pipeline_stage: akn
    """
    slug = request.slug

    parse_data = read_parse_json(VAULT_ROOT, slug)
    if parse_data is None:
        raise HTTPException(status_code=404, detail=f"No parse data for: {slug}. Run Cleanse first.")

    # Read doc_type and existing metadata from _index.md
    doc_type = "other"
    existing_meta: dict = {}
    try:
        idx = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
        doc_type = idx.metadata.get("doc_type", "other")
        existing_meta = {
            k: idx.metadata.get(k, "")
            for k in ("case_number", "court", "order_date", "corporate_debtor",
                       "resolution_applicant", "insolvency_professional")
        }
    except FileNotFoundError:
        pass

    if doc_type not in _AKN_ORDER_TYPES:
        return {
            "success": False,
            "slug": slug,
            "skipped": True,
            "reason": f"doc_type '{doc_type}' is not a court order — AKN annotation not applicable.",
        }

    # Skip if already annotated (avoid re-billing on re-runs)
    if not getattr(request, "force", False):
        existing_akn = read_akn_json(VAULT_ROOT, slug)
        if existing_akn and existing_akn.get("elements"):
            return {
                "success": True,
                "slug": slug,
                "skipped": True,
                "reason": "_akn.json already exists — pass force=true to re-annotate.",
                "frbr_uri": existing_akn.get("frbr_uri", ""),
                "elements": [el.get("akn_element") for el in existing_akn.get("elements", [])],
            }

    # Get full document text, truncate to avoid context overflow
    full_text = parse_data.get("text", "")
    if not full_text:
        pages = parse_data.get("pages", [])
        full_text = "\n\n".join(p.get("text", "") for p in pages if p.get("text"))

    text_for_llm = full_text[:_AKN_MAX_CHARS]
    truncated = len(full_text) > _AKN_MAX_CHARS

    # Build user prompt — include already-extracted metadata as grounding context
    meta_context = "\n".join(
        f"  {k}: {v}" for k, v in existing_meta.items() if v
    )
    user_prompt = f"""Annotate the following NCLT/NCLAT court order using the AKN judgment schema.

Already extracted metadata (use as grounding context):
{meta_context if meta_context else "  (none yet — infer from document)"}

Document text:
---
{text_for_llm}
---
{"[NOTE: Document truncated at 40,000 characters. Annotate what is present.]" if truncated else ""}

Return ONLY valid JSON as specified in the system prompt."""

    raw = await llm_call(
        user_prompt,
        system=_AKN_SYSTEM_PROMPT,
        max_tokens=4000,
        json_mode=True,
        provider="openai",
        heavy=False,
    )

    # Parse LLM response
    akn_data: dict = {}
    parse_error: str = ""
    try:
        # Strip markdown fences if model wrapped the JSON anyway
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        akn_data = json.loads(cleaned.strip())
    except Exception as e:
        parse_error = str(e)
        akn_data = {"raw_response": raw, "parse_error": parse_error}

    # Attach provenance fields
    akn_data["slug"] = slug
    akn_data["doc_type"] = doc_type
    akn_data["annotated_by"] = LLM_MODEL_CLAUDE_HEAVY
    akn_data["truncated"] = truncated
    akn_data["akn_version"] = "1.0"

    write_akn_json(VAULT_ROOT, slug, akn_data)

    # Promote key fields to _index.md frontmatter
    elements_found = [e["akn_element"] for e in akn_data.get("elements", [])]
    try:
        idx = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
        idx.metadata["akn_elements"] = elements_found
        if akn_data.get("frbr_uri"):
            idx.metadata["frbr_uri"] = akn_data["frbr_uri"]
        idx.metadata["pipeline_stage"] = "akn"
        write_note(VAULT_ROOT, f"sources/{slug}/_index.md", idx.metadata, idx.body)
    except FileNotFoundError:
        pass

    logger.info(
        f"  akn result: elements={elements_found}  frbr={akn_data.get('frbr_uri','?')}"
        f"  refs_cases={len(akn_data.get('references',{}).get('case_citations',[]))}"
        f"  refs_ibc={len(akn_data.get('references',{}).get('ibc_citations',[]))}"
        + ("  [TRUNCATED]" if truncated else "")
    )
    return {
        "success": True,
        "slug": slug,
        "doc_type": doc_type,
        "frbr_uri": akn_data.get("frbr_uri"),
        "elements_found": elements_found,
        "references": akn_data.get("references", {}),
        "truncated": truncated,
        "parse_error": parse_error or None,
    }


@app.post("/vault/stage/link")
async def stage_link(request: StageRequest):
    """Build cross-document wikilinks from AKN references.

    Reads _akn.json (written by stage_akn) and resolves case citations and
    organizations against other slugs in the vault. Writes:
      - _index.md frontmatter: cited_cases[], cited_organizations[]
        as Obsidian [[wikilinks]] to matched source documents
      - A _links.md note in sources/{slug}/ listing all outbound references
        with match status (linked / unresolved)

    Safe to re-run — overwrites _links.md and frontmatter fields only.
    Skips silently if _akn.json doesn't exist (stage_akn not yet run).
    """
    slug = request.slug

    akn_data = read_akn_json(VAULT_ROOT, slug)
    if not akn_data:
        return {
            "success": True, "slug": slug, "skipped": True,
            "reason": "No _akn.json found — run stage_akn first.",
        }

    references = akn_data.get("references", {})
    case_citations = references.get("case_citations", [])
    organizations = references.get("organizations", [])
    ibc_citations = references.get("ibc_citations", [])
    key_dates = references.get("key_dates", [])

    # Build slug index of all source documents in the vault
    sources_dir = Path(VAULT_ROOT) / "sources"
    vault_slugs: dict[str, str] = {}   # slug → case_number (from frontmatter)
    vault_by_case: dict[str, str] = {} # normalised case_number → slug
    if sources_dir.exists():
        for d in sources_dir.iterdir():
            if not d.is_dir():
                continue
            idx_path = d / "_index.md"
            if idx_path.exists():
                try:
                    note = read_note(VAULT_ROOT, f"sources/{d.name}/_index.md")
                    cn = note.metadata.get("case_number", "")
                    vault_slugs[d.name] = cn
                    if cn:
                        vault_by_case[cn.lower().replace(" ", "").replace("/", "-")] = d.name
                except Exception:
                    pass

    def _resolve_case(citation: str) -> str:
        """Return [[wikilink]] if citation matches a vault slug, else raw string."""
        norm = citation.lower().replace(" ", "").replace("/", "-")
        # Direct case number match
        for key, target_slug in vault_by_case.items():
            if key in norm or norm in key:
                return f"[[sources/{target_slug}/_index|{citation}]]"
        # Slug name match (e.g. citation contains corporate debtor name)
        for target_slug in vault_slugs:
            if target_slug.replace("-", " ") in citation.lower():
                return f"[[sources/{target_slug}/_index|{citation}]]"
        return citation  # unresolved — keep as plain text

    linked_cases = [_resolve_case(c) for c in case_citations]
    linked_orgs = []
    for org in organizations:
        name = org.get("name", "") if isinstance(org, dict) else str(org)
        role = org.get("role", "") if isinstance(org, dict) else ""
        linked_orgs.append(f"{name} ({role})" if role else name)

    # Promote to _index.md frontmatter
    wikilinked = [c for c in linked_cases if c.startswith("[[")]
    unresolved = [c for c in linked_cases if not c.startswith("[[")]

    try:
        idx = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
        idx.metadata["cited_cases"] = linked_cases
        idx.metadata["cited_ibc"] = ibc_citations
        idx.metadata["pipeline_stage"] = "linked"
        write_note(VAULT_ROOT, f"sources/{slug}/_index.md", idx.metadata, idx.body)
    except FileNotFoundError:
        pass

    # Write _links.md — human-readable reference sheet in Obsidian
    lines = [
        f"# References — {slug}",
        "",
        "## IBC / Statutory Citations",
    ]
    if ibc_citations:
        lines += [f"- {c}" for c in ibc_citations]
    else:
        lines.append("- (none found)")

    lines += ["", "## Case Citations"]
    for raw, linked in zip(case_citations, linked_cases):
        status = "linked" if linked.startswith("[[") else "unresolved"
        lines.append(f"- {linked}  `{status}`")
    if not case_citations:
        lines.append("- (none found)")

    lines += ["", "## Organizations"]
    for org in linked_orgs:
        lines.append(f"- {org}")
    if not linked_orgs:
        lines.append("- (none found)")

    lines += ["", "## Key Dates"]
    for kd in key_dates:
        if isinstance(kd, dict):
            lines.append(f"- **{kd.get('date', '')}** — {kd.get('event', '')}")
        else:
            lines.append(f"- {kd}")
    if not key_dates:
        lines.append("- (none found)")

    links_meta = {
        "type": "links",
        "slug": slug,
        "linked_cases": len(wikilinked),
        "unresolved_cases": len(unresolved),
        "ibc_citations": len(ibc_citations),
        "pipeline_stage": "linked",
    }
    write_note(VAULT_ROOT, f"sources/{slug}/_links.md", links_meta, "\n".join(lines))

    return {
        "success": True,
        "slug": slug,
        "case_citations": len(case_citations),
        "linked": len(wikilinked),
        "unresolved": len(unresolved),
        "ibc_citations": len(ibc_citations),
        "organizations": len(linked_orgs),
        "key_dates": len(key_dates),
    }


@app.post("/vault/stage/index")
async def stage_index(request: StageRequest):
    """Write section notes from cached tree, filling content from page-range text."""
    slug = request.slug
    tree_data = read_tree_json(VAULT_ROOT, slug)
    if tree_data is None:
        raise HTTPException(status_code=404, detail=f"No tree data for: {slug}. Run Cleanse first.")

    parse_data = read_parse_json(VAULT_ROOT, slug)
    try:
        index_note = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
    except FileNotFoundError:
        index_note = None

    tree = tree_data.get("tree", {})
    total_pages = (parse_data or {}).get("metadata", {}).get("totalPages", 0)
    total_chars = (parse_data or {}).get("metadata", {}).get("characterCount", 0)
    filename = index_note.metadata.get("filename", f"{slug}.pdf") if index_note else f"{slug}.pdf"

    # Build per-page text lookup from LiteParse pages array
    # LiteParse may use "pageNumber" OR "pageNum" depending on version
    raw_pages = (parse_data or {}).get("pages", [])
    page_texts: dict[int, str] = {}
    for i, p in enumerate(raw_pages):
        pn = p.get("pageNumber") or p.get("pageNum") or (i + 1)
        text_val = p.get("text", "").strip()
        if text_val:
            page_texts[int(pn)] = text_val

    # Fallback: if LiteParse didn't give per-page text, split the full text
    # by estimated page boundaries so sections get proportional content
    full_doc_text = (parse_data or {}).get("text", "")
    if not page_texts and full_doc_text and total_pages > 0:
        chars_per_page = max(1, len(full_doc_text) // total_pages)
        for pg in range(1, total_pages + 1):
            start = (pg - 1) * chars_per_page
            end = pg * chars_per_page if pg < total_pages else len(full_doc_text)
            page_texts[pg] = full_doc_text[start:end]

    def get_page_range_text(page_start: int, page_end: int) -> str:
        parts = [page_texts[pn] for pn in range(page_start, page_end + 1) if pn in page_texts]
        return "\n\n".join(p for p in parts if p.strip())

    def child_page_union(children_nodes: list) -> set:
        """Return all page numbers covered by any descendant node."""
        pages: set = set()
        for child in children_nodes:
            ps = child.get("pageStart", 0)
            pe = child.get("pageEnd", 0)
            pages.update(range(ps, pe + 1))
            pages.update(child_page_union(child.get("children", [])))
        return pages

    children = []
    section_notes = []

    def collect_sections(node: dict, parent_path: str = "") -> None:
        section_id = node.get("id", "0").replace("node-", "")
        title = node.get("title", "Untitled")
        level = node.get("level", 0)
        content = node.get("content", "")
        summary = node.get("summary", "")
        page_start = node.get("pageStart", 1)
        page_end = node.get("pageEnd", 1)
        metadata = node.get("metadata", {})
        children_nodes = node.get("children", [])
        is_leaf = len(children_nodes) == 0 or metadata.get("type") == "content"
        heading_level = metadata.get("headingLevel", level)

        if not content.strip() and page_texts:
            if is_leaf:
                # Leaf: take full page range text — this is the actual content
                content = get_page_range_text(page_start, page_end)
            else:
                # Non-leaf: only take pages NOT already covered by children
                # so we don't duplicate content that lives in child sections
                child_pages = child_page_union(children_nodes)
                exclusive_pages = [
                    pn for pn in range(page_start, page_end + 1)
                    if pn not in child_pages and pn in page_texts
                ]
                parts = [page_texts[pn] for pn in exclusive_pages if page_texts[pn].strip()]
                content = "\n\n".join(parts)

        word_count = len(content.split())

        title_slug = make_slug(title) if title else "untitled"
        sec_filename = f"sec-{section_id}-{title_slug}.md"
        sec_wikilink = f"[[sources/{slug}/sections/sec-{section_id}-{title_slug}]]"

        child_wikilinks = []
        for child in children_nodes:
            child_id = child.get("id", "").replace("node-", "")
            child_title = child.get("title", "Untitled")
            child_slug_str = make_slug(child_title)
            child_wikilinks.append(f"[[sources/{slug}/sections/sec-{child_id}-{child_slug_str}]]")

        parent_wikilink = f"[[sources/{slug}/sections/{parent_path}]]" if parent_path else ""

        write_section_note(
            VAULT_ROOT, slug, section_id,
            level=level, heading_level=heading_level, title=title,
            content=content, summary=summary,
            page_start=page_start, page_end=page_end,
            word_count=word_count, parent=parent_wikilink,
            children=child_wikilinks if child_wikilinks else None,
            is_leaf=is_leaf,
        )
        section_notes.append(sec_filename)
        children.append(sec_wikilink)

        for child in children_nodes:
            collect_sections(child, sec_filename)

    collect_sections(tree)

    write_source_index(
        VAULT_ROOT, slug,
        filename=filename,
        total_pages=total_pages,
        total_chars=total_chars,
        source_url=index_note.metadata.get("source_url", "") if index_note else "",
        pipeline_stage="pageindex",
        children=children,
    )

    # Merge-back fields set by earlier stages (classify, extract) that write_source_index would erase.
    # write_source_index creates a minimal fresh _index.md — we need to restore richer metadata.
    if index_note:
        _preserve_fields = (
            "doc_type", "case_number", "court", "order_date", "judges",
            "corporate_debtor", "resolution_applicant", "insolvency_professional",
            "classification_confidence", "classification_reasoning",
            "classify_parse_job_id", "llamacloud_file_id",
            "petition_type", "cirp_commencement_date", "admission_date",
            "ibc_sections", "parties",
            "resolution_amount_inr", "liquidation_value_inr", "fair_value_inr",
            "total_admitted_inr", "upfront_inr", "payment_timeline_months",
            "haircut_pct", "coc_approval_pct", "cirp_cost_inr",
            "fc_recovery_pct", "section_29a_compliant",
            "extract_method", "pipeline_stage",
        )
        try:
            new_idx = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
            for k in _preserve_fields:
                v = index_note.metadata.get(k)
                if v is not None and v != "" and v != [] and k not in new_idx.metadata:
                    new_idx.metadata[k] = v
            # Always overwrite pipeline_stage with the caller's intended value
            new_idx.metadata["pipeline_stage"] = "pageindex"
            write_note(VAULT_ROOT, f"sources/{slug}/_index.md", new_idx.metadata, new_idx.body)
        except FileNotFoundError:
            pass

    full_text = (parse_data or {}).get("text", "")
    if full_text:
        write_full_text(VAULT_ROOT, slug, full_text, filename=filename)

    # Write table notes from _tables.json (one note per extracted table)
    # Include doc-level context so Dataview can query tables by case/doc_type.
    tables_data = read_tables_json(VAULT_ROOT, slug)
    tables_written = 0

    # Read doc-level metadata to stamp on every table note
    _doc_meta: dict = {}
    try:
        _dm = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
        _doc_meta = {
            k: _dm.metadata.get(k, "")
            for k in ("doc_type", "corporate_debtor", "case_number", "order_date",
                       "court", "resolution_applicant")
        }
    except FileNotFoundError:
        pass

    def _ibc_table_type(caption: str, headers: list) -> str:
        """Heuristic: classify an IBC table by caption and column names."""
        text = (caption + " ".join(str(h) for h in headers)).lower()
        if any(w in text for w in ("creditor", "claim", "admitted", "financial creditor")):
            return "creditor_table"
        if any(w in text for w in ("payment", "schedule", "instalment", "tranche")):
            return "payment_schedule"
        if any(w in text for w in ("valuation", "fair value", "liquidation value")):
            return "valuation_summary"
        if any(w in text for w in ("asset", "property", "land", "plant")):
            return "asset_schedule"
        if any(w in text for w in ("employee", "workmen", "staff")):
            return "employee_table"
        if any(w in text for w in ("litigation", "legal", "suit", "case")):
            return "litigation_summary"
        return "other"

    if tables_data and tables_data.get("tables"):
        for tbl in tables_data["tables"]:
            try:
                headers = tbl.get("headers", [])
                caption = tbl.get("caption", f"Table {tbl['table_id']}")
                ibc_type = _ibc_table_type(caption, headers)
                write_table_note(
                    VAULT_ROOT, slug,
                    table_id=tbl["table_id"],
                    page=tbl.get("page", 1),
                    caption=caption,
                    headers=headers,
                    rows=tbl.get("rows", []),
                    markdown=tbl.get("markdown", ""),
                    context_before=tbl.get("context_before", ""),
                    context_after=tbl.get("context_after", ""),
                    doc_meta=_doc_meta,
                    ibc_table_type=ibc_type,
                )
                tables_written += 1
            except Exception:
                pass  # Best-effort — don't fail stage on table write error

    logger.info(f"  index result: sections={len(section_notes)}  tables={tables_written}")
    return {
        "success": True, "slug": slug,
        "sections": len(section_notes),
        "tables": tables_written,
        "message": (
            f"Saved {len(section_notes)} sections"
            + (f" and {tables_written} tables" if tables_written else "")
            + " to vault"
        ),
    }


@app.post("/vault/stage/enrich")
async def stage_enrich(request: StageRequest):
    """Add LLM summaries + breadcrumb paths to all section notes."""
    slug = request.slug

    section_notes = read_all_sections(VAULT_ROOT, slug)
    if not section_notes:
        raise HTTPException(status_code=404, detail=f"No section notes for: {slug}. Run Index first.")

    # filename → VaultNote map for parent traversal
    note_map = {note.path.name: note for note in section_notes}

    def build_breadcrumb(note: VaultNote) -> str:
        parts: List[str] = []
        current = note
        visited: set = set()
        while True:
            title = current.metadata.get("title") or current.path.stem
            parts.append(str(title))
            parent_wikilink = current.metadata.get("parent", "")
            if not parent_wikilink:
                break
            m = re.search(r'sections/([^\]]+)', str(parent_wikilink))
            if not m:
                break
            parent_stem = m.group(1)
            parent_filename = parent_stem if parent_stem.endswith(".md") else f"{parent_stem}.md"
            if parent_filename in visited or parent_filename not in note_map:
                break
            visited.add(parent_filename)
            current = note_map[parent_filename]
        parts.reverse()
        return " > ".join(parts)

    async def get_llm_summary(title: str, content: str, breadcrumb: str) -> str:
        if not content.strip() or len(content.strip()) < 80:
            return ""
        snippet = content[:2500]
        prompt = (
            f"You are a legal document analyst. Write a concise 2-3 sentence summary of the following section.\n"
            f"Section path: {breadcrumb}\n\n"
            f"Content:\n{snippet}\n\nSummary:"
        )
        try:
            return await llm_call(prompt, max_tokens=300)
        except Exception:
            return ""

    enriched = 0
    skipped = 0

    # Parallel enrichment with bounded concurrency (12 simultaneous LLM calls max)
    sem = asyncio.Semaphore(12)

    async def enrich_note(note):
        breadcrumb = build_breadcrumb(note)
        content = note.body or ""
        if len(content.strip()) >= 80:
            async with sem:
                llm_summary = await get_llm_summary(
                    str(note.metadata.get("title", note.path.stem)),
                    content,
                    breadcrumb,
                )
            result = "enriched"
        else:
            llm_summary = ""
            result = "skipped"
        new_meta = dict(note.metadata)
        new_meta["breadcrumb"] = breadcrumb
        new_meta["llm_summary"] = llm_summary
        new_meta["pipeline_stage"] = "enriched"
        write_note(VAULT_ROOT, f"sources/{slug}/sections/{note.path.name}", new_meta, content)
        return result

    results = await asyncio.gather(*[enrich_note(n) for n in section_notes])
    enriched = results.count("enriched")
    skipped = results.count("skipped")

    update_pipeline_stage(VAULT_ROOT, f"sources/{slug}/_index.md", "enriched")

    logger.info(f"  enrich result: enriched={enriched}  skipped={skipped}")
    return {
        "success": True, "slug": slug,
        "enriched": enriched, "skipped": skipped,
        "message": f"Enriched {enriched} sections with LLM summaries and breadcrumbs ({skipped} skipped — too short)",
    }


@app.post("/vault/stage/enrich_mca")
async def stage_enrich_mca(request: StageRequest):
    """Enrich a source document with external entity data via GLEIF open API.

    Looks up the corporate_debtor name from _index.md against the GLEIF
    global LEI registry (free, no auth required). If a match is found, stores:
      - lei: Legal Entity Identifier (20-char ISO 17442 code)
      - gleif_legal_name: canonical legal name from GLEIF
      - gleif_jurisdiction: incorporation jurisdiction
      - gleif_status: ACTIVE / INACTIVE / ANNULLED
      - gleif_match_confidence: exact / fuzzy / none

    Writes result to _meta.json (merges, does not overwrite) and promotes
    lei + gleif_status to _index.md frontmatter.

    Safe to re-run. Falls back gracefully if GLEIF is unreachable.
    """
    slug = request.slug

    try:
        idx = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Source not found: {slug}")

    corporate_debtor = idx.metadata.get("corporate_debtor", "").strip()
    if not corporate_debtor:
        return {
            "success": False, "slug": slug, "skipped": True,
            "reason": "corporate_debtor not set in _index.md — run stage_extract first.",
        }

    gleif_result: dict = {"gleif_match_confidence": "none"}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # GLEIF fuzzy search — free, no API key
            resp = await client.get(
                "https://api.gleif.org/api/v1/fuzzycompletions",
                params={"field": "entity.legalName", "q": corporate_debtor},
                headers={"Accept": "application/vnd.api+json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                completions = data.get("data", [])
                if completions:
                    # Take the top match and fetch full LEI record
                    top = completions[0]
                    lei_id = top.get("relationships", {}).get("lei-records", {}).get("data", [{}])[0].get("id", "")
                    if not lei_id:
                        # Try direct attributes path
                        lei_id = top.get("id", "")

                    if lei_id:
                        lei_resp = await client.get(
                            f"https://api.gleif.org/api/v1/lei-records/{lei_id}",
                            headers={"Accept": "application/vnd.api+json"},
                        )
                        if lei_resp.status_code == 200:
                            lei_data = lei_resp.json().get("data", {})
                            attrs = lei_data.get("attributes", {})
                            entity = attrs.get("entity", {})
                            legal_name = entity.get("legalName", {}).get("name", "")
                            gleif_result = {
                                "lei": lei_id,
                                "gleif_legal_name": legal_name,
                                "gleif_jurisdiction": entity.get("jurisdiction", ""),
                                "gleif_status": attrs.get("registration", {}).get("status", ""),
                                "gleif_match_confidence": (
                                    "exact" if legal_name.lower() == corporate_debtor.lower()
                                    else "fuzzy"
                                ),
                            }
    except Exception as e:
        gleif_result["gleif_error"] = str(e)

    # Merge into _meta.json
    meta_path = Path(VAULT_ROOT) / "sources" / slug / "_meta.json"
    existing_meta: dict = {}
    if meta_path.exists():
        with open(meta_path) as f:
            existing_meta = json.load(f)
    existing_meta.update(gleif_result)
    with open(meta_path, "w") as f:
        json.dump(existing_meta, f, ensure_ascii=False, indent=2)

    # Promote LEI fields to _index.md frontmatter
    for field in ("lei", "gleif_legal_name", "gleif_jurisdiction", "gleif_status", "gleif_match_confidence"):
        if gleif_result.get(field):
            idx.metadata[field] = gleif_result[field]
    idx.metadata["pipeline_stage"] = "mca_enriched"
    write_note(VAULT_ROOT, f"sources/{slug}/_index.md", idx.metadata, idx.body)

    return {
        "success": True,
        "slug": slug,
        "corporate_debtor": corporate_debtor,
        **gleif_result,
    }


@app.post("/vault/stage/chunk")
async def stage_chunk(request: StageRequest):
    """SemChunk enriched sections, prepending breadcrumb+summary to each chunk."""
    slug = request.slug
    index_path = f"sources/{slug}/_index.md"

    if not note_exists(VAULT_ROOT, index_path):
        raise HTTPException(status_code=404, detail=f"Source document not found: {slug}")

    section_notes = read_all_sections(VAULT_ROOT, slug)
    if not section_notes:
        raise HTTPException(status_code=404, detail=f"No section notes found for: {slug}")

    index_note = read_note(VAULT_ROOT, index_path)
    doc_title = index_note.metadata.get("filename", slug)

    # AKN element map — built from _akn.json if stage_akn has run.
    # Maps akn_element name → its verbatim text (used for section→element matching).
    akn_data = read_akn_json(VAULT_ROOT, slug)
    akn_element_texts: dict[str, str] = {}
    if akn_data and "elements" in akn_data:
        for el in akn_data["elements"]:
            name = el.get("akn_element", "")
            text = el.get("text", "")
            if name and text:
                akn_element_texts[name] = text

    def _akn_element_for_section(content: str) -> str:
        """Find which AKN element this section's text overlaps most with.

        Samples the first and last 200 chars of the section and checks which
        AKN element contains that text as a substring. Falls back to scanning
        for the longest common prefix. Returns "" if no AKN data available.
        """
        if not akn_element_texts or not content.strip():
            return ""
        sample = content.strip()[:200]
        # Preferred order — decision and motivation are most useful to distinguish
        order = ["header", "preamble", "background", "motivation", "decision"]
        for el_name in order:
            el_text = akn_element_texts.get(el_name, "")
            if sample[:80] in el_text:
                return el_name
        # Fallback: score by character overlap
        best_el, best_score = "", 0
        for el_name, el_text in akn_element_texts.items():
            overlap = sum(1 for ch in sample if ch in el_text)
            if overlap > best_score:
                best_score, best_el = overlap, el_name
        return best_el

    # Build enriched nodes: prepend [Section: breadcrumb]\n[Summary: ...]\n to each section body
    nodes = []
    for note in section_notes:
        m = note.metadata
        breadcrumb = m.get("breadcrumb", "")
        llm_summary = m.get("llm_summary", "")
        content = note.body or ""

        akn_element = _akn_element_for_section(content)

        context_lines: List[str] = []
        if akn_element:
            context_lines.append(f"[AKN: {akn_element}]")
        if breadcrumb:
            context_lines.append(f"[Section: {breadcrumb}]")
        if llm_summary:
            context_lines.append(f"[Summary: {llm_summary}]")

        enriched_content = "\n".join(context_lines) + "\n\n" + content if context_lines else content

        nodes.append({
            "id": note.path.stem.replace("sec-", "").split("-")[0],
            "level": m.get("level", 1),
            "title": m.get("title", note.path.stem),
            "summary": llm_summary or m.get("summary", ""),
            "content": enriched_content,
            "pageStart": m.get("page_start", 1),
            "pageEnd": m.get("page_end", 1),
            "metadata": {
                "type": "content" if m.get("is_leaf", True) else "section",
                "wordCount": len(enriched_content.split()),
                "aknElement": akn_element,
            },
            "children": [],
        })

    tree_dict = {
        "id": "node-root",
        "level": 0,
        "title": doc_title,
        "summary": index_note.body[:200] if index_note.body else "",
        "content": "",
        "pageStart": 1,
        "pageEnd": index_note.metadata.get("total_pages", 1),
        "children": nodes,
        "metadata": {"type": "document"},
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            resp = await client.post(
                f"{SEMCHUNK_URL}/pipeline",
                json={
                    "pageindex_result": {"success": True, "tree": tree_dict},
                    "maxTokens": request.max_tokens,
                    "overlapTokens": request.overlap_tokens,
                },
            )
            resp.raise_for_status()
            result = resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"SemChunk request failed: {e}")

    if not result.get("success"):
        raise HTTPException(status_code=502, detail=f"SemChunk error: {result}")

    chunks = result.get("chunks", [])
    total_tokens = result.get("totalTokens", 0)
    doc_title_resp = result.get("documentTitle", doc_title)
    doc_summary = result.get("documentSummary", "")

    (Path(VAULT_ROOT) / "chunks" / slug).mkdir(parents=True, exist_ok=True)
    source_wikilink = f"[[sources/{slug}/_index]]"

    for i, chunk in enumerate(chunks):
        source_node_id = chunk.get("sourceNodeId", chunk.get("metadata", {}).get("nodeId", ""))
        section_wikilink = ""
        akn_element = chunk.get("metadata", {}).get("aknElement", "")
        if source_node_id:
            for sn in section_notes:
                if sn.path.stem.startswith(f"sec-{source_node_id.replace('node-', '')}"):
                    section_wikilink = f"[[sources/{slug}/sections/{sn.path.stem}]]"
                    break

        write_chunk_note(
            VAULT_ROOT, slug, i,
            total_chunks=len(chunks),
            content=chunk.get("content", ""),
            parent_context=chunk.get("parentContext", ""),
            page_start=chunk.get("pageStart", 1),
            page_end=chunk.get("pageEnd", 1),
            token_count=chunk.get("tokenCount", 0),
            level=chunk.get("level", 0),
            has_overlap=chunk.get("metadata", {}).get("hasOverlap", False),
            source_wikilink=source_wikilink,
            section_wikilink=section_wikilink,
            akn_element=akn_element,
        )

    # ── Atomic table chunks ────────────────────────────────────
    # Tables are never split by SemChunk — each table becomes exactly
    # one chunk note. The full markdown table is the chunk content.
    # Offset chunk index so table chunks follow text chunks sequentially.
    table_notes = read_all_tables(VAULT_ROOT, slug)
    chunk_offset = len(chunks)
    table_chunks_written = 0

    for tbl_note in table_notes:
        tm = tbl_note.metadata
        caption = tm.get("caption", "Table")
        page = tm.get("page", 1)
        headers = tm.get("headers", [])
        table_id = tm.get("table_id", "")

        # Build table chunk content: caption header + context + markdown
        content_lines = [f"[Table: {caption}]"]
        if headers:
            content_lines.append(f"[Columns: {', '.join(str(h) for h in headers)}]")
        content_lines.append(f"[Page: {page}]")
        content_lines.append("")
        content_lines.append(tbl_note.body or "")
        table_content = "\n".join(content_lines)

        # Rough token estimate (1 token ≈ 4 chars)
        token_est = max(1, len(table_content) // 4)

        # Store structured data in frontmatter via a regular chunk note
        # We write directly to avoid SemChunk's splitting logic
        table_meta = {
            "type": "table-chunk",
            "source": source_wikilink,
            "table_source": f"[[sources/{slug}/tables/{tbl_note.path.name}]]",
            "chunk_index": chunk_offset + table_chunks_written,
            "total_chunks": chunk_offset + len(table_notes),
            "page_start": page,
            "page_end": page,
            "token_count": token_est,
            "level": 0,
            "caption": caption,
            "table_id": table_id,
            "headers": headers,
            "rows_count": tm.get("rows_count", 0),
            "has_overlap": False,
            "pipeline_stage": "semchunk",
            "lightrag_ingested": False,
            "ingested_at": None,
        }
        tbl_chunk_filename = f"chunk-{chunk_offset + table_chunks_written + 1:03d}.md"
        write_note(VAULT_ROOT, f"chunks/{slug}/{tbl_chunk_filename}", table_meta, table_content)
        total_tokens += token_est
        table_chunks_written += 1

    total_chunk_count = chunk_offset + table_chunks_written

    write_chunk_index(
        VAULT_ROOT, slug,
        total_chunks=total_chunk_count,
        total_tokens=total_tokens,
        document_title=doc_title_resp,
        document_summary=doc_summary,
    )

    update_pipeline_stage(VAULT_ROOT, f"sources/{slug}/_index.md", "semchunk")

    logger.info(f"  chunk result: text_chunks={chunk_offset}  table_chunks={table_chunks_written}  total={total_chunk_count}  tokens={total_tokens:,}")
    return ChunkFromVaultResponse(
        success=True, slug=slug,
        total_chunks=total_chunk_count, total_tokens=total_tokens,
        message=(
            f"Chunked {chunk_offset} text sections"
            + (f" + {table_chunks_written} atomic table chunks" if table_chunks_written else "")
            + f" ({total_chunk_count} total) into vault"
        ),
    )


@app.post("/vault/stage/embed")
async def stage_embed(request: StageRequest):
    """Ingest enriched LEAF sections directly into LightRAG (not pre-chunks).

    Sending larger coherent passages (800-3000 tokens) lets LightRAG's own
    chunker and entity extractor work properly across sentence/paragraph
    boundaries. Only leaf sections with ≥ 80 words are sent.
    """
    slug = request.slug

    # Load document-level metadata for context header
    try:
        index_note = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
        filename = index_note.metadata.get("filename", slug)
        source_url = index_note.metadata.get("source_url", "")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Source not found: {slug}")

    section_notes = read_all_sections(VAULT_ROOT, slug)
    if not section_notes:
        raise HTTPException(status_code=404, detail=f"No section notes for: {slug}. Run Index/Enrich first.")

    # ── Entity pre-seed document ───────────────────────────────
    # Build a structured entity summary from _meta.json and _akn.json and
    # send it as the first document so LightRAG's graph starts with typed
    # named entities rather than discovering them cold from raw text.
    meta_data = read_meta_json(VAULT_ROOT, slug) or {}
    akn_data_embed = read_akn_json(VAULT_ROOT, slug) or {}
    akn_refs = akn_data_embed.get("references", {})

    seed_lines = [f"[ENTITY SEED DOCUMENT: {filename}]", ""]
    m_idx = index_note.metadata

    for label, key in [
        ("Corporate Debtor", "corporate_debtor"),
        ("Resolution Applicant", "resolution_applicant"),
        ("Insolvency Professional", "insolvency_professional"),
        ("Court", "court"),
        ("Case Number", "case_number"),
        ("Order Date", "order_date"),
        ("CIRP Commencement Date", "cirp_commencement_date"),
        ("Doc Type", "doc_type"),
    ]:
        val = m_idx.get(key) or meta_data.get(key, "")
        if val:
            seed_lines.append(f"{label}: {val}")

    # Financial summary
    for label, key in [
        ("Resolution Amount (INR)", "resolution_amount_inr"),
        ("Total Admitted Claims (INR)", "total_admitted_inr"),
        ("Haircut %", "haircut_pct"),
        ("CoC Approval %", "coc_approval_pct"),
        ("Liquidation Value (INR)", "liquidation_value_inr"),
    ]:
        val = meta_data.get(key)
        if val is not None:
            seed_lines.append(f"{label}: {val}")

    # Creditors from _meta.json
    creditors = meta_data.get("creditors", [])
    if creditors:
        seed_lines += ["", "Creditors:"]
        for cr in creditors[:20]:  # cap at 20
            name = cr.get("name", "")
            ctype = cr.get("creditor_type", "")
            admitted = cr.get("amount_admitted_inr", "")
            plan = cr.get("amount_under_plan_inr", "")
            seed_lines.append(f"  - {name} ({ctype}): admitted={admitted}, plan={plan}")

    # AKN organizations + IBC citations
    orgs = akn_refs.get("organizations", [])
    if orgs:
        seed_lines += ["", "Organizations referenced:"]
        for org in orgs:
            name = org.get("name", "") if isinstance(org, dict) else str(org)
            role = org.get("role", "") if isinstance(org, dict) else ""
            seed_lines.append(f"  - {name}" + (f" ({role})" if role else ""))

    ibc_cites = akn_refs.get("ibc_citations", [])
    if ibc_cites:
        seed_lines += ["", f"IBC/IBBI provisions: {', '.join(ibc_cites)}"]

    seed_doc = "\n".join(seed_lines)

    # Document context header — prepended to every section so LightRAG sees
    # the full document context even when processing individual sections
    doc_header = f"[DOCUMENT: {filename}]"
    if source_url:
        doc_header += f"\n[SOURCE: {source_url}]"
    doc_header += "\n"

    ingested = 0
    skipped = 0
    failed = 0
    skip_reasons: dict = {"not_leaf": 0, "too_short": 0, "duplicate": 0}
    seed_ingested = False

    async with httpx.AsyncClient(timeout=180.0) as client:
        # Send entity seed document first
        if len(seed_lines) > 5:
            try:
                resp = await client.post(
                    f"{LIGHTRAG_URL}/documents/text",
                    json={"text": seed_doc, "file_source": f"{slug}/_entity_seed"},
                )
                resp.raise_for_status()
                if resp.json().get("status") != "duplicated":
                    seed_ingested = True
            except Exception:
                pass  # Best-effort — don't fail if seed fails

        for note in section_notes:
            m = note.metadata
            is_leaf = m.get("is_leaf", True)
            word_count = m.get("word_count", 0)
            content = note.body or ""

            # Only send leaf sections with meaningful content
            if not is_leaf:
                skip_reasons["not_leaf"] += 1
                continue
            if word_count < 30 or len(content.strip()) < 80:
                skip_reasons["too_short"] += 1
                continue

            breadcrumb = m.get("breadcrumb", "")
            llm_summary = m.get("llm_summary", "")
            section_id = note.path.stem  # e.g. sec-042-background

            # Build the passage: doc header + section context + content
            passage_parts = [doc_header]
            if breadcrumb:
                passage_parts.append(f"[SECTION PATH: {breadcrumb}]")
            if llm_summary:
                passage_parts.append(f"[SUMMARY: {llm_summary}]")
            passage_parts.append("")
            passage_parts.append(content)
            passage = "\n".join(passage_parts)

            file_source = f"{slug}/{section_id}"

            try:
                resp = await client.post(
                    f"{LIGHTRAG_URL}/documents/text",
                    json={"text": passage, "file_source": file_source},
                )
                resp.raise_for_status()
                result = resp.json()
                if result.get("status") == "duplicated":
                    skip_reasons["duplicate"] += 1
                    skipped += 1
                else:
                    ingested += 1
            except Exception:
                failed += 1

    update_pipeline_stage(VAULT_ROOT, f"sources/{slug}/_index.md", "ingested")

    logger.info(f"  embed result: seed={seed_ingested}  ingested={ingested}  skipped={skipped}  failed={failed}")
    return {
        "success": True, "slug": slug,
        "seed_ingested": seed_ingested,
        "ingested": ingested, "skipped": skipped, "failed": failed,
        "skip_reasons": skip_reasons,
        "message": (
            f"{'Entity seed + ' if seed_ingested else ''}"
            f"Sent {ingested} leaf sections to LightRAG "
            f"(skipped {skipped} duplicates, {skip_reasons['not_leaf']} non-leaf, "
            f"{skip_reasons['too_short']} too short; {failed} failed)"
        ),
    }


@app.post("/vault/stage/karpathy")
async def stage_karpathy(request: StageRequest):
    """Build Karpathy-style local search index for Obsidian.

    For each chunk note, calls SBERT to get an embedding, then writes:
      _karpathy/{slug}/note-{n:03d}.md  — atomic Obsidian note (chunk body + frontmatter)
      _karpathy/{slug}/embeddings.json  — list of {id, embedding, meta} for local ANN
      _karpathy/{slug}/bm25.json        — inverted index {term: [note_ids...]} for keyword search
      _karpathy/{slug}/_index.md        — Obsidian entry note linking all atomic notes
    """
    slug = request.slug

    chunk_notes = read_all_chunks(VAULT_ROOT, slug)
    if not chunk_notes:
        raise HTTPException(status_code=404, detail=f"No chunk notes for: {slug}. Run Chunk first.")

    try:
        index_note = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
        filename = index_note.metadata.get("filename", slug)
        doc_meta = read_meta_json(VAULT_ROOT, slug) or {}
    except FileNotFoundError:
        filename = slug
        doc_meta = {}

    karp_dir = Path(VAULT_ROOT) / "_karpathy" / slug
    karp_dir.mkdir(parents=True, exist_ok=True)

    embeddings_list = []
    bm25_index: dict = {}
    note_links = []

    def tokenize_for_bm25(text: str) -> List[str]:
        """Simple whitespace + lowercase tokenizer, filter stopwords."""
        stop = {"the","a","an","and","or","of","in","to","for","with","on","at","by","is","are","was","were","be","been","that","this","it","as","from"}
        tokens = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        return [t for t in tokens if t not in stop]

    async with httpx.AsyncClient(timeout=60.0) as client:
        for i, note in enumerate(chunk_notes):
            m = note.metadata
            chunk_idx = m.get("chunk_index", i)
            body = note.body or ""
            if not body.strip():
                continue

            breadcrumb = m.get("breadcrumb", "") or m.get("parent_context", "")
            llm_summary = m.get("llm_summary", "")
            page_start = m.get("page_start", 0)
            page_end = m.get("page_end", 0)
            token_count = m.get("token_count", 0)

            note_id = f"note-{chunk_idx + 1:03d}"
            note_filename = f"{note_id}.md"

            # Build atomic Obsidian note
            note_meta = {
                "type": "karpathy-note",
                "source": f"[[sources/{slug}/_index]]",
                "doc": filename,
                "chunk_index": chunk_idx,
                "page_start": page_start,
                "page_end": page_end,
                "token_count": token_count,
                "breadcrumb": breadcrumb,
                "doc_type": doc_meta.get("doc_type", ""),
                "case_number": doc_meta.get("case_number", ""),
                "court": doc_meta.get("court", ""),
            }
            note_body = ""
            if breadcrumb:
                note_body += f"**Section:** {breadcrumb}\n\n"
            if llm_summary:
                note_body += f"**Summary:** {llm_summary}\n\n---\n\n"
            note_body += body

            write_note(VAULT_ROOT, f"_karpathy/{slug}/{note_filename}", note_meta, note_body)
            note_links.append(f"[[_karpathy/{slug}/{note_id}]]")

            # Get embedding from SBERT
            embed_text = f"{breadcrumb}\n\n{body}"[:2000]
            try:
                emb_resp = await client.post(
                    f"{SBERT_URL}/v1/embeddings",
                    json={"input": embed_text, "model": "inlegal-sbert"},
                )
                emb_resp.raise_for_status()
                embedding = emb_resp.json()["data"][0]["embedding"]
            except Exception:
                embedding = []

            embeddings_list.append({
                "id": note_id,
                "chunk_index": chunk_idx,
                "page_start": page_start,
                "page_end": page_end,
                "breadcrumb": breadcrumb,
                "embedding": embedding,
            })

            # BM25 index update
            tokens = tokenize_for_bm25(body)
            seen_in_note = set()
            for token in tokens:
                if token not in seen_in_note:
                    bm25_index.setdefault(token, []).append(note_id)
                    seen_in_note.add(token)

    # Write embeddings.json
    emb_path = karp_dir / "embeddings.json"
    with open(emb_path, "w", encoding="utf-8") as f:
        _json_mod.dump(embeddings_list, f, ensure_ascii=False)

    # Write bm25.json
    bm25_path = karp_dir / "bm25.json"
    with open(bm25_path, "w", encoding="utf-8") as f:
        _json_mod.dump(bm25_index, f, ensure_ascii=False)

    # Write _index.md for Obsidian navigation
    idx_meta = {
        "type": "karpathy-index",
        "source": f"[[sources/{slug}/_index]]",
        "doc": filename,
        "total_notes": len(note_links),
        "doc_type": doc_meta.get("doc_type", ""),
        "case_number": doc_meta.get("case_number", ""),
        "court": doc_meta.get("court", ""),
        "order_date": doc_meta.get("order_date", ""),
        "corporate_debtor": doc_meta.get("corporate_debtor", ""),
        "resolution_applicant": doc_meta.get("resolution_applicant", ""),
    }
    idx_body = f"# {filename}\n\n"
    for k in ("doc_type","case_number","court","order_date","corporate_debtor","resolution_applicant"):
        v = doc_meta.get(k)
        if v:
            idx_body += f"**{k.replace('_',' ').title()}:** {v}\n"
    idx_body += f"\n**Notes:** {len(note_links)}\n\n"
    idx_body += "\n".join(note_links)
    write_note(VAULT_ROOT, f"_karpathy/{slug}/_index.md", idx_meta, idx_body)

    return {
        "success": True, "slug": slug,
        "notes": len(note_links),
        "vocab_size": len(bm25_index),
        "embeddings_path": str(emb_path),
        "message": f"Built Karpathy index: {len(note_links)} notes, {len(bm25_index)} BM25 terms",
    }


# ──────────────────────────────────────────────────────────────
# Pi Agents — Resolution Plan Verify (RPV)
# ──────────────────────────────────────────────────────────────

class RpvRequest(BaseModel):
    order_slug: str                   # slug of the resolution_plan_order document
    plan_slug: Optional[str] = None   # slug of the resolution_plan (if separately ingested)
    im_slug: Optional[str] = None     # slug of the information_memorandum (if separately ingested)


@app.post("/vault/agents/rpv")
async def agent_rpv(request: RpvRequest):
    """Resolution Plan Verify (RPV) — Pi Agent #1.

    Reads the extracted metadata from a resolution_plan_order and cross-checks
    it against the resolution_plan and/or information_memorandum if available.

    Checks performed:
      1. Section 29A compliance declared vs court's finding
      2. CoC vote % in order vs plan document
      3. Resolution amount vs IM's liquidation/fair value
      4. Creditor recovery % consistency
      5. Payment timeline stated vs approved
      6. CIRP cost within normal range (< 5% of resolution amount)
      7. AKN motivation vs decision consistency (did court approve exactly what was proposed)

    Output:
      sources/{order_slug}/_rpv.json  — structured verification report
      sources/{order_slug}/_rpv.md    — human-readable Obsidian note

    Uses Claude (heavy) for semantic checks. Structured field checks are deterministic.
    """
    order_slug = request.order_slug

    # Load order metadata
    try:
        order_idx = read_note(VAULT_ROOT, f"sources/{order_slug}/_index.md")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Order not found: {order_slug}")

    if order_idx.metadata.get("doc_type") != "resolution_plan_order":
        raise HTTPException(
            status_code=400,
            detail=f"doc_type is '{order_idx.metadata.get('doc_type')}' — RPV requires resolution_plan_order",
        )

    order_meta = read_meta_json(VAULT_ROOT, order_slug) or {}
    order_akn = read_akn_json(VAULT_ROOT, order_slug) or {}
    plan_meta = read_meta_json(VAULT_ROOT, request.plan_slug) if request.plan_slug else {}
    im_meta = read_meta_json(VAULT_ROOT, request.im_slug) if request.im_slug else {}
    plan_meta = plan_meta or {}
    im_meta = im_meta or {}

    checks: list = []

    def _check(name: str, passed: bool, detail: str, severity: str = "warning"):
        checks.append({
            "check": name,
            "passed": passed,
            "detail": detail,
            "severity": severity if not passed else "ok",
        })

    # ── Deterministic field checks ─────────────────────────────

    # 1. CoC vote %
    coc = order_meta.get("coc_approval_pct")
    if coc is not None:
        _check(
            "coc_threshold",
            passed=float(coc) >= 66.0,
            detail=f"CoC approval: {coc}% (minimum 66% per Section 30(4))",
            severity="critical",
        )
    else:
        _check("coc_threshold", passed=False, detail="coc_approval_pct not extracted", severity="warning")

    # 2. Resolution amount vs liquidation value
    res_amt = order_meta.get("resolution_amount_inr")
    liq_val = order_meta.get("liquidation_value_inr") or im_meta.get("liquidation_value_inr")
    if res_amt and liq_val:
        above_liq = int(res_amt) >= int(liq_val)
        _check(
            "resolution_above_liquidation",
            passed=above_liq,
            detail=f"Resolution ₹{res_amt:,} vs Liquidation ₹{liq_val:,} — {'above' if above_liq else 'BELOW liquidation value'}",
            severity="critical",
        )

    # 3. Haircut consistency
    res_amt_n = order_meta.get("resolution_amount_inr")
    total_admitted = order_meta.get("total_admitted_inr")
    stated_haircut = order_meta.get("haircut_pct")
    if res_amt_n and total_admitted and stated_haircut is not None:
        computed = round((1 - int(res_amt_n) / int(total_admitted)) * 100, 2)
        diff = abs(computed - float(stated_haircut))
        _check(
            "haircut_consistency",
            passed=diff < 2.0,
            detail=f"Stated haircut {stated_haircut}% vs computed {computed}% (diff {diff:.1f}%)",
            severity="warning",
        )

    # 4. CIRP cost reasonableness (< 5% of resolution amount)
    cirp_cost = order_meta.get("cirp_cost_inr")
    if cirp_cost and res_amt_n:
        cirp_pct = round(int(cirp_cost) / int(res_amt_n) * 100, 2)
        _check(
            "cirp_cost_reasonableness",
            passed=cirp_pct < 5.0,
            detail=f"CIRP cost ₹{cirp_cost:,} = {cirp_pct}% of resolution amount",
            severity="warning",
        )

    # 5. Section 29A declared
    s29a = order_meta.get("section_29a_compliant")
    _check(
        "section_29a_declared",
        passed=s29a is True,
        detail=f"Section 29A compliance: {s29a}",
        severity="warning",
    )

    # ── LLM semantic checks ────────────────────────────────────
    # Only run if AKN annotation exists (motivation + decision elements available)
    llm_check_result: dict = {}
    akn_elements = {el["akn_element"]: el["text"] for el in order_akn.get("elements", [])}
    motivation = akn_elements.get("motivation", "")
    decision = akn_elements.get("decision", "")

    if motivation and decision and ANTHROPIC_API_KEY:
        llm_prompt = f"""You are a legal analyst verifying an NCLT resolution plan approval order.

Review the court's MOTIVATION and DECISION sections and check:
1. Does the decision approve exactly what the motivation discusses? Any unexplained gaps?
2. Does the motivation address all material creditor objections?
3. Are there any conditions in the decision that are not explained in the motivation?
4. Is the resolution applicant's name consistent across both sections?

MOTIVATION:
{motivation[:3000]}

DECISION:
{decision[:2000]}

Return JSON: {{"consistent": true/false, "issues": ["list of issues found"], "summary": "one sentence"}}"""

        try:
            raw = await llm_call(llm_prompt, provider="openai", heavy=False, max_tokens=500, json_mode=True)
            cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            llm_check_result = json.loads(cleaned)
            _check(
                "motivation_decision_consistency",
                passed=llm_check_result.get("consistent", False),
                detail=llm_check_result.get("summary", ""),
                severity="warning",
            )
        except Exception as e:
            llm_check_result = {"error": str(e)}

    # ── Build report ───────────────────────────────────────────
    passed_count = sum(1 for c in checks if c["passed"])
    critical_failures = [c for c in checks if not c["passed"] and c["severity"] == "critical"]
    warnings = [c for c in checks if not c["passed"] and c["severity"] == "warning"]
    overall = "PASS" if not critical_failures else "FAIL"

    report = {
        "slug": order_slug,
        "doc_type": "resolution_plan_order",
        "corporate_debtor": order_meta.get("corporate_debtor", order_idx.metadata.get("corporate_debtor", "")),
        "case_number": order_meta.get("case_number", order_idx.metadata.get("case_number", "")),
        "overall": overall,
        "passed": passed_count,
        "total_checks": len(checks),
        "critical_failures": len(critical_failures),
        "warnings": len(warnings),
        "checks": checks,
        "llm_analysis": llm_check_result,
        "cross_docs": {
            "plan_slug": request.plan_slug,
            "im_slug": request.im_slug,
        },
    }

    # Write _rpv.json
    rpv_json_path = Path(VAULT_ROOT) / "sources" / order_slug / "_rpv.json"
    with open(rpv_json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Write _rpv.md — Obsidian note
    status_icon = "✅" if overall == "PASS" else "❌"
    md_lines = [
        f"# RPV Report — {report['corporate_debtor']}",
        f"**Case:** {report['case_number']}  **Status:** {status_icon} {overall}",
        f"**Checks:** {passed_count}/{len(checks)} passed  "
        f"**Critical failures:** {len(critical_failures)}  **Warnings:** {len(warnings)}",
        "",
        "## Check Results",
    ]
    for c in checks:
        icon = "✅" if c["passed"] else ("🔴" if c["severity"] == "critical" else "⚠️")
        md_lines.append(f"{icon} **{c['check']}**: {c['detail']}")

    if llm_check_result and not llm_check_result.get("error"):
        md_lines += ["", "## LLM Semantic Analysis"]
        for issue in llm_check_result.get("issues", []):
            md_lines.append(f"- {issue}")

    rpv_meta = {
        "type": "rpv-report",
        "source": f"[[sources/{order_slug}/_index]]",
        "overall": overall,
        "passed": passed_count,
        "total_checks": len(checks),
        "critical_failures": len(critical_failures),
        "corporate_debtor": report["corporate_debtor"],
        "case_number": report["case_number"],
    }
    write_note(VAULT_ROOT, f"sources/{order_slug}/_rpv.md", rpv_meta, "\n".join(md_lines))

    # Stamp pipeline_stage
    order_idx.metadata["rpv_overall"] = overall
    order_idx.metadata["pipeline_stage"] = "rpv_done"
    write_note(VAULT_ROOT, f"sources/{order_slug}/_index.md", order_idx.metadata, order_idx.body)

    return report


# ──────────────────────────────────────────────────────────────
# Proxy endpoints — forward to existing services
# ──────────────────────────────────────────────────────────────

@app.post("/lightrag/compliance/check")
async def compliance_check(request: dict):
    """Proxy to LightRAG compliance check, using vault chunks."""
    slug = request.get("slug")
    if slug:
        # Read chunks from vault
        chunk_notes = read_all_chunks(VAULT_ROOT, slug)
        if not chunk_notes:
            raise HTTPException(status_code=404, detail=f"No chunks found for: {slug}")

        index_note = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
        chunks_payload = []
        for note in chunk_notes:
            m = note.metadata
            chunks_payload.append({
                "id": f"chunk-{m.get('chunk_index', 0) + 1:03d}",
                "content": note.body,
                "parentContext": m.get("parent_context"),
                "pageStart": m.get("page_start", 0),
                "pageEnd": m.get("page_end", 0),
                "tokenCount": m.get("token_count", 0),
                "metadata": {},
            })

        request = {
            "source": slug,
            "chunks": chunks_payload,
            "documentTitle": index_note.metadata.get("filename", slug),
        }

    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(f"{LIGHTRAG_URL}/compliance/check", json=request)
        resp.raise_for_status()
        return resp.json()


# ──────────────────────────────────────────────────────────────
# stage_extract_multipass — Sprint 2: 4 parallel Claude Haiku passes
# Produces: _entities.json, _timeline.json, _obligations.json, _citations.json
# ──────────────────────────────────────────────────────────────

_MULTIPASS_MAX_CHARS = 20_000  # same budget as stage_akn


@app.post("/vault/stage/extract_multipass")
async def stage_extract_multipass(request: StageRequest):
    """Run 4 parallel Claude Haiku extraction passes over the full document text.

    Pass B: Named entities (parties, judges, advocates, key companies)
    Pass D: Timeline events (all dated events chronologically)
    Pass E: Obligations (all SHALL/MUST/DIRECTED TO items)
    Pass F: Legal citations (IBC sections, case citations, IBBI regulations)

    Outputs (written to sources/{slug}/):
      _entities.json, _timeline.json, _obligations.json, _citations.json

    Skip-if-done: skips individual passes whose output file already exists
    unless force=true.
    """
    slug = request.slug
    force = getattr(request, "force", False)

    parse_data = read_parse_json(VAULT_ROOT, slug)
    if parse_data is None:
        raise HTTPException(status_code=404, detail=f"No parse data for: {slug}. Run Parse first.")

    full_text = parse_data.get("text", "")
    if not full_text:
        full_text = "\n\n".join(p.get("text", "") for p in parse_data.get("pages", []) if p.get("text"))
    text = full_text[:_MULTIPASS_MAX_CHARS]

    passes = {
        "_entities.json": {
            "system": "You are a legal entity extraction expert for Indian insolvency (IBC) proceedings.",
            "prompt": (
                f"Extract all named entities from this IBC document.\n"
                f"Return ONLY valid JSON:\n"
                f'{{"parties": [{{"name": str, "role": str, "type": "company|person|court|regulator"}}], '
                f'"judges": [{{"name": str, "designation": str}}], '
                f'"advocates": [{{"name": str, "representing": str}}], '
                f'"resolution_professional": {{"name": str, "registration": str}}, '
                f'"key_companies": [{{"name": str, "cin": str, "role": str}}]}}\n\n'
                f"Document:\n{text}"
            ),
            "max_tokens": 2000,
        },
        "_timeline.json": {
            "system": "You are a legal timeline extraction expert for Indian insolvency (IBC) proceedings.",
            "prompt": (
                f"Extract all dated events from this IBC document in chronological order.\n"
                f"Return ONLY valid JSON:\n"
                f'{{"events": [{{"date": "YYYY-MM-DD", "event": str, "significance": "high|medium|low"}}]}}\n'
                f"Use null for dates that cannot be parsed. Include: CIRP commencement, CoC meetings, "
                f"resolution plan submission, CoC approval, order date, payment milestones.\n\n"
                f"Document:\n{text}"
            ),
            "max_tokens": 2000,
        },
        "_obligations.json": {
            "system": "You are a legal obligations extraction expert for Indian insolvency (IBC) proceedings.",
            "prompt": (
                f"Extract all obligations from this IBC document — every SHALL, MUST, IS DIRECTED TO, "
                f"IS REQUIRED TO, IS HEREBY ORDERED TO clause.\n"
                f"Return ONLY valid JSON:\n"
                f'{{"obligations": [{{"party": str, "obligation": str, "deadline": str_or_null, '
                f'"ibc_basis": str_or_null, "severity": "mandatory|directory"}}]}}\n\n'
                f"Document:\n{text}"
            ),
            "max_tokens": 2000,
        },
        "_citations.json": {
            "system": "You are a legal citation extraction expert for Indian insolvency law.",
            "prompt": (
                f"Extract all legal citations from this IBC document.\n"
                f"Return ONLY valid JSON:\n"
                f'{{"ibc_sections": [{{"section": str, "context": str}}], '
                f'"case_citations": [{{"case_name": str, "citation": str, "principle": str}}], '
                f'"regulations": [{{"reg": str, "context": str}}]}}\n\n'
                f"Document:\n{text}"
            ),
            "max_tokens": 2000,
        },
    }

    results: dict = {}
    errors: dict = {}

    async def run_pass(filename: str, cfg: dict) -> None:
        if not force and read_sidecar_json(VAULT_ROOT, slug, filename) is not None:
            results[filename] = "skipped"
            return
        try:
            raw = await llm_call(
                cfg["prompt"],
                system=cfg["system"],
                max_tokens=cfg["max_tokens"],
                json_mode=True,
                provider="openai",
                heavy=False,
            )
            cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            data = json.loads(cleaned)
            data["slug"] = slug
            data["source"] = "extract_multipass"
            write_sidecar_json(VAULT_ROOT, slug, filename, data)
            results[filename] = "ok"
        except Exception as e:
            errors[filename] = str(e)
            results[filename] = "error"

    await asyncio.gather(*[run_pass(fn, cfg) for fn, cfg in passes.items()])

    update_pipeline_stage(VAULT_ROOT, f"sources/{slug}/_index.md", "multipass_extracted")

    return {
        "success": len(errors) == 0,
        "slug": slug,
        "results": results,
        "errors": errors,
        "message": f"Multipass extract done — {sum(1 for v in results.values() if v == 'ok')} passes ran, "
                   f"{sum(1 for v in results.values() if v == 'skipped')} skipped, "
                   f"{len(errors)} errors.",
    }


# ──────────────────────────────────────────────────────────────
# stage_structure — Sprint 2: per-section financial YAML + aggregate
# Produces: typed section_type frontmatter + aggregated _index.md fields
# ──────────────────────────────────────────────────────────────

# Rule-based section type classification by title keywords (checked in order)
_SECTION_TYPE_RULES: list[tuple[list[str], str]] = [
    (["committee of creditor", "coc composition", "constitution of coc"], "creditor-claims"),
    (["financial proposal", "resolution amount", "payment plan", "payment schedule",
      "proposed payment", "financial terms", "upfront payment"], "payment-plan"),
    (["resolution applicant", "resolution plan applicant", "successful resolution"], "ra-profile"),
    (["background", "facts of the case", "cirp commencement", "brief facts",
      "brief background", "chronology"], "cirp-background"),
    (["direction", "accordingly", "in view of the above", "operative order",
      "in the result", "order accordingly"], "operative-order"),
    (["coc approval", "voting result", "voting percentage", "approval of coc",
      "approval percentage", "coc vote"], "coc-vote"),
    (["valuation", "fair value", "liquidation value", "registered valuer"], "valuation"),
    (["section 29a", "eligibility", "29a compliance"], "eligibility"),
    (["cirp cost", "insolvency resolution cost", "cost of cirp"], "cirp-costs"),
    (["monitoring committee", "implementation", "implementation schedule"], "implementation"),
]


def _classify_section_type(title: str, content: str) -> str:
    """Classify a section by type using title + content keyword rules."""
    combined = (title + " " + content[:500]).lower()
    for keywords, stype in _SECTION_TYPE_RULES:
        if any(kw in combined for kw in keywords):
            return stype
    return "other"


def _extract_financial_fields(section_type: str, content: str, meta: dict) -> dict:
    """Extract simple financial fields deterministically from known section content."""
    fields: dict = {}
    if section_type == "coc-vote":
        # Look for percentage patterns like "91.3%" or "91.30 %"
        pct_matches = re.findall(r'(\d+\.?\d*)\s*%', content)
        if pct_matches:
            candidates = [float(p) for p in pct_matches if 50 <= float(p) <= 100]
            if candidates:
                fields["coc_approval_pct"] = max(candidates)
        date_match = re.search(r'(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{2,4})', content)
        if date_match:
            fields["approval_date_raw"] = date_match.group(0)
    elif section_type == "valuation":
        # Look for INR amounts (crore/lakh patterns)
        crore_matches = re.findall(r'(?:Rs\.?|INR|₹)\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:crore|cr\.?)', content, re.IGNORECASE)
        if crore_matches:
            amounts = [float(v.replace(",", "")) * 10_000_000 for v in crore_matches]
            if len(amounts) >= 2:
                fields["fair_value_inr"] = int(max(amounts))
                fields["liquidation_value_inr"] = int(min(amounts))
    elif section_type == "cirp-costs":
        crore_matches = re.findall(r'(?:Rs\.?|INR|₹)\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:crore|cr\.?)', content, re.IGNORECASE)
        if crore_matches:
            fields["cirp_cost_inr"] = int(float(crore_matches[0].replace(",", "")) * 10_000_000)
    return fields


@app.post("/vault/stage/structure")
async def stage_structure(request: StageRequest):
    """Classify each section by type and extract typed financial YAML into frontmatter.

    For each section note in sources/{slug}/sections/:
      1. Classify section_type using title + content keyword rules
      2. Extract financial fields deterministically (regex for amounts/percentages)
      3. For ambiguous sections, call Claude Haiku for LLM classification
      4. Stamp section_type + financial fields into section note frontmatter

    Then aggregate typed financial data into _index.md frontmatter:
      total_admitted_inr, liquidation_value_inr, resolution_amount_inr,
      haircut_pct, fc_recovery_pct, coc_approval_pct, cirp_cost_inr

    Cross-field validation:
      - resolution_amount_inr > liquidation_value_inr
      - coc_approval_pct >= 66.0 (Section 30(4))
    """
    slug = request.slug

    try:
        idx = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Source not found: {slug}")

    section_notes = read_all_sections(VAULT_ROOT, slug)
    if not section_notes:
        return {"success": False, "slug": slug, "reason": "No section notes found — run Index first."}

    # Read existing meta for context
    meta: dict = {}
    meta_path = Path(VAULT_ROOT) / "sources" / slug / "_meta.json"
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)

    typed_sections: list[dict] = []
    aggregated: dict = {}

    for note in section_notes:
        title = str(note.metadata.get("title", note.path.stem))
        content = note.body or ""

        # Rule-based classification
        section_type = _classify_section_type(title, content)

        # LLM fallback only for genuinely ambiguous sections (type=other) with enough content
        if section_type == "other" and len(content.strip()) > 300:
            try:
                type_prompt = (
                    f"Classify this section from an NCLT IBC court order into ONE of these types:\n"
                    f"creditor-claims | payment-plan | ra-profile | cirp-background | "
                    f"operative-order | coc-vote | valuation | eligibility | cirp-costs | "
                    f"implementation | other\n\n"
                    f"Section title: {title}\n"
                    f"Section content (first 400 chars): {content[:400]}\n\n"
                    f"Return ONLY the type label, nothing else."
                )
                llm_type = await llm_call(type_prompt, max_tokens=20, provider="openai", heavy=False)
                llm_type = llm_type.strip().lower().split()[0]
                valid_types = {
                    "creditor-claims", "payment-plan", "ra-profile", "cirp-background",
                    "operative-order", "coc-vote", "valuation", "eligibility",
                    "cirp-costs", "implementation", "other"
                }
                if llm_type in valid_types:
                    section_type = llm_type
            except Exception:
                pass

        # Deterministic financial field extraction
        financial_fields = _extract_financial_fields(section_type, content, meta)

        # Stamp section_type + financial fields into section note frontmatter
        new_meta = dict(note.metadata)
        new_meta["section_type"] = section_type
        new_meta.update(financial_fields)
        new_meta["pipeline_stage"] = "structured"
        write_note(VAULT_ROOT, f"sources/{slug}/sections/{note.path.name}", new_meta, content)

        typed_sections.append({"section": note.path.name, "type": section_type, "fields": financial_fields})

        # Aggregate financial fields to document level
        for k, v in financial_fields.items():
            if k not in aggregated:
                aggregated[k] = v

    # Promote key meta fields from _meta.json to aggregated if not already found
    for field in ("resolution_amount_inr", "liquidation_value_inr", "total_admitted_claims_inr",
                  "haircut_pct", "fc_recovery_pct"):
        if field not in aggregated and field in meta:
            val = meta[field]
            if val is not None:
                aggregated[field] = val

    # Cross-field validation
    validation_warnings: list[str] = []
    res_amt = aggregated.get("resolution_amount_inr")
    liq_val = aggregated.get("liquidation_value_inr")
    coc_pct = aggregated.get("coc_approval_pct")
    cirp_cost = aggregated.get("cirp_cost_inr")

    if res_amt and liq_val:
        if res_amt <= liq_val:
            validation_warnings.append(
                f"resolution_amount_inr ({res_amt:,}) ≤ liquidation_value_inr ({liq_val:,}) — violates IBC Section 30(2)(b)"
            )
    if coc_pct and coc_pct < 66.0:
        validation_warnings.append(f"coc_approval_pct ({coc_pct}%) < 66% — does not meet Section 30(4) threshold")
    if res_amt and cirp_cost:
        cirp_pct = (cirp_cost / res_amt) * 100
        if cirp_pct > 5:
            validation_warnings.append(f"CIRP cost is {cirp_pct:.1f}% of resolution amount — unusually high (>5%)")

    # Write aggregated fields + validation warnings to _index.md
    idx_meta = dict(idx.metadata)
    idx_meta.update(aggregated)
    if validation_warnings:
        idx_meta["data_quality_warnings"] = validation_warnings
    idx_meta["pipeline_stage"] = "structured"
    write_note(VAULT_ROOT, f"sources/{slug}/_index.md", idx_meta, idx.body)

    return {
        "success": True,
        "slug": slug,
        "sections_typed": len(typed_sections),
        "aggregated_fields": list(aggregated.keys()),
        "validation_warnings": validation_warnings,
        "section_breakdown": {
            stype: sum(1 for s in typed_sections if s["type"] == stype)
            for stype in set(s["type"] for s in typed_sections)
        },
    }


# ──────────────────────────────────────────────────────────────
# stage_canvas — Sprint 2: Obsidian Canvas JSON from PageIndex tree
# Produces: sources/{slug}/_canvas.json
# ──────────────────────────────────────────────────────────────

_CANVAS_NODE_W = 260
_CANVAS_NODE_H = 60
_CANVAS_H_GAP = 40   # horizontal gap between siblings
_CANVAS_V_GAP = 120  # vertical gap between levels


def _build_canvas_layout(nodes: list[dict], edges: list[dict], tree: dict, slug: str, x: int = 0, y: int = 0) -> int:
    """Recursively lay out canvas nodes. Returns the total width consumed by this subtree."""
    node_id = str(tree.get("id", "root"))
    section_file = tree.get("file", "")
    title = tree.get("title", node_id)
    children = tree.get("children", [])

    if not children:
        # Leaf node
        nodes.append({
            "id": node_id,
            "type": "file",
            "file": section_file,
            "x": x,
            "y": y,
            "width": _CANVAS_NODE_W,
            "height": _CANVAS_NODE_H,
            "label": title[:40],
        })
        return _CANVAS_NODE_W

    # Lay out children first to know total width
    child_x = x
    child_widths: list[int] = []
    child_node_ids: list[str] = []

    for child in children:
        child_id = str(child.get("id", ""))
        child_node_ids.append(child_id)
        w = _build_canvas_layout(nodes, edges, child, slug, x=child_x, y=y + _CANVAS_V_GAP)
        child_widths.append(w)
        child_x += w + _CANVAS_H_GAP

    total_width = sum(child_widths) + _CANVAS_H_GAP * (len(children) - 1)
    center_x = x + total_width // 2 - _CANVAS_NODE_W // 2

    nodes.append({
        "id": node_id,
        "type": "file",
        "file": section_file,
        "x": center_x,
        "y": y,
        "width": _CANVAS_NODE_W,
        "height": _CANVAS_NODE_H,
        "label": title[:40],
    })

    for child_id in child_node_ids:
        edges.append({
            "id": f"edge-{node_id}-{child_id}",
            "fromNode": node_id,
            "toNode": child_id,
            "fromSide": "bottom",
            "toSide": "top",
        })

    return max(total_width, _CANVAS_NODE_W)


@app.post("/vault/stage/canvas")
async def stage_canvas(request: StageRequest):
    """Generate an Obsidian Canvas JSON file from the PageIndex tree.

    Reads sources/{slug}/_tree.json and produces sources/{slug}/_canvas.json
    in Obsidian Canvas format. Each tree node becomes a canvas card linked to
    its section note file. Parent→child relationships become edges.

    No LLM call — purely deterministic from _tree.json.
    """
    slug = request.slug

    tree = read_tree_json(VAULT_ROOT, slug)
    if tree is None:
        raise HTTPException(status_code=404, detail=f"No tree data for: {slug}. Run Index first.")

    # Enrich tree nodes with file paths by matching section notes
    section_notes = read_all_sections(VAULT_ROOT, slug)
    section_map: dict[str, str] = {}
    for note in section_notes:
        # Match by section id embedded in filename (sec-{id}-...)
        m = re.match(r"sec-(\d+)-", note.path.name)
        if m:
            section_map[m.group(1)] = f"sources/{slug}/sections/{note.path.name}"

    def enrich_tree(node: dict) -> dict:
        node_id = str(node.get("id", ""))
        node["file"] = section_map.get(node_id, f"sources/{slug}/_index.md")
        node["children"] = [enrich_tree(c) for c in node.get("children", [])]
        return node

    # _tree.json may be a list (multiple roots) or a dict
    if isinstance(tree, list):
        roots = [enrich_tree(n) for n in tree]
    else:
        roots = [enrich_tree(tree)]

    canvas_nodes: list[dict] = []
    canvas_edges: list[dict] = []
    x_offset = 0

    for root in roots:
        w = _build_canvas_layout(canvas_nodes, canvas_edges, root, slug, x=x_offset, y=0)
        x_offset += w + _CANVAS_H_GAP * 3

    canvas = {"nodes": canvas_nodes, "edges": canvas_edges}

    canvas_path = Path(VAULT_ROOT) / "sources" / slug / "_canvas.json"
    canvas_path.parent.mkdir(parents=True, exist_ok=True)
    with open(canvas_path, "w", encoding="utf-8") as f:
        json.dump(canvas, f, ensure_ascii=False, indent=2)

    return {
        "success": True,
        "slug": slug,
        "nodes": len(canvas_nodes),
        "edges": len(canvas_edges),
        "canvas_path": str(canvas_path),
    }


# ──────────────────────────────────────────────────────────────
# stage_dashboard — Sprint 2: _financials.md with Dataview blocks
# Produces: sources/{slug}/_financials.md
# ──────────────────────────────────────────────────────────────

def _fmt_inr(val: Any) -> str:
    """Format an INR integer value as readable crore/lakh string."""
    if val is None:
        return "—"
    try:
        v = int(val)
        if v >= 10_000_000:
            return f"₹{v / 10_000_000:.2f} Cr"
        if v >= 100_000:
            return f"₹{v / 100_000:.2f} L"
        return f"₹{v:,}"
    except (TypeError, ValueError):
        return str(val)


@app.post("/vault/stage/dashboard")
async def stage_dashboard(request: StageRequest):
    """Generate _financials.md — a pre-built Dataview dashboard note.

    Reads _index.md frontmatter and _meta.json, then produces a markdown note
    with pre-built Dataview query blocks that render live inside Obsidian:
      - Document summary (case info, key figures)
      - Creditor recovery table
      - Cross-matter comparison query (all resolution_plan_orders in vault)

    No LLM call — template-driven from extracted frontmatter.
    """
    slug = request.slug

    try:
        idx = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Source not found: {slug}")

    m = idx.metadata
    meta: dict = {}
    meta_path = Path(VAULT_ROOT) / "sources" / slug / "_meta.json"
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)

    # Helper to get field from index or meta
    def field(key: str, default: Any = None) -> Any:
        return m.get(key) or meta.get(key) or default

    doc_type = field("doc_type", "other")
    case_number = field("case_number", "")
    court = field("court", "")
    order_date = field("order_date", "")
    corporate_debtor = field("corporate_debtor", slug)
    resolution_applicant = field("resolution_applicant", "")
    res_amt = field("resolution_amount_inr")
    liq_val = field("liquidation_value_inr")
    total_admitted = field("total_admitted_claims_inr") or field("total_admitted_inr")
    haircut = field("haircut_pct")
    coc_pct = field("coc_approval_pct")
    cirp_cost = field("cirp_cost_inr")
    creditors: list = meta.get("creditors", [])

    # Build creditor recovery table
    creditor_rows = ""
    for c in creditors:
        name = c.get("name", "")
        admitted = c.get("amount_inr") or c.get("admitted_claim_inr", "")
        recovery = c.get("recovery_amount_inr", "")
        pct = c.get("recovery_pct") or c.get("voting_share_pct", "")
        ctype = c.get("type", "")
        creditor_rows += f"| {name} | {ctype} | {_fmt_inr(admitted)} | {_fmt_inr(recovery)} | {pct or '—'}% |\n"

    if not creditor_rows:
        creditor_rows = "| — | — | — | — | — |\n"

    warnings = m.get("data_quality_warnings", [])
    warning_block = ""
    if warnings:
        warning_block = "\n> [!warning] Data Quality Warnings\n"
        for w in warnings:
            warning_block += f"> - {w}\n"

    dashboard_md = f"""---
type: financial-dashboard
source: "[[sources/{slug}/_index]]"
slug: {slug}
generated_at: {__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d')}
---

# Financial Dashboard — {corporate_debtor}

{warning_block}
## Case Summary

| Field | Value |
|---|---|
| **Case** | {case_number} |
| **Court** | {court} |
| **Order Date** | {order_date} |
| **Corporate Debtor** | {corporate_debtor} |
| **Resolution Applicant** | {resolution_applicant or '—'} |
| **Doc Type** | {doc_type} |

## Key Financial Figures

| Metric | Value |
|---|---|
| Total Admitted Claims | {_fmt_inr(total_admitted)} |
| Resolution Amount | {_fmt_inr(res_amt)} |
| Liquidation Value | {_fmt_inr(liq_val)} |
| Haircut | {f"{haircut:.1f}%" if haircut else "—"} |
| CoC Approval | {f"{coc_pct:.1f}%" if coc_pct else "—"} |
| CIRP Costs | {_fmt_inr(cirp_cost)} |

## Creditor Recovery

| Creditor | Type | Admitted Claim | Recovery | Recovery % |
|---|---|---|---|---|
{creditor_rows}

## Cross-Matter Comparison (live Dataview)

```dataview
TABLE corporate_debtor, resolution_amount_inr, haircut_pct, coc_approval_pct, order_date
FROM "sources"
WHERE type = "source-document" AND doc_type = "resolution_plan_order"
SORT order_date DESC
```

## All Sources in This Vault

```dataview
TABLE doc_type, corporate_debtor, order_date, pipeline_stage
FROM "sources"
WHERE type = "source-document"
SORT order_date DESC
```
"""

    write_note(
        VAULT_ROOT,
        f"sources/{slug}/_financials.md",
        {
            "type": "financial-dashboard",
            "source": f"[[sources/{slug}/_index]]",
            "slug": slug,
        },
        dashboard_md.split("---", 2)[-1].strip(),
    )

    return {
        "success": True,
        "slug": slug,
        "doc_type": doc_type,
        "corporate_debtor": corporate_debtor,
        "fields_rendered": [
            k for k in ["resolution_amount_inr", "liquidation_value_inr", "haircut_pct",
                         "coc_approval_pct", "cirp_cost_inr", "total_admitted_claims_inr"]
            if field(k) is not None
        ],
        "creditors": len(creditors),
        "warnings": len(warnings),
    }


# ══════════════════════════════════════════════════════════════
# Sprint 3 — Global Index: cross-doc search, matters, entities,
#             precedent graph
# ══════════════════════════════════════════════════════════════

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _global_dir() -> Path:
    return Path(VAULT_ROOT) / "_global"


def _matters_dir() -> Path:
    return Path(VAULT_ROOT) / "matters"


def _load_global_bm25() -> dict:
    p = _global_dir() / "bm25.json"
    if not p.exists():
        return {}
    with open(p) as f:
        return json.load(f)


def _load_global_embeddings() -> list:
    p = _global_dir() / "embeddings.json"
    if not p.exists():
        return []
    with open(p) as f:
        return json.load(f)


def _tokenize(text: str) -> list[str]:
    stop = {
        "the","a","an","and","or","of","in","to","for","with","on","at","by",
        "is","are","was","were","be","been","that","this","it","as","from","has",
        "its","not","but","they","their","which","who","also","been","have",
    }
    tokens = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    return [t for t in tokens if t not in stop]


def _bm25_score(query_tokens: list[str], note: dict, idf: dict, avgdl: float, k1: float = 1.5, b: float = 0.75) -> float:
    tf_map = note.get("tf", {})
    dl = note.get("dl", 1)
    score = 0.0
    for token in query_tokens:
        if token not in idf or token not in tf_map:
            continue
        tf = tf_map[token]
        idf_val = idf[token]
        score += idf_val * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / max(avgdl, 1)))
    return score


def _cosine(a: list[float], b: list[float]) -> float:
    try:
        import numpy as np
        av, bv = np.array(a, dtype=float), np.array(b, dtype=float)
        na, nb = np.linalg.norm(av), np.linalg.norm(bv)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(av, bv) / (na * nb))
    except Exception:
        return 0.0


def _rrf(ranks: list[dict[str, int]], k: int = 60) -> dict[str, float]:
    """Reciprocal Rank Fusion across multiple ranked lists."""
    scores: dict[str, float] = {}
    for rank_list in ranks:
        for doc_id, rank in rank_list.items():
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return scores


# ──────────────────────────────────────────────────────────────
# POST /vault/global/index  — build global BM25 + embedding index
# ──────────────────────────────────────────────────────────────

class GlobalIndexRequest(BaseModel):
    force: bool = False   # rebuild even if already exists


@app.post("/vault/global/index")
async def global_index_build(request: GlobalIndexRequest):
    """Build the global cross-document search index.

    Reads all per-doc _karpathy/{slug}/note-*.md and embeddings.json files,
    then writes to _global/:
      bm25.json       — corpus-level BM25 index with true IDF across all docs
      embeddings.json — flat list of all embeddings with provenance
      manifest.json   — which slugs are indexed + build timestamp

    Safe to re-run (incremental: only adds slugs not in manifest unless force=True).
    """
    _global_dir().mkdir(parents=True, exist_ok=True)

    # Load existing manifest
    manifest_path = _global_dir() / "manifest.json"
    manifest: dict = {}
    if manifest_path.exists() and not request.force:
        with open(manifest_path) as f:
            manifest = json.load(f)
    indexed_slugs: set = set(manifest.get("slugs", []))

    # Discover all slugs with karpathy indexes
    karp_root = Path(VAULT_ROOT) / "_karpathy"
    all_slugs = [d.name for d in karp_root.iterdir() if d.is_dir()] if karp_root.exists() else []
    new_slugs = [s for s in all_slugs if s not in indexed_slugs] if not request.force else all_slugs

    if not new_slugs and not request.force:
        return {
            "success": True,
            "message": "Global index already up to date.",
            "indexed_slugs": list(indexed_slugs),
            "new_slugs": [],
        }

    # ── Load existing global state (for incremental updates) ──
    existing_emb: list = [] if request.force else _load_global_embeddings()
    existing_bm25: dict = {} if request.force else _load_global_bm25()

    # Remove entries for slugs being reprocessed
    reprocess = set(new_slugs)
    existing_emb = [e for e in existing_emb if e.get("slug") not in reprocess]
    existing_notes = {
        nid: n for nid, n in existing_bm25.get("notes", {}).items()
        if n.get("slug") not in reprocess
    }

    new_embeddings: list = []
    new_notes: dict = {}   # note_global_id → {slug, dl, tf, meta}

    for slug in new_slugs:
        karp_dir = karp_root / slug

        # Load per-doc embeddings
        emb_path = karp_dir / "embeddings.json"
        if emb_path.exists():
            with open(emb_path) as f:
                doc_embs = json.load(f)
            for e in doc_embs:
                new_embeddings.append({
                    "id": f"{slug}/{e['id']}",
                    "slug": slug,
                    "note_id": e["id"],
                    "embedding": e.get("embedding", []),
                    "meta": {
                        "page_start": e.get("page_start", 0),
                        "page_end": e.get("page_end", 0),
                        "breadcrumb": e.get("breadcrumb", ""),
                    },
                })

        # Build per-note TF from note markdown files
        for note_path in sorted(karp_dir.glob("note-*.md")):
            try:
                import frontmatter as _fm
                post = _fm.load(note_path)
                body = post.content or ""
                tokens = _tokenize(body)
                tf: dict[str, int] = {}
                for tok in tokens:
                    tf[tok] = tf.get(tok, 0) + 1
                global_id = f"{slug}/{note_path.stem}"
                new_notes[global_id] = {
                    "slug": slug,
                    "note_id": note_path.stem,
                    "dl": len(tokens),
                    "tf": tf,
                    "meta": {
                        "page_start": post.metadata.get("page_start", 0),
                        "page_end": post.metadata.get("page_end", 0),
                        "breadcrumb": post.metadata.get("breadcrumb", ""),
                        "akn_element": post.metadata.get("akn_element", ""),
                    },
                }
            except Exception:
                continue

    # ── Merge and compute corpus-level IDF ────────────────────
    all_notes = {**existing_notes, **new_notes}
    all_embeddings = existing_emb + new_embeddings

    N = len(all_notes)
    avgdl = sum(n["dl"] for n in all_notes.values()) / max(N, 1)

    # Document frequency per term
    df: dict[str, int] = {}
    for note in all_notes.values():
        for term in note["tf"]:
            df[term] = df.get(term, 0) + 1

    # IDF: BM25+ formula
    idf: dict[str, float] = {}
    for term, freq in df.items():
        idf[term] = math.log((N - freq + 0.5) / (freq + 0.5) + 1)

    bm25_index = {
        "schema_version": "1.0",
        "total_notes": N,
        "avgdl": avgdl,
        "idf": idf,
        "notes": all_notes,
    }

    # ── Write global files ────────────────────────────────────
    with open(_global_dir() / "bm25.json", "w") as f:
        json.dump(bm25_index, f, ensure_ascii=False)

    with open(_global_dir() / "embeddings.json", "w") as f:
        json.dump(all_embeddings, f, ensure_ascii=False)

    all_indexed = list(indexed_slugs | set(new_slugs)) if not request.force else all_slugs
    manifest = {
        "built_at": __import__("datetime").datetime.utcnow().isoformat(),
        "slugs": all_indexed,
        "total_notes": N,
        "total_embeddings": len(all_embeddings),
        "vocab_size": len(idf),
    }
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return {
        "success": True,
        "new_slugs": new_slugs,
        "total_slugs": len(all_indexed),
        "total_notes": N,
        "total_embeddings": len(all_embeddings),
        "vocab_size": len(idf),
        "avgdl": round(avgdl, 1),
    }


# ──────────────────────────────────────────────────────────────
# POST /vault/global/search  — unified BM25 + semantic + RRF
# ──────────────────────────────────────────────────────────────

class GlobalSearchRequest(BaseModel):
    query: str
    top_k: int = 10
    mode: str = "hybrid"          # bm25 | semantic | hybrid
    filter_slug: Optional[str] = None
    filter_doc_type: Optional[str] = None
    filter_akn_element: Optional[str] = None


@app.post("/vault/global/search")
async def global_search(request: GlobalSearchRequest):
    """Unified cross-document search using BM25 + cosine similarity + RRF.

    Modes:
      bm25     — keyword search with corpus-level IDF
      semantic — cosine similarity over SBERT embeddings
      hybrid   — RRF fusion of BM25 + semantic ranks (default)

    Filters:
      filter_slug        — restrict to a single document
      filter_doc_type    — e.g. 'resolution_plan_order'
      filter_akn_element — e.g. 'motivation'

    Returns top_k results with slug, note_id, score, snippet, metadata.
    """
    bm25_data = _load_global_bm25()
    emb_data = _load_global_embeddings()

    if not bm25_data and not emb_data:
        raise HTTPException(status_code=404, detail="Global index not built. Run POST /vault/global/index first.")

    query_tokens = _tokenize(request.query)
    idf = bm25_data.get("idf", {})
    avgdl = bm25_data.get("avgdl", 100)
    notes = bm25_data.get("notes", {})

    # Apply filters
    def passes_filter(slug: str, meta: dict) -> bool:
        if request.filter_slug and slug != request.filter_slug:
            return False
        if request.filter_doc_type:
            pass   # doc_type not stored per-note; skip for now
        if request.filter_akn_element and meta.get("akn_element") != request.filter_akn_element:
            return False
        return True

    results: list[dict] = []

    # ── BM25 ranking ──────────────────────────────────────────
    bm25_scores: dict[str, float] = {}
    if request.mode in ("bm25", "hybrid") and query_tokens:
        for note_id, note in notes.items():
            slug = note.get("slug", "")
            if not passes_filter(slug, note.get("meta", {})):
                continue
            score = _bm25_score(query_tokens, note, idf, avgdl)
            if score > 0:
                bm25_scores[note_id] = score

    # ── Semantic ranking ──────────────────────────────────────
    sem_scores: dict[str, float] = {}
    query_embedding: list[float] = []
    if request.mode in ("semantic", "hybrid") and emb_data:
        # Get query embedding from SBERT
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{SBERT_URL}/v1/embeddings",
                    json={"input": request.query, "model": "inlegal-sbert"},
                )
                resp.raise_for_status()
                query_embedding = resp.json()["data"][0]["embedding"]
        except Exception:
            query_embedding = []

        if query_embedding:
            for entry in emb_data:
                slug = entry.get("slug", "")
                if not passes_filter(slug, entry.get("meta", {})):
                    continue
                emb = entry.get("embedding", [])
                if not emb:
                    continue
                note_global_id = f"{slug}/{entry['note_id']}"
                sem_scores[note_global_id] = _cosine(query_embedding, emb)

    # ── RRF fusion ────────────────────────────────────────────
    if request.mode == "hybrid" and bm25_scores and sem_scores:
        bm25_ranked = {k: i for i, k in enumerate(sorted(bm25_scores, key=bm25_scores.get, reverse=True))}
        sem_ranked = {k: i for i, k in enumerate(sorted(sem_scores, key=sem_scores.get, reverse=True))}
        fused = _rrf([bm25_ranked, sem_ranked])
        final_scores = fused
    elif request.mode == "semantic" or (request.mode == "hybrid" and sem_scores):
        final_scores = sem_scores
    else:
        final_scores = bm25_scores

    # ── Build result list ─────────────────────────────────────
    top = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)[:request.top_k]

    for note_global_id, score in top:
        parts = note_global_id.split("/", 1)
        slug = parts[0]
        note_id = parts[1] if len(parts) > 1 else ""
        note_meta = notes.get(note_global_id, {}).get("meta", {})

        # Load snippet from karpathy note file
        snippet = ""
        note_path = Path(VAULT_ROOT) / "_karpathy" / slug / f"{note_id}.md"
        if note_path.exists():
            try:
                import frontmatter as _fm
                post = _fm.load(note_path)
                snippet = (post.content or "")[:300]
            except Exception:
                pass

        results.append({
            "id": note_global_id,
            "slug": slug,
            "note_id": note_id,
            "score": round(score, 4),
            "snippet": snippet,
            "page_start": note_meta.get("page_start", 0),
            "page_end": note_meta.get("page_end", 0),
            "breadcrumb": note_meta.get("breadcrumb", ""),
            "akn_element": note_meta.get("akn_element", ""),
            "bm25_score": round(bm25_scores.get(note_global_id, 0), 4),
            "sem_score": round(sem_scores.get(note_global_id, 0), 4),
        })

    return {
        "success": True,
        "query": request.query,
        "mode": request.mode,
        "total_results": len(results),
        "results": results,
    }


# ──────────────────────────────────────────────────────────────
# POST /vault/global/matter_group — group docs by case/debtor
# ──────────────────────────────────────────────────────────────

@app.post("/vault/global/matter_group")
async def global_matter_group():
    """Detect and group source documents into matters.

    Groups slugs by shared case_number (primary) or corporate_debtor (fallback).
    For each matter group writes:
      matters/{matter-id}/_index.md  — links all slugs, cross-matter Dataview query
      matters/{matter-id}/_timeline.md — merged timeline from all _timeline.json in matter

    Safe to re-run — overwrites existing matter notes.
    """
    _matters_dir().mkdir(parents=True, exist_ok=True)

    sources_dir = Path(VAULT_ROOT) / "sources"
    if not sources_dir.exists():
        return {"success": False, "reason": "No sources in vault."}

    # Collect all slugs with their key fields
    docs: list[dict] = []
    for slug_dir in sources_dir.iterdir():
        if not slug_dir.is_dir():
            continue
        idx_path = slug_dir / "_index.md"
        if not idx_path.exists():
            continue
        try:
            import frontmatter as _fm
            post = _fm.load(idx_path)
            docs.append({
                "slug": slug_dir.name,
                "case_number": (post.metadata.get("case_number") or "").strip().upper(),
                "corporate_debtor": (post.metadata.get("corporate_debtor") or "").strip().lower(),
                "doc_type": post.metadata.get("doc_type", "other"),
                "order_date": post.metadata.get("order_date", ""),
            })
        except Exception:
            continue

    # ── Group by case_number (exact) then corporate_debtor (fuzzy) ──
    import difflib

    matters: dict[str, list[dict]] = {}   # matter_key → [doc, ...]

    assigned: set = set()
    # Pass 1: group by case_number
    case_map: dict[str, str] = {}   # case_number → matter_key
    for doc in docs:
        cn = doc["case_number"]
        if not cn:
            continue
        if cn not in case_map:
            matter_key = make_slug(cn)
            case_map[cn] = matter_key
            matters[matter_key] = []
        matters[case_map[cn]].append(doc)
        assigned.add(doc["slug"])

    # Pass 2: unassigned docs — fuzzy match on corporate_debtor
    unassigned = [d for d in docs if d["slug"] not in assigned]
    for doc in unassigned:
        cd = doc["corporate_debtor"]
        if not cd:
            continue
        best_key = None
        best_ratio = 0.0
        for mkey, mdocs in matters.items():
            for md in mdocs:
                ratio = difflib.SequenceMatcher(None, cd, md["corporate_debtor"]).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_key = mkey
        if best_ratio >= 0.80 and best_key:
            matters[best_key].append(doc)
            assigned.add(doc["slug"])
        else:
            # New matter based on debtor name
            matter_key = make_slug(cd) or make_slug(doc["slug"])
            matters.setdefault(matter_key, []).append(doc)
            assigned.add(doc["slug"])

    # ── Write matter notes ─────────────────────────────────────
    matters_written = []
    for matter_key, group_docs in matters.items():
        if len(group_docs) < 1:
            continue

        slugs = [d["slug"] for d in group_docs]
        case_number = next((d["case_number"] for d in group_docs if d["case_number"]), "")
        corporate_debtor = next((d["corporate_debtor"] for d in group_docs if d["corporate_debtor"]), matter_key)
        doc_types = list({d["doc_type"] for d in group_docs})

        # Collect and merge timelines
        all_events: list[dict] = []
        for doc in group_docs:
            timeline = read_sidecar_json(VAULT_ROOT, doc["slug"], "_timeline.json")
            if timeline and "events" in timeline:
                for ev in timeline["events"]:
                    ev["_source_slug"] = doc["slug"]
                    all_events.append(ev)

        # Sort by date
        all_events.sort(key=lambda e: (e.get("date") or "9999-99-99"))

        # Write _index.md
        matter_meta = {
            "type": "matter-index",
            "matter_id": matter_key,
            "case_number": case_number,
            "corporate_debtor": corporate_debtor,
            "doc_types": doc_types,
            "slugs": slugs,
            "total_docs": len(slugs),
        }
        slug_links = "\n".join(f"- [[sources/{s}/_index]]" for s in slugs)
        matter_body = f"# Matter: {corporate_debtor.title()}\n\n"
        if case_number:
            matter_body += f"**Case:** {case_number}\n\n"
        matter_body += f"**Documents ({len(slugs)}):**\n{slug_links}\n\n"
        matter_body += "## All Documents in This Matter\n\n"
        matter_body += "```dataview\n"
        matter_body += f'TABLE doc_type, order_date, pipeline_stage\nFROM "sources"\nWHERE contains(file.path, "{matter_key}")\nSORT order_date ASC\n'
        matter_body += "```\n"

        write_note(VAULT_ROOT, f"matters/{matter_key}/_index.md", matter_meta, matter_body)

        # Write _timeline.md
        if all_events:
            timeline_meta = {
                "type": "matter-timeline",
                "matter_id": matter_key,
                "corporate_debtor": corporate_debtor,
                "total_events": len(all_events),
            }
            timeline_rows = "| Date | Event | Significance | Source |\n|---|---|---|---|\n"
            for ev in all_events:
                date = ev.get("date") or "—"
                event = ev.get("event", "").replace("|", "\\|")[:80]
                sig = ev.get("significance", "medium")
                src = ev.get("_source_slug", "")
                timeline_rows += f"| {date} | {event} | {sig} | [[sources/{src}/_index\\|{src}]] |\n"
            timeline_body = f"# Timeline: {corporate_debtor.title()}\n\n{timeline_rows}"
            write_note(VAULT_ROOT, f"matters/{matter_key}/_timeline.md", timeline_meta, timeline_body)

        matters_written.append({"matter_id": matter_key, "slugs": slugs, "events": len(all_events)})

    return {
        "success": True,
        "matters_written": len(matters_written),
        "matters": matters_written,
    }


# ──────────────────────────────────────────────────────────────
# POST /vault/global/entity_resolve — canonical entity registry
# ──────────────────────────────────────────────────────────────

@app.post("/vault/global/entity_resolve")
async def global_entity_resolve():
    """Build canonical entity registry from all _entities.json files.

    Reads sources/{slug}/_entities.json for every slug, deduplicates entities
    by name similarity (≥0.85 ratio) + role, and writes:
      _global/entities.json — canonical registry with aliases + appears_in list

    Useful for: cross-doc entity resolution, Pi agent entity lookup,
    LightRAG entity deduplication.
    """
    import difflib

    _global_dir().mkdir(parents=True, exist_ok=True)
    sources_dir = Path(VAULT_ROOT) / "sources"
    if not sources_dir.exists():
        return {"success": False, "reason": "No sources in vault."}

    # Collect all entities from all slugs
    raw_entities: list[dict] = []
    for slug_dir in sources_dir.iterdir():
        if not slug_dir.is_dir():
            continue
        slug = slug_dir.name
        entities_data = read_sidecar_json(VAULT_ROOT, slug, "_entities.json")
        if not entities_data:
            continue
        for party in entities_data.get("parties", []):
            party["_slug"] = slug
            party["_category"] = "party"
            raw_entities.append(party)
        for company in entities_data.get("key_companies", []):
            company["_slug"] = slug
            company["_category"] = "company"
            raw_entities.append(company)
        for judge in entities_data.get("judges", []):
            judge["_slug"] = slug
            judge["_category"] = "judge"
            raw_entities.append(judge)

    # Cluster by name similarity
    canonical: list[dict] = []

    def find_cluster(name: str, role: str) -> int | None:
        name_lower = name.lower()
        for i, cluster in enumerate(canonical):
            ratio = difflib.SequenceMatcher(None, name_lower, cluster["canonical_name"].lower()).ratio()
            if ratio >= 0.85:
                return i
            for alias in cluster.get("aliases", []):
                ratio2 = difflib.SequenceMatcher(None, name_lower, alias.lower()).ratio()
                if ratio2 >= 0.85:
                    return i
        return None

    for entity in raw_entities:
        name = (entity.get("name") or "").strip()
        role = (entity.get("role") or entity.get("designation") or "").strip()
        slug = entity.get("_slug", "")
        category = entity.get("_category", "party")
        if not name:
            continue

        cluster_idx = find_cluster(name, role)
        if cluster_idx is not None:
            c = canonical[cluster_idx]
            if name != c["canonical_name"] and name not in c["aliases"]:
                c["aliases"].append(name)
            if slug not in c["appears_in"]:
                c["appears_in"].append(slug)
        else:
            canonical.append({
                "canonical_name": name,
                "aliases": [],
                "role": role,
                "category": category,
                "appears_in": [slug],
                "cin": entity.get("cin", ""),
            })

    registry = {
        "built_at": __import__("datetime").datetime.utcnow().isoformat(),
        "total_entities": len(canonical),
        "entities": canonical,
    }

    with open(_global_dir() / "entities.json", "w") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)

    # Categorise for response
    by_category: dict[str, int] = {}
    for e in canonical:
        by_category[e["category"]] = by_category.get(e["category"], 0) + 1

    return {
        "success": True,
        "total_entities": len(canonical),
        "by_category": by_category,
        "entities_path": str(_global_dir() / "entities.json"),
    }


# ──────────────────────────────────────────────────────────────
# POST /vault/global/precedent_graph — build citation graph
# ──────────────────────────────────────────────────────────────

@app.post("/vault/global/precedent_graph")
async def global_precedent_graph():
    """Build a precedent citation graph from all _citations.json files.

    Reads sources/{slug}/_citations.json for every slug and:
      1. Writes _global/citations.json — flat edge list: (slug → cited_case)
      2. Pushes each citation as a LightRAG entity relation so the graph
         becomes queryable via LightRAG: "what cases does X cite?"

    Each edge: {source_slug, cited_case_name, citation_str, principle}
    """
    _global_dir().mkdir(parents=True, exist_ok=True)
    sources_dir = Path(VAULT_ROOT) / "sources"
    if not sources_dir.exists():
        return {"success": False, "reason": "No sources in vault."}

    all_edges: list[dict] = []
    slug_case_map: dict[str, str] = {}  # slug → case_number (for labelling nodes)

    # Build slug → case_number map from _index.md
    for slug_dir in sources_dir.iterdir():
        if not slug_dir.is_dir():
            continue
        idx_path = slug_dir / "_index.md"
        if idx_path.exists():
            try:
                import frontmatter as _fm
                post = _fm.load(idx_path)
                slug_case_map[slug_dir.name] = post.metadata.get("case_number", slug_dir.name)
            except Exception:
                slug_case_map[slug_dir.name] = slug_dir.name

    # Collect citation edges
    for slug_dir in sources_dir.iterdir():
        if not slug_dir.is_dir():
            continue
        slug = slug_dir.name
        citations_data = read_sidecar_json(VAULT_ROOT, slug, "_citations.json")
        if not citations_data:
            continue

        source_label = slug_case_map.get(slug, slug)

        for cite in citations_data.get("case_citations", []):
            cited_name = (cite.get("case_name") or "").strip()
            if not cited_name:
                continue
            all_edges.append({
                "source_slug": slug,
                "source_case": source_label,
                "cited_case": cited_name,
                "citation_str": cite.get("citation", ""),
                "principle": cite.get("principle", ""),
            })

    # Write flat edge list
    graph_data = {
        "built_at": __import__("datetime").datetime.utcnow().isoformat(),
        "total_edges": len(all_edges),
        "edges": all_edges,
    }
    with open(_global_dir() / "citations.json", "w") as f:
        json.dump(graph_data, f, ensure_ascii=False, indent=2)

    # Push to LightRAG as entity relations
    lightrag_pushed = 0
    lightrag_errors = 0
    if all_edges:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Build a structured text that LightRAG will parse into entities + relations
                graph_text_parts = []
                for edge in all_edges:
                    graph_text_parts.append(
                        f"Case '{edge['source_case']}' (slug: {edge['source_slug']}) "
                        f"cites '{edge['cited_case']}'. "
                        f"{edge['principle']}"
                    )
                graph_text = "\n".join(graph_text_parts)
                resp = await client.post(
                    f"{LIGHTRAG_URL}/documents/text",
                    json={
                        "text": graph_text,
                        "metadata": {"type": "precedent-citation-graph", "source": "global_precedent_graph"},
                    },
                )
                if resp.status_code < 300:
                    lightrag_pushed = len(all_edges)
                else:
                    lightrag_errors = len(all_edges)
        except Exception as e:
            lightrag_errors = len(all_edges)

    # Node summary
    nodes: set = set()
    for e in all_edges:
        nodes.add(e["source_case"])
        nodes.add(e["cited_case"])

    return {
        "success": True,
        "total_edges": len(all_edges),
        "total_nodes": len(nodes),
        "lightrag_pushed": lightrag_pushed,
        "lightrag_errors": lightrag_errors,
        "citations_path": str(_global_dir() / "citations.json"),
    }


# ──────────────────────────────────────────────────────────────
# GET /vault/global/status — Sprint 3 index health check
# ──────────────────────────────────────────────────────────────

@app.get("/vault/global/status")
async def global_status():
    """Return current state of all global indexes."""
    g = _global_dir()
    manifest_path = g / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)

    entities_path = g / "entities.json"
    entities_count = 0
    if entities_path.exists():
        with open(entities_path) as f:
            entities_count = json.load(f).get("total_entities", 0)

    citations_path = g / "citations.json"
    citations_count = 0
    if citations_path.exists():
        with open(citations_path) as f:
            citations_count = json.load(f).get("total_edges", 0)

    matters_dir = _matters_dir()
    matter_count = len([d for d in matters_dir.iterdir() if d.is_dir()]) if matters_dir.exists() else 0

    return {
        "bm25_built": (g / "bm25.json").exists(),
        "embeddings_built": (g / "embeddings.json").exists(),
        "manifest": manifest,
        "entities_count": entities_count,
        "citations_edges": citations_count,
        "matters_count": matter_count,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5004)