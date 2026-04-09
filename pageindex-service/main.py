"""
PageIndex Service v3

Two additions over v2:
  1. Cross-page section stitching  — headings that span multiple pages are merged
     into one section node covering all their content, regardless of page breaks.
  2. LLM summaries via Ollama      — each section node gets a real summary generated
     by ministral-3:14b-cloud instead of a dumb first-sentence cut.

Pipeline: liteparse paragraphs → stitch sections → build tree → generate summaries
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import re
import httpx
import asyncio
import logging

logger = logging.getLogger("pageindex")

app = FastAPI(title="PageIndex Service", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "ministral-3:14b-cloud"

# Minimum words a section needs before we bother asking the LLM to summarise it
LLM_SUMMARY_MIN_WORDS = 30

# ═══════════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class Paragraph(BaseModel):
    text: str
    x: float
    y: float
    width: float
    height: float
    avgFontSize: float = 12
    lineCount: int = 1
    isHeading: bool = False
    headingLevel: int = 0
    isList: bool = False
    isFooter: bool = False
    isTable: bool = False

class Page(BaseModel):
    pageNum: int
    paragraphs: List[Paragraph]

class LiteParseResult(BaseModel):
    filename: str
    text: str
    pages: List[Page]
    metadata: Dict[str, Any]

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

class PageIndexRequest(BaseModel):
    liteparse_result: LiteParseResult
    generate_summaries: bool = True    # set False to skip LLM calls (faster, for debugging)

class PageIndexResponse(BaseModel):
    success: bool
    tree: PageIndexNode
    nodeCount: int
    summariesGenerated: int

# ═══════════════════════════════════════════════════════════════════════════════
# OLLAMA LLM HELPER
# ═══════════════════════════════════════════════════════════════════════════════

async def llm_summarise(title: str, content: str, page_range: str) -> str:
    """
    Ask Ollama to generate a concise section summary for use as RAG context.
    Falls back to first-sentences heuristic if Ollama is unavailable.
    """
    words = content.split()
    if len(words) < LLM_SUMMARY_MIN_WORDS:
        return content[:200]

    # Truncate to ~800 words to keep the prompt fast
    excerpt = " ".join(words[:800])
    if len(words) > 800:
        excerpt += " [...]"

    prompt = (
        f"You are summarising a section of a legal/regulatory document for use as RAG retrieval context.\n"
        f"Section title: {title or '(untitled)'}\n"
        f"Pages: {page_range}\n\n"
        f"Content:\n{excerpt}\n\n"
        f"Write ONE concise sentence (max 40 words) that captures what this section is about. "
        f"Be specific — mention key obligations, parties, or thresholds. "
        f"Do not start with 'This section'. Output only the sentence, no prefix."
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(OLLAMA_URL, json={
                "model":  OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 80}
            })
            resp.raise_for_status()
            raw = resp.json().get("response", "").strip()
            # Strip markdown bold markers if model returns **text**
            raw = re.sub(r'\*\*(.+?)\*\*', r'\1', raw).strip('"').strip()
            return raw if raw else _fallback_summary(content)
    except Exception as e:
        logger.warning(f"Ollama unavailable ({e}), using fallback summary")
        return _fallback_summary(content)


def _fallback_summary(content: str, n: int = 2, max_chars: int = 200) -> str:
    if not content.strip():
        return ""
    sentences = re.split(r'(?<=[.!?])\s+', content.strip())
    summary = " ".join(sentences[:n])
    return summary[:max_chars - 3] + "..." if len(summary) > max_chars else summary


# ═══════════════════════════════════════════════════════════════════════════════
# CROSS-PAGE SECTION STITCHER
# ═══════════════════════════════════════════════════════════════════════════════

class SectionStitcher:
    """
    Converts the flat, page-scoped paragraph list from liteparse into a
    flat list of "stitched sections" where each section owns ALL paragraphs
    that belong to it, regardless of page boundaries.

    Example: CHAPTER III spans pages 5-12. Liteparse gives paragraphs
    scattered across 8 pages. After stitching, one section entry holds
    all of them with pageStart=5, pageEnd=12.
    """

    def stitch(self, pages: List[Page]) -> List[Dict]:
        """
        Returns a flat list of dicts:
          {
            'isHeading': bool,
            'headingLevel': int,
            'text': str,
            'pageNum': int,
            'para': Paragraph
          }
        sorted in reading order (page → y), with footers removed.
        """
        flat = []
        for page in pages:
            for para in page.paragraphs:
                if para.isFooter:
                    continue
                flat.append({
                    'para':         para,
                    'pageNum':      page.pageNum,
                    'isHeading':    para.isHeading,
                    'headingLevel': para.headingLevel,
                    'text':         para.text,
                    'sort_key':     page.pageNum * 100_000 + para.y,
                })
        flat.sort(key=lambda x: x['sort_key'])
        return flat


# ═══════════════════════════════════════════════════════════════════════════════
# TREE BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

class PageIndexBuilder:

    def __init__(self, result: LiteParseResult):
        self.result  = result
        self._counter = 0

    def _id(self) -> str:
        self._counter += 1
        return f"node-{self._counter}"

    # ── Public entry point ───────────────────────────────────────────────────

    def build_tree(self) -> PageIndexNode:
        flat = SectionStitcher().stitch(self.result.pages)
        level_map = self._normalize_levels(flat)

        root = PageIndexNode(
            id=self._id(),
            level=0,
            title=self.result.filename,
            summary="",          # filled by LLM after tree is built
            content=self.result.text,
            pageStart=self.result.pages[0].pageNum  if self.result.pages else 1,
            pageEnd=self.result.pages[-1].pageNum   if self.result.pages else 1,
            children=[],
            metadata={
                'type':        'document',
                'totalPages':  self.result.metadata.get('totalPages', 0),
                'totalChars':  self.result.metadata.get('characterCount', 0),
            }
        )
        root.children = self._build_sections(flat, level_map)
        return root

    # ── Level normalisation ──────────────────────────────────────────────────

    def _normalize_levels(self, flat: List[Dict]) -> Dict[int, int]:
        """
        Map whatever heading levels liteparse produced → tree levels 1/2/3.
        If the doc only uses H2 and H3, map H2→1, H3→2.
        """
        used = sorted(set(
            i['headingLevel'] for i in flat
            if i['isHeading'] and i['headingLevel'] > 0
        ))
        return {orig: min(idx + 1, 3) for idx, orig in enumerate(used)}

    # ── Section builder with cross-page stitching ────────────────────────────

    def _build_sections(self, flat: List[Dict], level_map: Dict[int, int]) -> List[PageIndexNode]:
        """
        Walk the flat paragraph list, group into a hierarchy.

        Cross-page stitching happens naturally: we never reset the current
        section when a page boundary occurs — only when a new heading at the
        same or higher level appears.  So a section that starts on p5 and
        whose content continues through p12 without a new chapter heading
        accumulates all paragraphs from p5–p12 in one node.
        """
        sections: List[PageIndexNode] = []

        # current[tree_level] = the open section node at that level
        current: Dict[int, Optional[PageIndexNode]] = {1: None, 2: None, 3: None}
        pending: List[Dict] = []   # body paragraphs waiting to be attached

        def flush(parent: Optional[PageIndexNode], items: List[Dict]):
            if not items or parent is None:
                return
            texts  = [i['para'].text for i in items]
            joined = " ".join(texts)
            leaf   = PageIndexNode(
                id=self._id(),
                level=parent.level + 1,
                title="",
                summary="",      # filled later
                content=joined,
                pageStart=items[0]['pageNum'],
                pageEnd=items[-1]['pageNum'],
                children=[],
                metadata={
                    'type':      'content',
                    'wordCount': len(joined.split()),
                    'paraCount': len(items),
                    'hasList':   any(i['para'].isList for i in items),
                }
            )
            # Extend parent's pageEnd across page boundaries
            if leaf.pageEnd > parent.pageEnd:
                parent.pageEnd = leaf.pageEnd
            parent.children.append(leaf)

        def nearest(below_level: int) -> Optional[PageIndexNode]:
            for lvl in range(below_level - 1, 0, -1):
                if current[lvl] is not None:
                    return current[lvl]
            return None

        def make_section(item: Dict, tree_level: int) -> PageIndexNode:
            title = re.sub(r'^\d+(\.\d+)*\.?\s*', '', item['para'].text).strip()
            return PageIndexNode(
                id=self._id(),
                level=tree_level,
                title=title or item['para'].text,
                summary="",      # filled by LLM
                content="",      # filled in _finalize
                pageStart=item['pageNum'],
                pageEnd=item['pageNum'],
                children=[],
                metadata={
                    'type':         'section',
                    'headingLevel': item['headingLevel'],
                    'avgFontSize':  item['para'].avgFontSize,
                    'rawHeading':   item['para'].text,
                }
            )

        for item in flat:
            if not (item['isHeading'] and item['headingLevel'] > 0):
                pending.append(item)
                continue

            tree_level = level_map.get(item['headingLevel'], 3)

            # Flush pending content to the deepest open section
            flush(nearest(tree_level + 1) or nearest(4), pending)
            pending = []

            # Close all sections at this level and deeper
            for lvl in range(tree_level, 4):
                current[lvl] = None

            node = make_section(item, tree_level)

            if tree_level == 1:
                sections.append(node)
            else:
                parent = nearest(tree_level)
                if parent is not None:
                    # Cross-page: extend parent's pageEnd if this heading is on a later page
                    if node.pageStart > parent.pageEnd:
                        parent.pageEnd = node.pageStart
                    parent.children.append(node)
                else:
                    sections.append(node)   # promote orphan to top level

            current[tree_level] = node

        # Flush any trailing content
        flush(nearest(4), pending)

        if not sections:
            joined = " ".join(i['para'].text for i in flat)
            sections.append(PageIndexNode(
                id=self._id(), level=1,
                title="Document Content", summary="",
                content=joined,
                pageStart=flat[0]['pageNum'] if flat else 1,
                pageEnd=flat[-1]['pageNum']  if flat else 1,
                children=[],
                metadata={'type': 'section', 'headingLevel': 0}
            ))

        self._finalize(sections)
        return sections

    # ── Back-fill content / pageEnd for section nodes ────────────────────────

    def _finalize(self, nodes: List[PageIndexNode]):
        for node in nodes:
            self._finalize(node.children)
            if node.metadata.get('type') == 'section':
                node.content = self._collect_text(node)
                node.pageEnd = self._max_page(node)

    def _collect_text(self, node: PageIndexNode) -> str:
        if not node.children:
            return node.content
        return " ".join(self._collect_text(c) for c in node.children if c.content or c.children)

    def _max_page(self, node: PageIndexNode) -> int:
        if not node.children:
            return node.pageEnd
        return max(self._max_page(c) for c in node.children)


# ═══════════════════════════════════════════════════════════════════════════════
# LLM SUMMARY PASS  (async, concurrent)
# ═══════════════════════════════════════════════════════════════════════════════

async def generate_summaries(root: PageIndexNode) -> int:
    """
    Walk the tree and fire LLM summary calls concurrently for all section nodes.
    Content leaves get a fallback summary (no LLM — they go straight into semchunk).
    Returns the number of LLM calls made.
    """
    tasks = []

    def collect(node: PageIndexNode):
        if node.metadata.get('type') == 'section' and node.content:
            page_range = (f"p{node.pageStart}" if node.pageStart == node.pageEnd
                          else f"p{node.pageStart}-{node.pageEnd}")
            tasks.append((node, page_range))
        elif node.metadata.get('type') == 'content':
            # Leaf — use fast fallback, no LLM
            node.summary = _fallback_summary(node.content)
        for child in node.children:
            collect(child)

    collect(root)

    # Run all LLM calls concurrently
    async def fill(node: PageIndexNode, page_range: str):
        node.summary = await llm_summarise(node.title, node.content, page_range)

    await asyncio.gather(*[fill(node, pr) for node, pr in tasks])
    return len(tasks)


# ═══════════════════════════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    return {"message": "PageIndex Service", "version": "3.0.0"}

@app.get("/health")
async def health():
    return {"status": "ok", "service": "PageIndex"}

@app.post("/build-tree", response_model=PageIndexResponse)
async def build_tree(request: PageIndexRequest):
    try:
        builder = PageIndexBuilder(request.liteparse_result)
        tree    = builder.build_tree()

        summaries_generated = 0
        if request.generate_summaries:
            summaries_generated = await generate_summaries(tree)
            # Root document summary: summarise the first few section summaries
            section_summaries = [c.summary for c in tree.children if c.summary][:4]
            if section_summaries:
                tree.summary = await llm_summarise(
                    tree.title,
                    " ".join(section_summaries),
                    f"p{tree.pageStart}-{tree.pageEnd}"
                )

        def count_nodes(n: PageIndexNode) -> int:
            return 1 + sum(count_nodes(c) for c in n.children)

        return PageIndexResponse(
            success=True,
            tree=tree,
            nodeCount=count_nodes(tree),
            summariesGenerated=summaries_generated
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5002)
