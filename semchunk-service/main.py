"""
semchunk Service

Splits PageIndex tree leaves into semantically-bounded text chunks.
Uses semchunk for sentence-aware splitting + tiktoken for token counting.

Tier-1 quality improvements:
  - 75-token overlap between adjacent chunks (prevents reasoning split at boundaries)
  - documentTitle + documentSummary included in pipeline responses (used by LightRAG
    contextual retrieval to situate each chunk in its document)

Output chunks (content + parentContext) are fed as plain text into LightRAG,
which handles its own embedding and graph indexing internally.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import semchunk
import tiktoken
import httpx
import tempfile
import os

app = FastAPI(title="semchunk Service", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class PageIndexNode(BaseModel):
    id: str
    level: int
    title: str
    summary: str
    content: str
    pageStart: int
    pageEnd: int
    children: List['PageIndexNode']
    parentId: Optional[str] = None
    metadata: Dict[str, Any]

PageIndexNode.model_rebuild()

class ContextualizedChunk(BaseModel):
    id: str
    content: str                     # chunk text (with overlap prepended from prev chunk)
    parentContext: Optional[str]     # ancestor title+summary breadcrumb (metadata)
    pageStart: int
    pageEnd: int
    level: int
    metadata: Dict[str, Any]
    sourceNodeId: str
    tokenCount: int                  # approximate token count (cl100k_base)

class ChunkRequest(BaseModel):
    pageIndexTree: PageIndexNode
    maxTokens: int = 512
    overlapTokens: int = 75

class ChunkResponse(BaseModel):
    success: bool
    chunks: List[ContextualizedChunk]
    chunkCount: int
    totalTokens: int
    documentTitle: Optional[str] = None
    documentSummary: Optional[str] = None

class PipelineRequest(BaseModel):
    pageindex_result: Dict[str, Any]
    maxTokens: int = 512
    overlapTokens: int = 75

class PipelineResponse(BaseModel):
    success: bool
    chunks: List[ContextualizedChunk]
    chunkCount: int
    totalTokens: int
    documentTitle: Optional[str] = None    # root node title — for contextual retrieval
    documentSummary: Optional[str] = None  # root node summary — for contextual retrieval

# ═══════════════════════════════════════════════════════════════════════════════
# CHUNKER
# ═══════════════════════════════════════════════════════════════════════════════

class SemanticChunker:
    def __init__(self, max_tokens: int = 512, overlap_tokens: int = 75):
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.chunk_id_counter = 0
        self.encoding = tiktoken.get_encoding('cl100k_base')
        self.chunker = semchunk.chunkerify(self._count_tokens, self.max_tokens)

    def _count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def generate_chunks(self, tree: PageIndexNode) -> List[ContextualizedChunk]:
        chunks: List[ContextualizedChunk] = []
        self._process_tree(tree, [], chunks)
        return chunks

    def _process_tree(
        self,
        node: PageIndexNode,
        ancestors: List[PageIndexNode],
        chunks: List[ContextualizedChunk]
    ):
        if self._should_chunk_node(node):
            parent_context = self._build_parent_context(ancestors)
            self._chunk_node(node, parent_context, chunks)
        else:
            for child in node.children:
                self._process_tree(child, ancestors + [node], chunks)

    def _should_chunk_node(self, node: PageIndexNode) -> bool:
        if node.level == 0:
            return False
        if node.metadata.get('type') == 'section' and len(node.children) > 0:
            return False
        return True

    def _build_parent_context(self, ancestors: List[PageIndexNode]) -> Optional[str]:
        """Last 3 ancestors → titled summaries breadcrumb."""
        if not ancestors:
            return None
        parts = []
        for anc in ancestors[-3:]:
            if anc.title and anc.summary:
                parts.append(f"{anc.title}: {anc.summary}")
            elif anc.title:
                parts.append(anc.title)
        return "\n".join(parts) if parts else None

    def _apply_overlap(self, text_chunks: List[str]) -> List[str]:
        """
        Prepend the last `overlap_tokens` tokens of chunk[i-1] to chunk[i].
        This prevents reasoning that spans a chunk boundary from being lost.
        Overlap is purely for embedding context — LightRAG sees it as part of the chunk.
        """
        if self.overlap_tokens == 0 or len(text_chunks) <= 1:
            return text_chunks

        result = [text_chunks[0]]
        for i in range(1, len(text_chunks)):
            prev_tokens = self.encoding.encode(text_chunks[i - 1])
            overlap_ids = prev_tokens[-self.overlap_tokens:]
            overlap_text = self.encoding.decode(overlap_ids).strip()
            result.append(overlap_text + " " + text_chunks[i])
        return result

    def _chunk_node(
        self,
        node: PageIndexNode,
        parent_context: Optional[str],
        chunks: List[ContextualizedChunk]
    ):
        content = node.content
        if not content.strip():
            return

        raw_chunks = list(self.chunker(content))
        text_chunks = self._apply_overlap(raw_chunks)

        for i, text_chunk in enumerate(text_chunks):
            chunk = ContextualizedChunk(
                id=self._generate_id(),
                content=text_chunk,
                parentContext=parent_context,
                pageStart=node.pageStart,
                pageEnd=node.pageEnd,
                level=node.level,
                metadata={
                    **node.metadata,
                    'nodeId': node.id,
                    'title': node.title,
                    'summary': node.summary,
                    'chunkIndex': i,
                    'totalChunks': len(text_chunks),
                    'hasOverlap': i > 0 and self.overlap_tokens > 0,
                },
                sourceNodeId=node.id,
                tokenCount=self._count_tokens(text_chunk),
            )
            chunks.append(chunk)

    def _generate_id(self) -> str:
        self.chunk_id_counter += 1
        return f"chunk-{self.chunk_id_counter}"


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _dict_to_node(d: Dict[str, Any]) -> PageIndexNode:
    children = [_dict_to_node(c) for c in d.get('children', [])]
    return PageIndexNode(
        id=d.get('id', ''),
        level=d.get('level', 0),
        title=d.get('title', ''),
        summary=d.get('summary', ''),
        content=d.get('content', ''),
        pageStart=d.get('pageStart', 1),
        pageEnd=d.get('pageEnd', 1),
        children=children,
        parentId=d.get('parentId'),
        metadata=d.get('metadata', {}),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    return {"message": "semchunk Service", "version": "2.1.0"}

@app.get("/health")
async def health():
    return {"status": "ok", "service": "semchunk"}

@app.post("/chunk", response_model=ChunkResponse)
async def chunk_tree(request: ChunkRequest):
    """
    Chunk a PageIndex tree into semantically-bounded text chunks.
    Each chunk carries parentContext as metadata for LightRAG ingestion.
    Adjacent chunks share overlap_tokens of text to preserve cross-boundary reasoning.
    """
    try:
        chunker = SemanticChunker(
            max_tokens=request.maxTokens,
            overlap_tokens=request.overlapTokens,
        )
        chunks = chunker.generate_chunks(request.pageIndexTree)
        return ChunkResponse(
            success=True,
            chunks=chunks,
            chunkCount=len(chunks),
            totalTokens=sum(c.tokenCount for c in chunks),
            documentTitle=request.pageIndexTree.title,
            documentSummary=request.pageIndexTree.summary,
        )
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/pipeline", response_model=PipelineResponse)
async def pipeline(request: PipelineRequest):
    """
    Accepts raw pageindex service output (JSON with a `tree` key).
    Returns chunks ready to be inserted into LightRAG as plain text.

    Body:
    {
      "pageindex_result": { "success": true, "tree": { ... } },
      "maxTokens": 512,
      "overlapTokens": 75
    }
    """
    try:
        tree_dict = request.pageindex_result.get('tree')
        if not tree_dict:
            raise HTTPException(status_code=422, detail="pageindex_result must contain a 'tree' key")

        tree = _dict_to_node(tree_dict)
        chunker = SemanticChunker(
            max_tokens=request.maxTokens,
            overlap_tokens=request.overlapTokens,
        )
        chunks = chunker.generate_chunks(tree)

        return PipelineResponse(
            success=True,
            chunks=chunks,
            chunkCount=len(chunks),
            totalTokens=sum(c.tokenCount for c in chunks),
            documentTitle=tree.title,
            documentSummary=tree.summary,
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


LITEPARSE_URL = "http://localhost:5001/parse"
PAGEINDEX_URL  = "http://localhost:5002/build-tree"

class UrlPipelineRequest(BaseModel):
    url: str
    maxTokens: int = 512
    overlapTokens: int = 75

@app.post("/url-pipeline", response_model=PipelineResponse)
async def url_pipeline(request: UrlPipelineRequest):
    """
    Full pipeline from a PDF URL.
    Downloads the PDF, runs LiteParse → PageIndex → SemChunk entirely in Python.
    Accepts: {"url": "https://...", "maxTokens": 512, "overlapTokens": 75}
    """
    url = request.url
    is_file_url = url.startswith("file://")
    if not is_file_url and not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Only http/https/file:// URLs are supported")

    async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
        # Step 1: get PDF bytes — local file path or remote download
        if is_file_url:
            file_path = url[7:]  # strip "file://"
            if not os.path.isfile(file_path):
                raise HTTPException(status_code=404, detail=f"Local file not found: {file_path}")
            tmp_path = None
            pdf_path = file_path
        else:
            try:
                pdf_resp = await client.get(url)
                pdf_resp.raise_for_status()
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Failed to download PDF: {e}")
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(pdf_resp.content)
                tmp_path = tmp.name
            pdf_path = tmp_path

        try:
            # Step 2: LiteParse
            filename = os.path.basename(pdf_path) or "document.pdf"
            with open(pdf_path, "rb") as f:
                lp_resp = await client.post(
                    LITEPARSE_URL,
                    files={"file": (filename, f, "application/pdf")},
                    timeout=120.0,
                )
            lp_resp.raise_for_status()
            lp_result = lp_resp.json()
            if not lp_result.get("success"):
                raise HTTPException(status_code=502, detail=f"LiteParse error: {lp_result.get('error')}")
        finally:
            if tmp_path:
                os.unlink(tmp_path)

        # Step 3: PageIndex
        try:
            pi_resp = await client.post(
                PAGEINDEX_URL,
                json={"liteparse_result": lp_result},
                timeout=120.0,
            )
            pi_resp.raise_for_status()
            pi_result = pi_resp.json()
            if not pi_result.get("success"):
                raise HTTPException(status_code=502, detail=f"PageIndex error: {pi_result.get('error')}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"PageIndex request failed: {e}")

    # Step 4: chunk (in-process, no HTTP)
    try:
        tree_dict = pi_result.get("tree")
        if not tree_dict:
            raise HTTPException(status_code=422, detail="PageIndex returned no tree")
        tree = _dict_to_node(tree_dict)
        chunker = SemanticChunker(
            max_tokens=request.maxTokens,
            overlap_tokens=request.overlapTokens,
        )
        chunks = chunker.generate_chunks(tree)
        return PipelineResponse(
            success=True,
            chunks=chunks,
            chunkCount=len(chunks),
            totalTokens=sum(c.tokenCount for c in chunks),
            documentTitle=tree.title,
            documentSummary=tree.summary,
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# VAULT ENDPOINT — read from Obsidian vault, write chunks back to vault
# Or: WIKI ENDPOINT — read from TiddlyWiki MWS, write chunks back to MWS
# ═══════════════════════════════════════════════════════════════════════════════

VAULT_ROOT = os.environ.get("VAULT_ROOT", "/vault")
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "vault").lower()
MWS_URL = os.environ.get("MWS_URL", "http://mws:8080")
MWS_ADMIN_USER = os.environ.get("MWS_ADMIN_USER", "admin")
MWS_ADMIN_PASSWORD = os.environ.get("MWS_ADMIN_PASSWORD", "1234")


class ChunkFromVaultRequest(BaseModel):
    slug: str
    maxTokens: int = 512
    overlapTokens: int = 75


class ChunkFromVaultResponse(BaseModel):
    success: bool
    slug: str
    totalChunks: int
    totalTokens: int
    documentTitle: Optional[str] = None
    documentSummary: Optional[str] = None


def _reconstruct_tree_from_vault(slug: str) -> PageIndexNode:
    """
    Read section notes from vault and reconstruct a PageIndexNode tree.
    Sections are stored as sec-{id}-{title-slug}.md with frontmatter.
    """
    import frontmatter
    from pathlib import Path

    sections_dir = Path(VAULT_ROOT) / "sources" / slug / "sections"
    if not sections_dir.exists():
        raise HTTPException(status_code=404, detail=f"No sections found for: {slug}")

    # Read _index.md for root metadata
    index_path = Path(VAULT_ROOT) / "sources" / slug / "_index.md"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail=f"Source document not found: {slug}")
    index_post = frontmatter.load(index_path)

    # Read all section notes
    section_nodes = []
    for f in sorted(sections_dir.glob("sec-*.md")):
        post = frontmatter.load(f)
        m = post.metadata
        # Extract the node ID from the filename: sec-01-introduction.md -> "01"
        stem = f.stem  # e.g. "sec-01-introduction"
        node_id = stem.split("-")[1] if "-" in stem else stem.replace("sec-", "")

        node = PageIndexNode(
            id=node_id,
            level=m.get("level", 1),
            title=m.get("summary", "")[:80] if m.get("summary") else (post.content[:80] if post.content else ""),
            summary=m.get("summary", ""),
            content=post.content,
            pageStart=m.get("page_start", 1),
            pageEnd=m.get("page_end", 1),
            children=[],
            parentId=None,
            metadata={
                "type": "content" if m.get("is_leaf", True) else "section",
                "wordCount": m.get("word_count", len(post.content.split()) if post.content else 0),
                "nodeId": node_id,
            },
        )
        section_nodes.append(node)

    # Build root node from _index.md
    doc_title = index_post.metadata.get("filename", slug)
    root = PageIndexNode(
        id="root",
        level=0,
        title=doc_title,
        summary=index_post.content[:200] if index_post.content else "",
        content="",
        pageStart=1,
        pageEnd=index_post.metadata.get("total_pages", 1),
        children=section_nodes,
        parentId=None,
        metadata={"type": "document", "totalPages": index_post.metadata.get("total_pages", 0)},
    )
    return root


def _write_chunks_to_vault(slug: str, chunks: List[ContextualizedChunk], document_title: str, document_summary: str):
    """Write chunk notes to the Obsidian vault."""
    import frontmatter
    from pathlib import Path
    from datetime import datetime, timezone

    chunks_dir = Path(VAULT_ROOT) / "chunks" / slug
    chunks_dir.mkdir(parents=True, exist_ok=True)

    source_wikilink = f"[[sources/{slug}/_index]]"

    for chunk in chunks:
        i = chunk.metadata.get("chunkIndex", 0)
        m = chunk.metadata

        # Build frontmatter
        chunk_meta = {
            "type": "contextualized-chunk",
            "source": source_wikilink,
            "chunk_index": i,
            "total_chunks": m.get("totalChunks", len(chunks)),
            "page_start": chunk.pageStart,
            "page_end": chunk.pageEnd,
            "token_count": chunk.tokenCount,
            "level": chunk.level,
            "parent_context": chunk.parentContext,
            "has_overlap": m.get("hasOverlap", False),
            "pipeline_stage": "semchunk",
            "lightrag_ingested": False,
            "ingested_at": None,
        }

        # Write chunk file
        filename = f"chunk-{i + 1:03d}.md"
        post = frontmatter.Post(content=chunk.content, **chunk_meta)
        with open(chunks_dir / filename, "w", encoding="utf-8") as f:
            frontmatter.dump(post, f)

    # Write chunk index
    index_meta = {
        "type": "chunk-index",
        "source": source_wikilink,
        "total_chunks": len(chunks),
        "total_tokens": sum(c.tokenCount for c in chunks),
        "document_title": document_title,
        "document_summary": document_summary,
        "pipeline_stage": "semchunk",
    }
    index_body = f"# Chunks: {document_title or slug}\n\n"
    index_body += f"**Total chunks:** {len(chunks)} | **Total tokens:** {sum(c.tokenCount for c in chunks):,}\n"
    post = frontmatter.Post(content=index_body, **index_meta)
    with open(chunks_dir / "_index.md", "w", encoding="utf-8") as f:
        frontmatter.dump(post, f)


# ──────────────────────────────────────────────────────────────
# WIKI MODE — read sections from TiddlyWiki MWS, write chunks to MWS
# ──────────────────────────────────────────────────────────────

async def _reconstruct_tree_from_wiki(slug: str) -> "PageIndexNode":
    """
    Read section tiddlers from TiddlyWiki MWS and reconstruct a PageIndexNode tree.
    Falls back to vault mode if MWS is not available.
    """
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'vault-pipeline'))
    from mws_client import MWSClient
    from wiki_io import read_all_sections, read_source_index

    client = MWSClient(MWS_URL, MWS_ADMIN_USER, MWS_ADMIN_PASSWORD)
    await client.authenticate()

    # Read source index tiddler for root metadata
    index_tiddler = await client.get_tiddler(slug, "Source Index")
    if not index_tiddler:
        raise HTTPException(status_code=404, detail=f"Source document not found in wiki: {slug}")

    index_fields = index_tiddler.get("fields", {})
    doc_title = index_fields.get("filename", slug)

    # Read all section tiddlers
    section_tiddlers = await read_all_sections(client, slug)
    if not section_tiddlers:
        raise HTTPException(status_code=404, detail=f"No sections found in wiki for: {slug}")

    section_nodes = []
    for s in section_tiddlers:
        fields = s.metadata.get("fields", s.metadata)
        node = PageIndexNode(
            id=fields.get("section_id", "0"),
            level=int(fields.get("level", 1)),
            title=fields.get("summary", s.body[:80])[:80] if fields.get("summary") else (s.body[:80] if s.body else ""),
            summary=fields.get("summary", ""),
            content=s.body,
            pageStart=int(fields.get("page_start", 1)),
            pageEnd=int(fields.get("page_end", 1)),
            children=[],
            parentId=None,
            metadata={
                "type": "content" if fields.get("is_leaf", "true").lower() == "true" else "section",
                "wordCount": int(fields.get("word_count", len(s.body.split()) if s.body else 0)),
                "nodeId": fields.get("section_id", "0"),
            },
        )
        section_nodes.append(node)

    root = PageIndexNode(
        id="root",
        level=0,
        title=doc_title,
        summary=index_tiddler.get("text", "")[:200],
        content="",
        pageStart=1,
        pageEnd=int(index_fields.get("total_pages", 1)),
        children=section_nodes,
        parentId=None,
        metadata={"type": "document", "totalPages": int(index_fields.get("total_pages", 0))},
    )
    return root


async def _write_chunks_to_wiki(slug: str, chunks: List["ContextualizedChunk"], document_title: str, document_summary: str):
    """Write chunk tiddlers to TiddlyWiki MWS."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'vault-pipeline'))
    from mws_client import MWSClient
    from wiki_io import write_chunk_note, write_chunk_index
    from wiki_manager import ensure_wiki

    client = MWSClient(MWS_URL, MWS_ADMIN_USER, MWS_ADMIN_PASSWORD)
    await client.authenticate()
    await ensure_wiki(slug)

    for chunk in chunks:
        i = chunk.metadata.get("chunkIndex", 0)
        m = chunk.metadata
        await write_chunk_note(
            client, slug, i,
            total_chunks=m.get("totalChunks", len(chunks)),
            content=chunk.content,
            parent_context=chunk.parentContext,
            page_start=chunk.pageStart,
            page_end=chunk.pageEnd,
            token_count=chunk.tokenCount,
            level=chunk.level,
            has_overlap=m.get("hasOverlap", False),
            source_wikilink=f"[[Source Index]]",
        )

    await write_chunk_index(
        client, slug,
        total_chunks=len(chunks),
        total_tokens=sum(c.tokenCount for c in chunks),
        document_title=document_title,
        document_summary=document_summary,
    )


