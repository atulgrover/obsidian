"""
vault-pipeline — FastAPI service that orchestrates the RAG2 pipeline
and writes all output to an Obsidian vault (markdown + YAML frontmatter).

Stages:
  Stage 1: PDF → LiteParse → PageIndex → vault markdown (sources/)
  Stage 2: vault sections → SemChunk → vault chunks (chunks/)
  Stage 3: vault chunks → LightRAG → Postgres (updates chunk frontmatter)

Also provides vault CRUD endpoints for the web frontend.
"""

from __future__ import annotations

import os
import tempfile
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
    read_all_chunks,
    read_all_sections,
    read_note,
    read_parse_json,
    read_tree_json,
    update_pipeline_stage,
    write_chunk_index,
    write_chunk_note,
    write_full_text,
    write_parse_json,
    write_section_note,
    write_source_index,
    write_tree_json,
    write_note,
)

# ──────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────

VAULT_ROOT = os.environ.get("VAULT_ROOT", "/vault")
LITEPARSE_URL = os.environ.get("LITEPARSE_URL", "http://localhost:5001")
PAGEINDEX_URL = os.environ.get("PAGEINDEX_URL", "http://localhost:5002")
SEMCHUNK_URL = os.environ.get("SEMCHUNK_URL", "http://localhost:5003")
LIGHTRAG_URL = os.environ.get("LIGHTRAG_URL", "http://localhost:8020")

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


@app.on_event("startup")
async def startup():
    init_vault(VAULT_ROOT)


@app.get("/")
async def root():
    return {"message": "vault-pipeline", "version": "1.0.0", "vault_root": VAULT_ROOT}