@app.post("/chunk-from-vault", response_model=ChunkFromVaultResponse)
async def chunk_from_vault(request: ChunkFromVaultRequest):
    """
    Read section notes, chunk them, and write chunk notes back.
    Routes to Obsidian vault or TiddlyWiki MWS based on STORAGE_BACKEND.
    """
    try:
        if STORAGE_BACKEND == "wiki":
            tree = await _reconstruct_tree_from_wiki(request.slug)
            chunker = SemanticChunker(
                max_tokens=request.maxTokens,
                overlap_tokens=request.overlapTokens,
            )
            chunks = chunker.generate_chunks(tree)
            await _write_chunks_to_wiki(request.slug, chunks, tree.title, tree.summary)
        else:
            tree = _reconstruct_tree_from_vault(request.slug)
            chunker = SemanticChunker(
                max_tokens=request.maxTokens,
                overlap_tokens=request.overlapTokens,
            )
            chunks = chunker.generate_chunks(tree)
            _write_chunks_to_vault(request.slug, chunks, tree.title, tree.summary)

        return ChunkFromVaultResponse(
            success=True,
            slug=request.slug,
            totalChunks=len(chunks),
            totalTokens=sum(c.tokenCount for c in chunks),
            documentTitle=tree.title,
            documentSummary=tree.summary,
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5003)