@app.get("/health")
async def health():
    return {"status": "ok", "vault_root": VAULT_ROOT}


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

        # Step 2: LiteParse
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as f:
                lp_resp = await client.post(
                    f"{LITEPARSE_URL}/parse",
                    files={"file": (filename, f, "application/pdf")},
                    timeout=120.0,
                )
            lp_resp.raise_for_status()
            lp_result = lp_resp.json()
            if not lp_result.get("success"):
                raise HTTPException(status_code=502, detail=f"LiteParse error: {lp_result.get('error')}")

            # Cache LiteParse result for re-processing
            write_parse_json(VAULT_ROOT, slug, lp_result)
        finally:
            os.unlink(tmp_path)

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
    Stage 3: Read vault chunk notes, call LightRAG /ingest, update frontmatter.
    """
    slug = request.slug
    chunks_dir = f"chunks/{slug}"

    if not note_exists(VAULT_ROOT, f"{chunks_dir}/_index.md"):
        raise HTTPException(status_code=404, detail=f"Chunk index not found for: {slug}")

    # Read all chunk notes
    chunk_notes = read_all_chunks(VAULT_ROOT, slug)
    if not chunk_notes:
        raise HTTPException(status_code=404, detail=f"No chunk notes found for: {slug}")

    # Read source metadata
    index_note = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")

    # Build LightRAG /ingest payload
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
            "metadata": {
                "nodeId": "",
                "title": "",
                "summary": "",
                "chunkIndex": m.get("chunk_index", 0),
                "totalChunks": m.get("total_chunks", 0),
                "hasOverlap": m.get("has_overlap", False),
            },
            "docType": m.get("doc_type"),
            "docDate": m.get("doc_date"),
            "parties": m.get("parties"),
            "statutoryRefs": m.get("statutory_refs"),
        })

    payload = {
        "source": slug,
        "chunks": chunks_payload,
        "documentTitle": index_note.metadata.get("filename", slug),
        "documentSummary": index_note.metadata.get("summary", ""),
    }

    # Call LightRAG /ingest
    async with httpx.AsyncClient(timeout=600.0) as client:
        try:
            resp = await client.post(
                f"{LIGHTRAG_URL}/ingest",
                json=payload,
            )
            resp.raise_for_status()
            result = resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"LightRAG ingest failed: {e}")

    # Update chunk frontmatter with ingestion status
    for note in chunk_notes:
        chunk_index = note.metadata.get("chunk_index", 0)
        rel_path = f"chunks/{slug}/chunk-{chunk_index + 1:03d}.md"
        try:
            update_pipeline_stage(VAULT_ROOT, rel_path, "ingested")
            # Also update lightrag_ingested
            m = note.metadata
            m["lightrag_ingested"] = True
            m["ingested_at"] = result.get("run_id", "")
            write_note(VAULT_ROOT, rel_path, m, note.body)
        except Exception:
            pass  # Best-effort update

    # Update source pipeline stage
    update_pipeline_stage(VAULT_ROOT, f"sources/{slug}/_index.md", "ingested")

    return IngestLightragResponse(
        success=True,
        slug=slug,
        ingested=result.get("ingested", 0),
        skipped=result.get("skipped", 0),
        failed=result.get("failed", 0),
        run_id=result.get("run_id", ""),
        message=f"Ingested {result.get('ingested', 0)} chunks into LightRAG",
    )


# ──────────────────────────────────────────────────────────────
# Full pipeline: Stage 1 → 2 → 3
# ──────────────────────────────────────────────────────────────

class FullPipelineRequest(BaseModel):
    url: str
    max_tokens: int = 512
    overlap_tokens: int = 75


class FullPipelineUploadResponse(BaseModel):
    success: bool
    slug: str
    stages: dict = {}


@app.post("/vault/full-pipeline")
async def full_pipeline(request: FullPipelineRequest):
    """Run all three stages: ingest → chunk → ingest-lightrag."""
    # Stage 1
    stage1 = await ingest_pdf(IngestPdfRequest(
        url=request.url,
        max_tokens=request.max_tokens,
        overlap_tokens=request.overlap_tokens,
    ))

    if not stage1.success:
        return {"success": False, "stage": 1, "error": stage1.message}

    # Stage 2
    stage2 = await chunk_from_vault(ChunkFromVaultRequest(
        slug=stage1.slug,
        max_tokens=request.max_tokens,
        overlap_tokens=request.overlap_tokens,
    ))

    if not stage2.success:
        return {"success": False, "stage": 2, "error": stage2.message}

    # Stage 3
    stage3 = await ingest_lightrag(IngestLightragRequest(slug=stage1.slug))

    return {
        "success": True,
        "slug": stage1.slug,
        "stages": {
            "ingest_pdf": stage1.dict(),
            "chunk": stage2.dict(),
            "ingest_lightrag": stage3.dict(),
        },
    }


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
            "title": note.metadata.get("summary", note.body[:80] if note.body else ""),
            "level": note.metadata.get("level", 0),
            "is_leaf": note.metadata.get("is_leaf", True),
            "page_start": note.metadata.get("page_start", 1),
            "page_end": note.metadata.get("page_end", 1),
            "word_count": note.metadata.get("word_count", 0),
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
# Single-stage run endpoints
# ──────────────────────────────────────────────────────────────

class StageRequest(BaseModel):
    slug: str
    max_tokens: int = 512
    overlap_tokens: int = 75


@app.post("/vault/stage/parse")
async def stage_parse(request: StageRequest):
    """Run only Stage 1: LiteParse + PageIndex (no vault write)."""
    slug = request.slug
    parse_data = read_parse_json(VAULT_ROOT, slug)

    if parse_data is None:
        raise HTTPException(status_code=404, detail=f"No parse data for: {slug}. Upload a PDF first.")

    return {"success": True, "slug": slug, "parse": parse_data}


@app.post("/vault/stage/cleanse")
async def stage_cleanse(request: StageRequest):
    """Run PageIndex tree building on cached parse data."""
    slug = request.slug
    parse_data = read_parse_json(VAULT_ROOT, slug)
    if parse_data is None:
        raise HTTPException(status_code=404, detail=f"No parse data for: {slug}. Run Parse first.")

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{PAGEINDEX_URL}/build-tree",
            json={"liteparse_result": parse_data},
        )
        resp.raise_for_status()
        tree_result = resp.json()

    # Cache the tree
    write_tree_json(VAULT_ROOT, slug, tree_result)

    return {"success": True, "slug": slug, "tree": tree_result}


@app.post("/vault/stage/index")
async def stage_index(request: StageRequest):
    """Run vault write: save sections + full-text + index from cached tree."""
    slug = request.slug
    tree_data = read_tree_json(VAULT_ROOT, slug)
    if tree_data is None:
        raise HTTPException(status_code=404, detail=f"No tree data for: {slug}. Run Cleanse first.")

    parse_data = read_parse_json(VAULT_ROOT, slug)
    index_note = read_note(VAULT_ROOT, f"sources/{slug}/_index.md")
    tree = tree_data.get("tree", {})
    total_pages = (parse_data or {}).get("metadata", {}).get("totalPages", 0)
    total_chars = (parse_data or {}).get("metadata", {}).get("characterCount", 0)
    filename = index_note.metadata.get("filename", f"{slug}.pdf") if index_note else f"{slug}.pdf"

    # Re-run the vault write logic from ingest_pdf
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
        word_count = metadata.get("wordCount", len(content.split()))
        heading_level = metadata.get("headingLevel", level)

        title_slug = make_slug(title) if title else "untitled"
        sec_filename = f"sec-{section_id}-{title_slug}.md"
        sec_wikilink = f"[[sources/{slug}/sections/sec-{section_id}-{title_slug}]]"

        child_wikilinks = []
        for child in children_nodes:
            child_id = child.get("id", "").replace("node-", "")
            child_title = child.get("title", "Untitled")
            child_slug = make_slug(child_title)
            child_wikilinks.append(f"[[sources/{slug}/sections/sec-{child_id}-{child_slug}]]")

        parent_wikilink = ""
        if parent_path:
            parent_wikilink = f"[[sources/{slug}/sections/{parent_path}]]"

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

    doc_title = tree.get("title", filename)
    write_source_index(
        VAULT_ROOT, slug,
        filename=filename,
        total_pages=total_pages,
        total_chars=total_chars,
        source_url=index_note.metadata.get("source_url", "") if index_note else "",
        pipeline_stage="pageindex",
        children=children,
    )

    # Write full-text
    full_text = (parse_data or {}).get("text", "")
    if full_text:
        write_full_text(VAULT_ROOT, slug, full_text, filename=filename)

    return {"success": True, "slug": slug, "sections": len(section_notes), "message": f"Saved {len(section_notes)} sections to vault"}


@app.post("/vault/stage/chunk")
async def stage_chunk(request: StageRequest):
    """Run SemChunk on cached sections."""
    return await chunk_from_vault(ChunkFromVaultRequest(
        slug=request.slug,
        max_tokens=request.max_tokens,
        overlap_tokens=request.overlap_tokens,
    ))


@app.post("/vault/stage/embed")
async def stage_embed(request: StageRequest):
    """Run LightRAG ingestion on cached chunks."""
    return await ingest_lightrag(IngestLightragRequest(slug=request.slug))


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5004)