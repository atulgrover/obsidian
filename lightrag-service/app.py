"""
LightRAG service — ingestion + query + audit API

POST /ingest              Accept semchunk output → contextual enrichment → LightRAG
POST /query               Hybrid BM25 + vector search with RRF fusion + metadata filters
GET  /ingest/check        Dry-run: show what would be ingested / skipped by hash diff
GET  /health
GET  /audit               Global stats across all sources
GET  /audit/source?src=   Per-source: chunk list with status, run history
GET  /audit/runs?limit=   Recent ingest run log

Tier-1 quality improvements in effect:
  - Contextual Retrieval: Sarvam AI generates a 2–3 sentence situating blurb per chunk
  - Metadata extraction: doc_type, doc_date, parties, statutory_refs (LLM + regex)
  - 75-token overlap already applied upstream by semchunk service
  - Hybrid BM25 + vector search with RRF fusion (POST /query)
  - Metadata pre-filtering on doc_type, doc_date, parties, statutory_refs
  - Embedding stored in rag2_chunks for direct pgvector ANN search
  - Hash-based dedup: identical enriched text is skipped on re-ingest

Storage backends (all Postgres):
  KV store   → PGKVStorage
  Vectors    → PGVectorStorage  (pgvector)
  Graph      → PGGraphStorage   (Apache AGE)
"""

import os
import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any, Tuple

import httpx
import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from lightrag import LightRAG
from lightrag.utils import EmbeddingFunc
from lightrag.llm.openai import openai_complete_if_cache
import lightrag.prompt as _lightrag_prompt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Indian Legal Entity Taxonomy — Tier 2 patch
#
# LightRAG reads entity_types from the ENTITY_TYPES env var (JSON array).
# We ALSO patch the built-in few-shot examples here so the LLM sees
# consistent types in both the instruction and the examples.
# Without this patch the examples show "Organization"/"Location" etc.
# while the instruction says "CourtTribunal"/"StatuteProvision" — the
# mismatch causes unreliable type compliance in sarvam-m output.
# ─────────────────────────────────────────────────────────────
_LEGAL_ENTITY_EXAMPLES = [
    """<Entity_types>
["Person","Organization","Location","CourtTribunal","StatuteProvision","LegalConcept","RegulatoryInstrument","PartyRole","CaseReference"]

<Input Text>
```
The National Company Law Tribunal, Mumbai Bench, vide its order dated 12.03.2021 in CP (IB) No. 1234/MB/2019, admitted the petition filed by State Bank of India under Section 7 of the Insolvency and Bankruptcy Code, 2016 against ABC Infra Private Limited. The Hon'ble Bench comprising Justice Pradeep Narayan Deshmukh (Technical Member) appointed Mr. Rajesh Kumar Gupta as the Interim Resolution Professional. The Committee of Creditors, constituted under Section 21 of the IBC, approved the resolution plan submitted by XYZ Reconstruction Company Limited at its 8th CoC meeting with 88.5% voting share. The resolution plan provided for payment of ₹142 crore against the total admitted claims of ₹1,840 crore, resulting in a haircut of approximately 92.3% for the financial creditors.
```

<Output>
entity<|#|>National Company Law Tribunal, Mumbai Bench<|#|>CourtTribunal<|#|>The NCLT Mumbai Bench is the adjudicating authority under the IBC that admitted the insolvency petition against ABC Infra Private Limited and supervised the CIRP.
entity<|#|>State Bank Of India<|#|>Organization<|#|>State Bank of India is the financial creditor that filed the Section 7 petition initiating the corporate insolvency resolution process against ABC Infra Private Limited.
entity<|#|>ABC Infra Private Limited<|#|>Organization<|#|>ABC Infra Private Limited is the corporate debtor against whom the insolvency petition was admitted by the NCLT Mumbai Bench.
entity<|#|>Justice Pradeep Narayan Deshmukh<|#|>Person<|#|>Technical Member of the NCLT Mumbai Bench who presided over the matter in CP (IB) No. 1234/MB/2019.
entity<|#|>Rajesh Kumar Gupta<|#|>Person<|#|>Rajesh Kumar Gupta was appointed as the Interim Resolution Professional to manage the affairs of the corporate debtor during the CIRP period.
entity<|#|>XYZ Reconstruction Company Limited<|#|>Organization<|#|>XYZ Reconstruction Company Limited is the successful resolution applicant whose plan was approved by the Committee of Creditors with 88.5% voting share.
entity<|#|>Section 7 Insolvency And Bankruptcy Code 2016<|#|>StatuteProvision<|#|>Section 7 of the IBC 2016 enables a financial creditor to file an application for initiation of corporate insolvency resolution process against a corporate debtor.
entity<|#|>Section 21 Insolvency And Bankruptcy Code 2016<|#|>StatuteProvision<|#|>Section 21 of the IBC 2016 governs the constitution and functioning of the Committee of Creditors in a CIRP.
entity<|#|>Corporate Insolvency Resolution Process<|#|>LegalConcept<|#|>The Corporate Insolvency Resolution Process (CIRP) is the time-bound restructuring mechanism under the IBC 2016 triggered upon admission of an insolvency petition.
entity<|#|>Committee Of Creditors<|#|>PartyRole<|#|>The Committee of Creditors is the decision-making body of financial creditors constituted under Section 21 IBC, which approved the resolution plan with 88.5% voting share.
entity<|#|>Interim Resolution Professional<|#|>PartyRole<|#|>The Interim Resolution Professional is appointed by the adjudicating authority to manage the corporate debtor's affairs and constitute the CoC during the initial phase of CIRP.
entity<|#|>CP (IB) No. 1234/MB/2019<|#|>CaseReference<|#|>Company Petition No. 1234/MB/2019 is the case reference for the insolvency proceedings filed by SBI against ABC Infra Private Limited before the NCLT Mumbai Bench.
entity<|#|>Mumbai<|#|>Location<|#|>Mumbai is the seat of the NCLT bench adjudicating the insolvency proceedings in CP (IB) No. 1234/MB/2019.
relation<|#|>State Bank Of India<|#|>ABC Infra Private Limited<|#|>financial creditor, insolvency petition<|#|>State Bank of India filed a Section 7 petition against ABC Infra Private Limited initiating the CIRP before the NCLT Mumbai Bench.
relation<|#|>National Company Law Tribunal, Mumbai Bench<|#|>Rajesh Kumar Gupta<|#|>appointment, insolvency administration<|#|>The NCLT Mumbai Bench appointed Rajesh Kumar Gupta as the Interim Resolution Professional for ABC Infra Private Limited.
relation<|#|>Committee Of Creditors<|#|>XYZ Reconstruction Company Limited<|#|>resolution plan approval, voting<|#|>The Committee of Creditors approved the resolution plan submitted by XYZ Reconstruction Company Limited with 88.5% voting share at its 8th CoC meeting.
relation<|#|>Corporate Insolvency Resolution Process<|#|>Section 7 Insolvency And Bankruptcy Code 2016<|#|>statutory trigger, legal framework<|#|>The CIRP against ABC Infra was initiated under Section 7 of the IBC 2016 upon admission of the financial creditor's petition.
<|COMPLETE|>

""",
    """<Entity_types>
["Person","Organization","Location","CourtTribunal","StatuteProvision","LegalConcept","RegulatoryInstrument","PartyRole","CaseReference"]

<Input Text>
```
The Securities and Exchange Board of India, vide Circular No. SEBI/HO/CFD/CMD1/CIR/P/2021/0000000665 dated August 05, 2021, amended the SEBI (Listing Obligations and Disclosure Requirements) Regulations, 2015 with respect to related party transactions. The circular, effective from April 01, 2022, mandates that all material related party transactions require prior approval of shareholders by ordinary resolution, with related parties abstaining from voting. The National Stock Exchange of India and BSE Limited were directed to bring the provisions of this circular to the notice of all listed entities. Non-compliance with these provisions may attract action under Section 15HB of the SEBI Act, 1992, which provides for penalty of up to ₹25 crore or three times the amount of profits made, whichever is higher.
```

<Output>
entity<|#|>Securities And Exchange Board Of India<|#|>Organization<|#|>SEBI is the statutory regulator for securities markets in India that issued the circular amending related party transaction norms for listed entities.
entity<|#|>SEBI/HO/CFD/CMD1/CIR/P/2021/0000000665<|#|>RegulatoryInstrument<|#|>SEBI Circular dated August 05, 2021 amending SEBI (LODR) Regulations 2015 with respect to related party transaction approval requirements, effective April 01, 2022.
entity<|#|>SEBI (Listing Obligations And Disclosure Requirements) Regulations 2015<|#|>RegulatoryInstrument<|#|>The SEBI LODR Regulations 2015 govern the disclosure and compliance obligations of listed entities in India, amended by the August 2021 circular on related party transactions.
entity<|#|>Section 15HB SEBI Act 1992<|#|>StatuteProvision<|#|>Section 15HB of the SEBI Act 1992 prescribes penalties for non-compliance with SEBI regulations, including fines up to ₹25 crore or three times the profits made from the violation.
entity<|#|>National Stock Exchange Of India<|#|>Organization<|#|>NSE is a stock exchange directed by SEBI to circulate the RPT circular provisions to all listed entities trading on its platform.
entity<|#|>BSE Limited<|#|>Organization<|#|>BSE Limited is a stock exchange directed by SEBI to circulate the RPT circular provisions to all listed entities trading on its platform.
entity<|#|>Related Party Transaction<|#|>LegalConcept<|#|>A related party transaction is a business deal between a listed entity and its related parties, now requiring prior shareholder approval by ordinary resolution under the amended LODR regulations.
entity<|#|>Ordinary Resolution<|#|>LegalConcept<|#|>An ordinary resolution requires approval by a simple majority of shareholders; the amended SEBI LODR regulations mandate this for material related party transactions, with related parties barred from voting.
entity<|#|>Listed Entity<|#|>PartyRole<|#|>Listed entities are companies whose securities are traded on stock exchanges, subject to SEBI LODR Regulations including the amended related party transaction norms.
relation<|#|>Securities And Exchange Board Of India<|#|>SEBI/HO/CFD/CMD1/CIR/P/2021/0000000665<|#|>regulatory issuance, amendment<|#|>SEBI issued the circular amending the LODR Regulations 2015 on related party transactions.
relation<|#|>SEBI/HO/CFD/CMD1/CIR/P/2021/0000000665<|#|>SEBI (Listing Obligations And Disclosure Requirements) Regulations 2015<|#|>amendment, regulatory instrument<|#|>The circular directly amends the SEBI LODR Regulations 2015 with respect to related party transaction approval requirements.
relation<|#|>Securities And Exchange Board Of India<|#|>National Stock Exchange Of India<|#|>regulatory direction, dissemination<|#|>SEBI directed NSE to bring the circular provisions to the notice of all listed entities on its platform.
relation<|#|>Related Party Transaction<|#|>Ordinary Resolution<|#|>approval mechanism, governance requirement<|#|>Material related party transactions now require prior shareholder approval by ordinary resolution under the amended LODR regulations.
relation<|#|>Section 15HB SEBI Act 1992<|#|>Related Party Transaction<|#|>penalty, enforcement<|#|>Non-compliance with the related party transaction norms attracts penalty under Section 15HB of the SEBI Act 1992.
<|COMPLETE|>

""",
]

_lightrag_prompt.PROMPTS["entity_extraction_examples"] = _LEGAL_ENTITY_EXAMPLES
logger.info("Patched LightRAG entity extraction examples with Indian legal domain examples.")

# ─────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────
POSTGRES_HOST     = os.environ["POSTGRES_HOST"]
POSTGRES_PORT     = int(os.getenv("POSTGRES_PORT", 5432))
POSTGRES_DB       = os.environ["POSTGRES_DB"]
POSTGRES_USER     = os.environ["POSTGRES_USER"]
POSTGRES_PASSWORD = os.environ["POSTGRES_PASSWORD"]
AGE_GRAPH_NAME    = os.getenv("AGE_GRAPH_NAME", "lightrag_graph")

SARVAM_API_KEY    = os.environ["SARVAM_API_KEY"]
SARVAM_BASE_URL   = os.getenv("SARVAM_BASE_URL", "https://api.sarvam.ai/v1")
SARVAM_MODEL      = os.getenv("SARVAM_MODEL", "sarvam-m")

EMBEDDING_URL     = os.environ["EMBEDDING_URL"]
EMBEDDING_DIM     = int(os.getenv("EMBEDDING_DIM", 768))
EMBEDDING_MAX_TOK = int(os.getenv("EMBEDDING_MAX_TOKENS", 512))
WORKING_DIR       = os.getenv("WORKING_DIR", "/data")

CONTEXTUAL_RETRIEVAL = os.getenv("CONTEXTUAL_RETRIEVAL", "true").lower() == "true"
_CONTEXT_SEMAPHORE   = asyncio.Semaphore(5)


# ─────────────────────────────────────────────────────────────
# LLM — Sarvam AI
# ─────────────────────────────────────────────────────────────
async def sarvam_llm(prompt, system_prompt=None, history_messages=[], **kwargs):
    return await openai_complete_if_cache(
        SARVAM_MODEL, prompt,
        system_prompt=system_prompt,
        history_messages=history_messages,
        base_url=SARVAM_BASE_URL,
        api_key=SARVAM_API_KEY,
        **kwargs,
    )


# ─────────────────────────────────────────────────────────────
# Embeddings — InLegal-SBERT
# ─────────────────────────────────────────────────────────────
async def sbert_embed(texts: List[str]) -> List[List[float]]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            EMBEDDING_URL,
            json={"input": texts, "model": "inlegal-sbert"},
        )
        resp.raise_for_status()
        data = resp.json()
    items = sorted(data["data"], key=lambda x: x["index"])
    return [item["embedding"] for item in items]


# ─────────────────────────────────────────────────────────────
# Contextual Retrieval + Metadata Extraction (Anthropic 2024)
# ─────────────────────────────────────────────────────────────
_CONTEXT_SYSTEM = (
    "You are a legal document analyst processing Indian insolvency and financial "
    "regulation documents. For the given chunk, provide:\n\n"
    "1. A 2–3 sentence situating context identifying document type, parties, "
    "court/regulator, statutory framework, and time period.\n"
    "2. Structured metadata as JSON.\n\n"
    "Respond with EXACTLY two sections separated by '---JSON---':\n\n"
    "First section: the situating context (max 80 words, no labels or preamble).\n\n"
    "Second section (after ---JSON---): a JSON object with keys:\n"
    "  - doc_type: one of ibbi_order, sebi_circular, nclt_judgment, nclat_order, circular, other\n"
    "  - doc_date: document date as YYYY-MM-DD, or null\n"
    "  - parties: array of party names (corporate debtor, RP, CoC, financial creditors, etc.)\n"
    "  - statutory_refs: array of statute/section references (e.g. 'Section 53 IBC 2016')\n\n"
    "Example response:\n"
    "This is a liquidation order by NCLT Mumbai concerning ABC Steel Pvt Ltd, "
    "appointing Mr X as liquidator under Section 33 of IBC 2016.\n"
    "---JSON---\n"
    '{\"doc_type\": \"ibbi_order\", \"doc_date\": \"2023-09-15\", '
    '\"parties\": [\"ABC Steel Pvt Ltd\", \"Mr X (Liquidator)\"], '
    '\"statutory_refs\": [\"Section 33 IBC 2016\"]}'
)

# Regex patterns for statutory references the LLM might miss
_STATUTORY_REF_PATTERNS = [
    re.compile(r'Section\s+\d+[A-Z]?(?:\s*\(\d+\))?\s+(?:of\s+)?(?:the\s+)?(?:IBC|Insolvency\s+and\s+Bankruptcy\s+Code)', re.I),
    re.compile(r'Regulation\s+\d+(?:\s*\([^)]+\))?\s+(?:of\s+)?(?:SEBI|the\s+SEBI)', re.I),
    re.compile(r'Rule\s+\d+(?:\s*\([^)]+\))?\s+(?:of\s+)?(?:the\s+)?(?:Companies\s+Act|Companies\s+Amendment)', re.I),
    re.compile(r'Section\s+\d+[A-Z]?(?:\s*\(\d+\))?\s+(?:of\s+)?(?:the\s+)?Companies\s+Act', re.I),
    re.compile(r'Article\s+\d+[A-Z]?\s+(?:of\s+)?(?:the\s+)?Constitution', re.I),
]

def _extract_statutory_refs_regex(text: str) -> List[str]:
    """Extract statutory references via regex. Returns deduplicated list."""
    refs = set()
    for pattern in _STATUTORY_REF_PATTERNS:
        for m in pattern.finditer(text):
            refs.add(m.group(0).strip())
    return sorted(refs)


class ChunkMetadata(BaseModel):
    doc_type: Optional[str] = None
    doc_date: Optional[str] = None
    parties: List[str] = []
    statutory_refs: List[str] = []


async def _generate_context_and_metadata(
    chunk_id: str, content: str, parent_context: Optional[str],
    doc_title: str, doc_summary: str
) -> Tuple[str, ChunkMetadata]:
    """
    Returns (context_text, metadata).
    Single LLM call produces both situating context and structured metadata.
    Falls back to regex-only metadata if LLM fails.
    """
    parts = [f"Document: {doc_title}", f"Summary: {doc_summary}"]
    if parent_context:
        parts.append(f"Section path: {parent_context}")
    parts.append(f"\nChunk:\n{content[:1200]}")
    prompt = "\n".join(parts)

    context_text = ""
    metadata = ChunkMetadata()

    # Regex-based statutory refs (always extracted, merged with LLM output)
    regex_refs = _extract_statutory_refs_regex(content)

    if CONTEXTUAL_RETRIEVAL and doc_title:
        async with _CONTEXT_SEMAPHORE:
            try:
                raw = await sarvam_llm(prompt, system_prompt=_CONTEXT_SYSTEM, max_tokens=300)
                if raw:
                    raw = raw.strip()
                    # Parse: context text before ---JSON---, metadata JSON after
                    json_marker = "---JSON---"
                    if json_marker in raw:
                        ctx_part, meta_part = raw.split(json_marker, 1)
                        context_text = ctx_part.strip()
                        try:
                            meta_dict = json.loads(meta_part.strip())
                            metadata = ChunkMetadata(
                                doc_type=meta_dict.get("doc_type"),
                                doc_date=meta_dict.get("doc_date"),
                                parties=meta_dict.get("parties", []),
                                statutory_refs=meta_dict.get("statutory_refs", []),
                            )
                        except (json.JSONDecodeError, Exception):
                            logger.warning(f"Metadata JSON parse failed for {chunk_id}, using context only")
                    else:
                        # LLM didn't output JSON marker — treat entire response as context
                        context_text = raw
            except Exception as e:
                logger.warning(f"Context+metadata gen failed for {chunk_id}: {e}")

    # Merge regex refs with LLM refs (dedup)
    all_refs = sorted(set(metadata.statutory_refs + regex_refs))
    metadata.statutory_refs = all_refs

    return context_text, metadata


async def _build_enriched_text(
    chunk: 'Chunk', doc_title: str, doc_summary: str
) -> Tuple[str, str, bool, ChunkMetadata]:
    """
    Returns (enriched_text, context_text, context_generated, metadata).
    enriched_text = what gets passed to rag.ainsert()
    context_text  = the Sarvam-generated blurb alone (for audit)
    metadata      = extracted doc_type, doc_date, parties, statutory_refs
    """
    context_text = ""
    context_generated = False
    metadata = ChunkMetadata()
    parts = []

    if CONTEXTUAL_RETRIEVAL and doc_title:
        context_text, metadata = await _generate_context_and_metadata(
            chunk.id, chunk.content, chunk.parentContext, doc_title, doc_summary
        )
        # Allow chunk-level metadata overrides from upstream
        if chunk.docType and not metadata.doc_type:
            metadata.doc_type = chunk.docType
        if chunk.docDate and not metadata.doc_date:
            metadata.doc_date = chunk.docDate
        if chunk.parties and not metadata.parties:
            metadata.parties = chunk.parties
        if chunk.statutoryRefs and not metadata.statutory_refs:
            metadata.statutory_refs = chunk.statutoryRefs

        if context_text:
            parts.append(f"[Situating Context]\n{context_text}")
            context_generated = True

    if chunk.parentContext:
        parts.append(f"[Section Path]\n{chunk.parentContext.strip()}")

    parts.append(f"[Content]\n{chunk.content.strip()}")

    return "\n\n".join(parts), context_text, context_generated, metadata


# ─────────────────────────────────────────────────────────────
# Postgres helpers
# ─────────────────────────────────────────────────────────────
def _pg_conn():
    return psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT, dbname=POSTGRES_DB,
        user=POSTGRES_USER, password=POSTGRES_PASSWORD,
    )


def _write_audit(
    run_id: str,
    source: str,
    doc_title: str,
    chunks_total: int,
    chunk_results: List[Tuple['Chunk', str, str, bool, bool, Optional[str], 'ChunkMetadata']],
    duration_ms: int,
):
    """
    chunk_results: list of (chunk, enriched_text, context_text, context_generated, success, error, metadata)
    Writes to rag2_ingest_log and rag2_chunks.
    """
    ingested = sum(1 for _, _, _, _, ok, _, _ in chunk_results if ok)
    failed   = sum(1 for _, _, _, _, ok, _, _ in chunk_results if not ok)
    skipped  = chunks_total - len(chunk_results)
    status   = "success" if failed == 0 else ("partial" if ingested > 0 else "failed")

    try:
        conn = _pg_conn()
        with conn:
            with conn.cursor() as cur:
                # ingest run record
                cur.execute(
                    """
                    INSERT INTO rag2_ingest_log
                        (run_id, source, document_title, chunks_total, chunks_ingested,
                         chunks_skipped, chunks_failed, duration_ms, contextual_retrieval, status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (run_id, source, doc_title, chunks_total, ingested,
                     skipped, failed, duration_ms, CONTEXTUAL_RETRIEVAL, status)
                )

                # per-chunk rows (now includes metadata + embedding)
                rows = []
                for chunk, enriched_text, context_text, context_generated, success, error, meta in chunk_results:
                    text_hash = hashlib.md5(enriched_text.encode()).hexdigest() if enriched_text else None
                    # Parse doc_date string to date object for Postgres
                    doc_date_val = None
                    if meta and meta.doc_date:
                        try:
                            from datetime import date as date_type
                            doc_date_val = date_type.fromisoformat(meta.doc_date)
                        except (ValueError, TypeError):
                            doc_date_val = None

                    # Convert embedding list to Postgres-compatible format
                    embedding_val = chunk.metadata.get('_embedding') if chunk.metadata else None

                    rows.append((
                        chunk.id, source, run_id, doc_title,
                        chunk.pageStart, chunk.pageEnd,
                        chunk.metadata.get('chunkIndex', 0) if chunk.metadata else 0,
                        chunk.parentContext, chunk.tokenCount,
                        chunk.content,
                        meta.doc_type if meta else None,
                        doc_date_val,
                        meta.parties if meta else None,
                        meta.statutory_refs if meta else None,
                        # embedding stored as string for psycopg2 compatibility
                        str(embedding_val) if embedding_val else None,
                        text_hash, context_generated, context_text or None,
                        success,
                        time.strftime('%Y-%m-%d %H:%M:%S') if success else None,
                        error,
                    ))

                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO rag2_chunks
                        (id, source, ingest_run_id, document_title,
                         page_start, page_end, chunk_index, section_path, token_count,
                         content, doc_type, doc_date, parties, statutory_refs, embedding,
                         enriched_text_hash, context_generated, context_text,
                         lightrag_ingested, ingested_at, ingest_error)
                    VALUES %s
                    ON CONFLICT (id) DO UPDATE SET
                        ingest_run_id      = EXCLUDED.ingest_run_id,
                        doc_type           = EXCLUDED.doc_type,
                        doc_date           = EXCLUDED.doc_date,
                        parties            = EXCLUDED.parties,
                        statutory_refs     = EXCLUDED.statutory_refs,
                        embedding          = EXCLUDED.embedding,
                        enriched_text_hash = EXCLUDED.enriched_text_hash,
                        context_generated  = EXCLUDED.context_generated,
                        context_text       = EXCLUDED.context_text,
                        lightrag_ingested  = EXCLUDED.lightrag_ingested,
                        ingested_at        = EXCLUDED.ingested_at,
                        ingest_error       = EXCLUDED.ingest_error
                    """,
                    rows,
                )
        conn.close()
        logger.info(f"Audit written: run={run_id} source='{source}' ingested={ingested} failed={failed}")
    except Exception as e:
        logger.warning(f"Audit write failed (non-fatal): {e}")


# ─────────────────────────────────────────────────────────────
# LightRAG init
# ─────────────────────────────────────────────────────────────
os.environ["AGE_GRAPH_NAME"]    = AGE_GRAPH_NAME
os.environ["POSTGRES_HOST"]     = POSTGRES_HOST
os.environ["POSTGRES_PORT"]     = str(POSTGRES_PORT)
os.environ["POSTGRES_DATABASE"] = POSTGRES_DB
os.environ["POSTGRES_USER"]     = POSTGRES_USER
os.environ["POSTGRES_PASSWORD"] = POSTGRES_PASSWORD

rag: Optional[LightRAG] = None


async def init_rag():
    global rag
    os.makedirs(WORKING_DIR, exist_ok=True)
    rag = LightRAG(
        working_dir=WORKING_DIR,
        llm_model_func=sarvam_llm,
        embedding_func=EmbeddingFunc(
            embedding_dim=EMBEDDING_DIM,
            max_token_size=EMBEDDING_MAX_TOK,
            func=sbert_embed,
        ),
        kv_storage="PGKVStorage",
        vector_storage="PGVectorStorage",
        graph_storage="PGGraphStorage",
    )
    await rag.initialize_storages()
    logger.info(f"LightRAG ready. Contextual retrieval: {'ON' if CONTEXTUAL_RETRIEVAL else 'OFF'}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_rag()
    await _embed_standard_requirements()
    yield


app = FastAPI(title="LightRAG Ingestion Service", version="2.1.0", lifespan=lifespan)

# ──────────────────────────────────────────────────────────────
# Serve LightRAG built-in web UI at /
# ──────────────────────────────────────────────────────────────
import pathlib as _pathlib
from fastapi.staticfiles import StaticFiles as _StaticFiles
from fastapi.responses import FileResponse as _FileResponse

_WEBUI_DIR = _pathlib.Path(__file__).resolve().parent / "webui"
# Check if webui shipped with lightrag package exists
_PKG_WEBUI = _pathlib.Path(
    __import__("lightrag").__file__).resolve().parent / "api" / "webui"
if _PKG_WEBUI.is_dir():
    _WEBUI_DIR = _PKG_WEBUI

if _WEBUI_DIR.is_dir():
    # Stub auth endpoints — no credentials required, always auto-login as guest
    @app.get("/auth-status")
    async def _auth_status():
        import base64, time
        # Create a minimal JWT-like guest token that the frontend expects
        header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b'=').decode()
        payload = base64.urlsafe_b64encode(
            f'{{"sub":"guest","role":"guest","exp":{int(time.time()) + 86400*365}}}'.encode()
        ).rstrip(b'=').decode()
        sig = base64.urlsafe_b64encode(b'stub').rstrip(b'=').decode()
        guest_token = f"{header}.{payload}.{sig}"
        return {"auth_configured": False, "access_token": guest_token}

    @app.post("/login")
    async def _login():
        import base64, time
        header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b'=').decode()
        payload = base64.urlsafe_b64encode(
            f'{{"sub":"guest","role":"guest","exp":{int(time.time()) + 86400*365}}}'.encode()
        ).rstrip(b'=').decode()
        sig = base64.urlsafe_b64encode(b'stub').rstrip(b'=').decode()
        guest_token = f"{header}.{payload}.{sig}"
        return {"access_token": guest_token, "token_type": "bearer"}

    app.mount("/webui/assets", _StaticFiles(directory=_WEBUI_DIR / "assets"), name="webui-assets")

    @app.get("/")
    async def _webui_index():
        return _FileResponse(_WEBUI_DIR / "index.html")

    @app.get("/favicon.png")
    async def _webui_favicon():
        return _FileResponse(_WEBUI_DIR / "favicon.png")

    @app.get("/logo.svg")
    async def _webui_logo():
        return _FileResponse(_WEBUI_DIR / "logo.svg")

    logger.info(f"LightRAG Web UI served from {_WEBUI_DIR}")


# ─────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────
class Chunk(BaseModel):
    id: str
    content: str
    parentContext: Optional[str] = None
    pageStart: int = 0
    pageEnd: int = 0
    tokenCount: int = 0
    metadata: Dict[str, Any] = {}
    # Domain metadata (optional — extracted during ingest if not provided upstream)
    docType: Optional[str] = None
    docDate: Optional[str] = None
    parties: Optional[List[str]] = None
    statutoryRefs: Optional[List[str]] = None


class IngestRequest(BaseModel):
    source: str
    chunks: List[Chunk]
    documentTitle: Optional[str] = None
    documentSummary: Optional[str] = None


class IngestResponse(BaseModel):
    success: bool
    ingested: int
    skipped: int
    failed: int
    source: str
    run_id: str
    contextualRetrieval: bool
    duration_ms: int


# ─────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "lightrag",
            "contextualRetrieval": CONTEXTUAL_RETRIEVAL}


@app.get("/audit")
def audit_global():
    """Global stats: all sources, total chunks, ingested/failed/pending."""
    try:
        conn = _pg_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM rag2_staleness ORDER BY last_ingested_at DESC NULLS LAST")
            sources = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT COUNT(*) AS total_runs, MAX(triggered_at) AS last_run FROM rag2_ingest_log")
            meta = dict(cur.fetchone())
        conn.close()
        return {"sources": sources, "meta": meta}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/audit/source")
def audit_source(src: str = Query(..., description="Source media ID or URL")):
    """Per-source audit: all chunks with status + recent run history."""
    try:
        conn = _pg_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, page_start, page_end, chunk_index, token_count, section_path,
                       lightrag_ingested, ingested_at, context_generated, ingest_error,
                       enriched_text_hash, created_at
                FROM rag2_chunks WHERE source = %s ORDER BY chunk_index
                """,
                (src,)
            )
            chunks = [dict(r) for r in cur.fetchall()]
            cur.execute(
                """
                SELECT run_id, triggered_at, chunks_total, chunks_ingested,
                       chunks_failed, duration_ms, contextual_retrieval, status
                FROM rag2_ingest_log WHERE source = %s
                ORDER BY triggered_at DESC LIMIT 10
                """,
                (src,)
            )
            runs = [dict(r) for r in cur.fetchall()]
        conn.close()
        ingested = sum(1 for c in chunks if c['lightrag_ingested'])
        failed   = sum(1 for c in chunks if c['ingest_error'])
        return {
            "source": src,
            "summary": {
                "total": len(chunks), "ingested": ingested,
                "failed": failed, "pending": len(chunks) - ingested - failed,
            },
            "chunks": chunks,
            "runs": runs,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/audit/runs")
def audit_runs(limit: int = Query(20, le=100)):
    """Recent ingest run history across all sources."""
    try:
        conn = _pg_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT run_id, source, document_title, triggered_at, triggered_by,
                       chunks_total, chunks_ingested, chunks_failed,
                       duration_ms, contextual_retrieval, status
                FROM rag2_ingest_log ORDER BY triggered_at DESC LIMIT %s
                """,
                (limit,)
            )
            runs = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"runs": runs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ingest/check")
def ingest_check(src: str = Query(...)):
    """
    Dry-run: compare semchunk cache against rag2_chunks.enriched_text_hash.
    Returns which chunks would be ingested vs skipped (already identical) vs new.
    """
    try:
        conn = _pg_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, enriched_text_hash, lightrag_ingested, ingested_at FROM rag2_chunks WHERE source = %s",
                (src,)
            )
            existing = {r['id']: dict(r) for r in cur.fetchall()}
        conn.close()
        return {
            "source": src,
            "existing_chunks": len(existing),
            "note": "POST to /ingest with same payload to check dedup in action; "
                    "chunks with matching enriched_text_hash will be skipped automatically."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest):
    """
    Ingest semchunk output into LightRAG.

    Per-chunk pipeline:
      1. Generate situating context + metadata via Sarvam AI (max 5 concurrent)
      2. Build enriched text: [Situating Context] + [Section Path] + [Content]
      3. Compute md5 of enriched text — skip if identical to last ingest (dedup)
      4. rag.ainsert(enriched_text) — LightRAG extracts entities, embeds, stores
      5. Embed enriched text via SBERT for hybrid search in rag2_chunks
      6. Write audit record to rag2_chunks + rag2_ingest_log
    """
    if rag is None:
        raise HTTPException(status_code=503, detail="LightRAG not initialised")

    run_id     = str(uuid.uuid4())
    t_start    = time.time()
    doc_title  = req.documentTitle or req.source
    doc_summary = req.documentSummary or ""

    valid_chunks = [c for c in req.chunks if c.content.strip()]
    chunks_total = len(req.chunks)

    logger.info(
        f"[{run_id}] Ingest start: source='{req.source}' "
        f"chunks={len(valid_chunks)}/{chunks_total} ctx={'ON' if CONTEXTUAL_RETRIEVAL else 'OFF'}"
    )

    # Fetch existing hashes for dedup
    existing_hashes: Dict[str, str] = {}
    try:
        conn = _pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, enriched_text_hash FROM rag2_chunks WHERE source = %s AND lightrag_ingested = true",
                (req.source,)
            )
            existing_hashes = {r[0]: r[1] for r in cur.fetchall()}
        conn.close()
    except Exception as e:
        logger.warning(f"Dedup hash fetch failed (continuing without dedup): {e}")

    # Build enriched texts + metadata in parallel (semaphore limits Sarvam concurrency)
    enriched_results: List[Tuple[str, str, bool, ChunkMetadata]] = await asyncio.gather(*[
        _build_enriched_text(chunk, doc_title, doc_summary)
        for chunk in valid_chunks
    ])

    # Insert into LightRAG (sequential — not concurrency-safe internally)
    chunk_results: List[Tuple[Chunk, str, str, bool, bool, Optional[str], ChunkMetadata]] = []
    ingested = skipped = failed = 0

    for chunk, (enriched_text, context_text, context_generated, metadata) in zip(valid_chunks, enriched_results):
        text_hash = hashlib.md5(enriched_text.encode()).hexdigest()

        # Dedup: skip if this exact enriched text was already ingested
        if chunk.id in existing_hashes and existing_hashes[chunk.id] == text_hash:
            logger.debug(f"Skip {chunk.id} — identical hash (already ingested)")
            skipped += 1
            continue

        try:
            await rag.ainsert(enriched_text)
            # Embed enriched text for hybrid search (store on chunk metadata for _write_audit)
            try:
                emb = await sbert_embed([enriched_text])
                if not chunk.metadata:
                    chunk.metadata = {}
                chunk.metadata['_embedding'] = emb[0] if emb else None
            except Exception as emb_err:
                logger.warning(f"Embedding failed for {chunk.id}: {emb_err}")
            chunk_results.append((chunk, enriched_text, context_text, context_generated, True, None, metadata))
            ingested += 1
        except Exception as e:
            err = str(e)
            logger.error(f"Failed to ingest chunk {chunk.id}: {err}")
            chunk_results.append((chunk, enriched_text, context_text, context_generated, False, err, metadata))
            failed += 1

    duration_ms = int((time.time() - t_start) * 1000)
    logger.info(
        f"[{run_id}] Ingest done: ingested={ingested} skipped={skipped} "
        f"failed={failed} duration={duration_ms}ms"
    )

    # Write audit sidecar (non-blocking on failure)
    _write_audit(run_id, req.source, doc_title, chunks_total, chunk_results, duration_ms)

    return IngestResponse(
        success=True,
        ingested=ingested,
        skipped=skipped,
        failed=failed,
        source=req.source,
        run_id=run_id,
        contextualRetrieval=CONTEXTUAL_RETRIEVAL,
        duration_ms=duration_ms,
    )


# ─────────────────────────────────────────────────────────────
# Hybrid Query — BM25 + Vector + RRF Fusion
# ─────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str
    mode: str = "hybrid"              # "hybrid" | "bm25" | "vector"
    top_k: int = 10
    # Metadata filters
    doc_type: Optional[str] = None
    doc_date_from: Optional[str] = None
    doc_date_to: Optional[str] = None
    parties: Optional[List[str]] = None
    statutory_refs: Optional[List[str]] = None
    source: Optional[str] = None


class QueryResult(BaseModel):
    id: str
    source: str
    document_title: Optional[str]
    content: str
    section_path: Optional[str]
    page_start: int
    page_end: int
    doc_type: Optional[str]
    doc_date: Optional[str]
    parties: Optional[List[str]]
    statutory_refs: Optional[List[str]]
    score: float
    bm25_rank: Optional[int] = None
    vector_rank: Optional[int] = None


class QueryResponse(BaseModel):
    results: List[QueryResult]
    total: int
    mode: str
    duration_ms: int


def _build_metadata_where(params: QueryRequest) -> Tuple[str, list]:
    """Build WHERE clause fragments for metadata filters. Returns (sql_fragments, params)."""
    conditions = []
    values = []
    if params.source:
        conditions.append("source = %s")
        values.append(params.source)
    if params.doc_type:
        conditions.append("doc_type = %s")
        values.append(params.doc_type)
    if params.doc_date_from:
        conditions.append("doc_date >= %s")
        values.append(params.doc_date_from)
    if params.doc_date_to:
        conditions.append("doc_date <= %s")
        values.append(params.doc_date_to)
    if params.parties:
        conditions.append("parties && %s")  # array overlap
        values.append(params.parties)
    if params.statutory_refs:
        conditions.append("statutory_refs && %s")
        values.append(params.statutory_refs)
    where_sql = " AND " + " AND ".join(conditions) if conditions else ""
    return where_sql, values


@app.post("/query", response_model=QueryResponse)
async def query_chunks(req: QueryRequest):
    """
    Hybrid BM25 + vector search with metadata pre-filtering and RRF fusion.

    Modes:
      - hybrid: RRF fusion of BM25 + vector results (default)
      - bm25: full-text search only
      - vector: semantic similarity only
    """
    t_start = time.time()

    if req.mode not in ("hybrid", "bm25", "vector"):
        raise HTTPException(status_code=400, detail=f"Invalid mode '{req.mode}': must be hybrid, bm25, or vector")

    # Embed query for vector search
    query_embedding = None
    if req.mode in ("hybrid", "vector"):
        try:
            emb = await sbert_embed([req.query])
            query_embedding = emb[0] if emb else None
        except Exception as e:
            logger.warning(f"Query embedding failed: {e}")
            if req.mode == "vector":
                raise HTTPException(status_code=503, detail=f"Embedding service unavailable: {e}")
            # Fall back to BM25-only for hybrid mode
            req.mode = "bm25"

    meta_where, meta_params = _build_metadata_where(req)
    fetch_limit = req.top_k * 2  # fetch wider candidate set for RRF fusion

    try:
        conn = _pg_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            bm25_rows = []
            vector_rows = []

            # ── BM25 branch ──────────────────────────────────────
            if req.mode in ("hybrid", "bm25"):
                bm25_sql = f"""
                    SELECT id, source, document_title, content, section_path,
                           page_start, page_end, doc_type, doc_date,
                           parties, statutory_refs,
                           ts_rank(content_tsv, plainto_tsquery('english', %s)) AS bm25_score
                    FROM rag2_chunks
                    WHERE content_tsv @@ plainto_tsquery('english', %s)
                      AND lightrag_ingested = true
                      {meta_where}
                    ORDER BY bm25_score DESC
                    LIMIT %s
                """
                bm25_params = [req.query, req.query] + meta_params + [fetch_limit]
                cur.execute(bm25_sql, bm25_params)
                bm25_rows = [dict(r) for r in cur.fetchall()]

            # ── Vector branch ───────────────────────────────────
            if req.mode in ("hybrid", "vector") and query_embedding:
                # Format embedding as vector string for pgvector
                emb_str = "[" + ",".join(str(v) for v in query_embedding) + "]"
                vector_sql = f"""
                    SELECT id, source, document_title, content, section_path,
                           page_start, page_end, doc_type, doc_date,
                           parties, statutory_refs,
                           1 - (embedding <=> %s::vector) AS cosine_score
                    FROM rag2_chunks
                    WHERE embedding IS NOT NULL
                      AND lightrag_ingested = true
                      {meta_where}
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """
                vector_params = [emb_str, emb_str] + meta_params + [fetch_limit]
                cur.execute(vector_sql, vector_params)
                vector_rows = [dict(r) for r in cur.fetchall()]

        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")

    # ── RRF Fusion ─────────────────────────────────────────────
    results: Dict[str, QueryResult] = {}

    if req.mode == "bm25":
        # BM25-only mode: rank directly
        for rank, row in enumerate(bm25_rows, 1):
            results[row['id']] = QueryResult(
                id=row['id'],
                source=row['source'],
                document_title=row.get('document_title'),
                content=row['content'],
                section_path=row.get('section_path'),
                page_start=row.get('page_start', 0),
                page_end=row.get('page_end', 0),
                doc_type=row.get('doc_type'),
                doc_date=str(row['doc_date']) if row.get('doc_date') else None,
                parties=row.get('parties'),
                statutory_refs=row.get('statutory_refs'),
                score=row['bm25_score'],
                bm25_rank=rank,
            )
    elif req.mode == "vector":
        # Vector-only mode: rank directly
        for rank, row in enumerate(vector_rows, 1):
            results[row['id']] = QueryResult(
                id=row['id'],
                source=row['source'],
                document_title=row.get('document_title'),
                content=row['content'],
                section_path=row.get('section_path'),
                page_start=row.get('page_start', 0),
                page_end=row.get('page_end', 0),
                doc_type=row.get('doc_type'),
                doc_date=str(row['doc_date']) if row.get('doc_date') else None,
                parties=row.get('parties'),
                statutory_refs=row.get('statutory_refs'),
                score=row['cosine_score'],
                vector_rank=rank,
            )
    else:
        # Hybrid mode: RRF fusion
        K = 60  # RRF constant
        bm25_ranks = {row['id']: rank for rank, row in enumerate(bm25_rows, 1)}
        vector_ranks = {row['id']: rank for rank, row in enumerate(vector_rows, 1)}
        all_ids = set(bm25_ranks.keys()) | set(vector_ranks.keys())

        # Gather row data from whichever branch has it
        row_data = {}
        for row in bm25_rows:
            row_data[row['id']] = row
        for row in vector_rows:
            row_data[row['id']] = row

        for cid in all_ids:
            b_rank = bm25_ranks.get(cid)
            v_rank = vector_ranks.get(cid)
            # RRF score: 60% BM25 + 40% dense
            score = 0.0
            if b_rank is not None:
                score += 0.6 / (K + b_rank)
            if v_rank is not None:
                score += 0.4 / (K + v_rank)

            row = row_data.get(cid, {})
            results[cid] = QueryResult(
                id=cid,
                source=row.get('source', ''),
                document_title=row.get('document_title'),
                content=row.get('content', ''),
                section_path=row.get('section_path'),
                page_start=row.get('page_start', 0),
                page_end=row.get('page_end', 0),
                doc_type=row.get('doc_type'),
                doc_date=str(row.get('doc_date')) if row.get('doc_date') else None,
                parties=row.get('parties'),
                statutory_refs=row.get('statutory_refs'),
                score=round(score, 6),
                bm25_rank=b_rank,
                vector_rank=v_rank,
            )

    # Sort by score descending, take top_k
    sorted_results = sorted(results.values(), key=lambda r: r.score, reverse=True)[:req.top_k]

    duration_ms = int((time.time() - t_start) * 1000)
    return QueryResponse(
        results=sorted_results,
        total=len(sorted_results),
        mode=req.mode,
        duration_ms=duration_ms,
    )
# POST /compliance/check
#
# Accepts semchunk output for a resolution plan and evaluates it
# against 20 mandatory requirements under IBC 2016 and IBBI CIRP
# Regulations 2016. Returns a structured JSON compliance report.
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# Standard IBC requirement embeddings — computed once at startup
# Used by /matter/plan/verify for node-to-node structural matching
# ─────────────────────────────────────────────────────────────
_standard_embeddings: Dict[str, List[float]] = {}


async def _embed_standard_requirements():
    global _standard_embeddings
    texts, ids = [], []
    for req in IBC_REQUIREMENTS:
        aliases = " ".join(req.get("aliases", []))
        text = f"{req['requirement']} {req['description']} {aliases}".strip()
        texts.append(text)
        ids.append(req["id"])
    try:
        vecs = await sbert_embed(texts)
        for req_id, vec in zip(ids, vecs):
            _standard_embeddings[req_id] = vec
        logger.info(f"Embedded {len(_standard_embeddings)} standard IBC requirements for node matching")
    except Exception as e:
        logger.warning(f"Failed to embed standard requirements (matching disabled): {e}")


def _heading_score(plan_heading: Optional[str], aliases: List[str]) -> float:
    """Token overlap between plan section heading and standard node aliases."""
    if not plan_heading or not aliases:
        return 0.0
    h = set(plan_heading.lower().split())
    best = 0.0
    for alias in aliases:
        a = set(alias.lower().split())
        if a:
            best = max(best, len(h & a) / len(a))
    return best


def _keyword_status(content: str, required: List[str], disqualifying: List[str]) -> str:
    """
    Returns 'strong', 'weak', or 'disqualified' based on keyword presence.
    strong   = all required signals present
    weak     = at least one required signal present
    disqualified = a disqualifying signal overrides
    none     = no signals found
    """
    c = content.lower()
    if any(d.lower() in c for d in disqualifying):
        return "disqualified"
    hits = sum(1 for r in required if r.lower() in c)
    if hits == len(required):
        return "strong"
    if hits > 0:
        return "weak"
    return "none"


def _derive_status(combined_score: float, keyword: str) -> str:
    if keyword == "disqualified":
        return "non_compliant"
    if combined_score >= 0.72 and keyword == "strong":
        return "compliant"
    if combined_score >= 0.55 and keyword in ("strong", "weak"):
        return "partial"
    if combined_score >= 0.40:
        return "partial"
    return "not_found"


IBC_REQUIREMENTS = [
    # ── Category A: Priority Payments & Costs ──────────────────
    {
        "id": "A1", "category": "Priority Payments",
        "requirement": "CIRP/IRP Cost Priority Payment",
        "description": (
            "The resolution plan explicitly provides for payment of insolvency resolution "
            "process costs (CIRP costs, IRP fees, RP fees, valuer fees) in priority to all "
            "other debt repayments."
        ),
        "section": "Sec 30(2)(a) IBC 2016; Reg 38(1)(a)(i) IBBI CIRP Regs 2016",
        "aliases": ["cirp cost", "irp cost", "insolvency resolution process cost",
                    "resolution professional fee", "process cost waterfall",
                    "priority payment", "cost of cirp", "cirp expenses"],
        "required_signals": ["priority", "first charge", "before distribution", "cirp cost"],
        "disqualifying_signals": ["subject to availability", "at discretion of coc"],
    },
    {
        "id": "A2", "category": "Priority Payments",
        "requirement": "Identified Funding Sources for CIRP Costs",
        "description": "Specific sources of funds to pay CIRP/IRP costs are identified.",
        "section": "Reg 38(1)(a) IBBI CIRP Regs 2016",
        "aliases": ["funding source", "source of funds", "cirp cost funding", "payment source"],
        "required_signals": ["source", "fund", "upfront", "cash"],
        "disqualifying_signals": [],
    },
    # ── Category B: Operational Creditor Treatment ─────────────
    {
        "id": "B1", "category": "Operational Creditors",
        "requirement": "OC Minimum Liquidation Value Payment",
        "description": (
            "Operational creditors receive at least the liquidation value under Section 53 IBC."
        ),
        "section": "Sec 30(2)(b) IBC 2016",
        "aliases": ["operational creditor", "oc payment", "operational creditors payment",
                    "payment to vendors", "trade creditor", "unpaid dues operational"],
        "required_signals": ["operational creditor", "liquidation value"],
        "disqualifying_signals": ["nil", "zero", "no payment to operational"],
    },
    {
        "id": "B2", "category": "Operational Creditors",
        "requirement": "OC Payment Timeline Specified",
        "description": "A specific timeline or payment schedule for operational creditors.",
        "section": "Sec 30(2)(b) IBC 2016; Reg 38(1)(a)(ii) IBBI CIRP Regs",
        "aliases": ["operational creditor schedule", "oc timeline", "payment schedule operational"],
        "required_signals": ["operational creditor"],
        "disqualifying_signals": [],
    },
    {
        "id": "B3", "category": "Operational Creditors",
        "requirement": "Employee, Workmen & Statutory Labour Dues",
        "description": "Employee wages, workmen dues, provident fund, gratuity addressed.",
        "section": "Sec 30(2)(b), Sec 53(1)(b) IBC 2016",
        "aliases": ["employee dues", "workmen dues", "provident fund", "gratuity",
                    "salary arrears", "statutory labour", "pf dues", "esic"],
        "required_signals": ["employee", "workmen", "provident fund"],
        "disqualifying_signals": [],
    },
    # ── Category C: Financial Creditor Treatment ───────────────
    {
        "id": "C1", "category": "Financial Creditors",
        "requirement": "Total Resolution Consideration Stated",
        "description": "Total consideration / upfront payment amount clearly stated with figure.",
        "section": "Sec 30(2) IBC 2016",
        "aliases": ["total consideration", "upfront payment", "resolution amount",
                    "plan consideration", "total offer", "purchase consideration"],
        "required_signals": ["crore", "consideration", "upfront"],
        "disqualifying_signals": [],
    },
    {
        "id": "C2", "category": "Financial Creditors",
        "requirement": "Financial Creditor Distribution Plan",
        "description": "Specific distribution plan among financial creditors (pro-rata or class-wise).",
        "section": "Sec 30(2) IBC 2016",
        "aliases": ["financial creditor distribution", "distribution to lenders",
                    "payment to banks", "fc distribution", "lender payment",
                    "distribution among financial creditors"],
        "required_signals": ["financial creditor", "distribution"],
        "disqualifying_signals": [],
    },
    {
        "id": "C3", "category": "Financial Creditors",
        "requirement": "Dissenting Financial Creditor Protection",
        "description": "Dissenting financial creditors receive at least liquidation value under Sec 53.",
        "section": "Sec 30(2)(b)(ii) IBC 2016; Reg 38(1)(a)(iii) IBBI CIRP Regs",
        "aliases": ["dissenting creditor", "dissenting financial creditor",
                    "minority creditor", "non-consenting creditor"],
        "required_signals": ["dissenting", "liquidation value"],
        "disqualifying_signals": [],
    },
    {
        "id": "C4", "category": "Financial Creditors",
        "requirement": "FC Payment Schedule / Tranches",
        "description": "Payment schedule with dates or milestones for financial creditor payments.",
        "section": "Sec 30(2) IBC 2016",
        "aliases": ["payment schedule", "payment tranche", "deferred payment",
                    "payment timeline", "ncd", "payment milestone", "closing payment"],
        "required_signals": ["payment", "schedule"],
        "disqualifying_signals": [],
    },
    # ── Category D: Default Cause & Business Viability ─────────
    {
        "id": "D1", "category": "Default & Viability",
        "requirement": "Cause of Default Addressed",
        "description": "Plan addresses root cause of default of the corporate debtor.",
        "section": "Reg 38(1)(b) IBBI CIRP Regs 2016",
        "aliases": ["cause of default", "reason for default", "root cause",
                    "why default", "default background", "background default"],
        "required_signals": ["default", "cause"],
        "disqualifying_signals": [],
    },
    {
        "id": "D2", "category": "Default & Viability",
        "requirement": "Viable & Adequate Implementation Means",
        "description": "Plan demonstrates viable means of implementation with committed funding.",
        "section": "Reg 38(1)(c) IBBI CIRP Regs 2016",
        "aliases": ["implementation means", "funding commitment", "financial capacity",
                    "ability to implement", "committed funding", "implementation feasibility"],
        "required_signals": ["implement", "fund", "viab"],
        "disqualifying_signals": [],
    },
    {
        "id": "D3", "category": "Default & Viability",
        "requirement": "Financial Projections / Business Plan",
        "description": "Financial projections or business plan supporting viability included.",
        "section": "Reg 38(1)(c) IBBI CIRP Regs 2016",
        "aliases": ["financial projection", "business plan", "projected financials",
                    "revenue projection", "ebitda projection", "five year plan",
                    "projected balance sheet", "financial forecast"],
        "required_signals": ["projection", "forecast", "plan"],
        "disqualifying_signals": [],
    },
    {
        "id": "D4", "category": "Default & Viability",
        "requirement": "Going Concern Continuity",
        "description": "Plan provides for corporate debtor to continue as a going concern.",
        "section": "Sec 30(2)(c) IBC 2016",
        "aliases": ["going concern", "business continuity", "continued operation",
                    "ongoing business", "continuation of business"],
        "required_signals": ["going concern", "continu"],
        "disqualifying_signals": ["liquidation", "wind up", "close down"],
    },
    # ── Category E: Corporate Governance & Implementation ──────
    {
        "id": "E1", "category": "Governance & Implementation",
        "requirement": "Post-Approval Management Structure",
        "description": "Plan specifies management of corporate debtor after NCLT approval.",
        "section": "Sec 30(2)(c) IBC 2016; Reg 38(1)(d)(iii)",
        "aliases": ["management structure", "board of directors", "post approval management",
                    "management control", "key management", "corporate governance"],
        "required_signals": ["board", "management", "director"],
        "disqualifying_signals": [],
    },
    {
        "id": "E2", "category": "Governance & Implementation",
        "requirement": "Shareholding / Equity Structure Post-Implementation",
        "description": "New shareholding pattern or equity structure post-implementation specified.",
        "section": "Sec 30(2)(c) IBC 2016",
        "aliases": ["shareholding", "equity structure", "share allotment",
                    "ownership structure", "promoter stake", "equity allotment"],
        "required_signals": ["share", "equity", "allot"],
        "disqualifying_signals": [],
    },
    {
        "id": "E3", "category": "Governance & Implementation",
        "requirement": "Implementation Timeline & Milestones",
        "description": "Implementation timeline with milestones — closing, payments, transfers.",
        "section": "Reg 38(1)(d)(ii) IBBI CIRP Regs 2016",
        "aliases": ["implementation timeline", "milestone", "closing date",
                    "implementation schedule", "time schedule", "implementation plan"],
        "required_signals": ["timeline", "milestone", "date"],
        "disqualifying_signals": [],
    },
    {
        "id": "E4", "category": "Governance & Implementation",
        "requirement": "Monitoring Committee / Supervision Mechanism",
        "description": "Monitoring committee or supervision mechanism for plan implementation.",
        "section": "Reg 38(1)(d)(iv) IBBI CIRP Regs 2016",
        "aliases": ["monitoring committee", "implementation committee", "supervision",
                    "monitoring mechanism", "oversight committee", "implementation monitoring"],
        "required_signals": ["monitor", "committee", "supervis"],
        "disqualifying_signals": [],
    },
    # ── Category F: Regulatory & Legal Compliance ──────────────
    {
        "id": "F1", "category": "Regulatory Compliance",
        "requirement": "Statutory & Regulatory Approvals Identified",
        "description": "Required regulatory approvals (CCI, RBI, SEBI, NCLT) identified with timelines.",
        "section": "Reg 38(1)(d)(ii) IBBI CIRP Regs 2016",
        "aliases": ["regulatory approval", "statutory approval", "cci approval",
                    "rbi approval", "sebi approval", "competition commission",
                    "regulatory clearance", "government approval"],
        "required_signals": ["approval", "regulatory"],
        "disqualifying_signals": [],
    },
    {
        "id": "F2", "category": "Regulatory Compliance",
        "requirement": "Non-Contravention Declaration",
        "description": "Declaration that plan does not contravene any law in force.",
        "section": "Sec 30(2)(e) IBC 2016",
        "aliases": ["non contravention", "legal compliance declaration",
                    "does not contravene", "compliance with law",
                    "not in violation", "legal declaration"],
        "required_signals": ["contravene", "law", "compliance"],
        "disqualifying_signals": [],
    },
    {
        "id": "F3", "category": "Regulatory Compliance",
        "requirement": "Section 29A Eligibility Compliance",
        "description": (
            "Resolution applicant declares compliance with Section 29A: not a wilful "
            "defaulter, NPA promoter not >1 year, no conviction, not related party of ineligible."
        ),
        "section": "Sec 29A IBC 2016",
        "aliases": ["section 29a", "29a compliance", "29a eligibility",
                    "wilful defaulter declaration", "eligibility declaration",
                    "resolution applicant eligibility"],
        "required_signals": ["29a", "eligible", "wilful defaulter"],
        "disqualifying_signals": [],
    },
]

_COMPLIANCE_SYSTEM_PROMPT = (
    "You are an expert in Indian insolvency law with deep knowledge of the Insolvency and "
    "Bankruptcy Code 2016 (IBC), IBBI (Insolvency Resolution Process for Corporate Persons) "
    "Regulations 2016, and related NCLT/NCLAT/Supreme Court jurisprudence.\n\n"
    "Your task: analyze the provided resolution plan excerpts and evaluate compliance with "
    "each mandatory requirement. Be precise and evidence-based. Only mark 'compliant' if "
    "clear textual evidence is present. Mark 'partial' if the requirement is addressed but "
    "incompletely. Mark 'not_found' if there is no relevant text at all.\n\n"
    "Return ONLY a valid JSON object — no explanation, no markdown, no preamble."
)


def _build_compliance_prompt(doc_title: str, content: str) -> str:
    reqs_json = json.dumps(
        [{"id": r["id"], "category": r["category"],
          "requirement": r["requirement"], "description": r["description"],
          "section": r["section"]} for r in IBC_REQUIREMENTS],
        indent=2
    )
    return (
        f"Document: {doc_title}\n\n"
        f"Mandatory IBC Compliance Requirements to evaluate:\n{reqs_json}\n\n"
        f"Resolution Plan Excerpts:\n\"\"\"\n{content}\n\"\"\"\n\n"
        "For EACH requirement above return one JSON object in the 'results' array:\n"
        "  - id: the requirement ID (e.g. 'A1')\n"
        "  - status: exactly one of: 'compliant', 'partial', 'non_compliant', 'not_found'\n"
        "  - evidence: verbatim quote or close paraphrase from the document (null if not found)\n"
        "  - notes: brief legal observation or gap identified (null if none)\n\n"
        'Return: {"results": [{"id":"...","status":"...","evidence":"...","notes":"..."}, ...]}'
    )


def _parse_compliance_json(raw: str) -> Optional[List[Dict]]:
    """Robustly extract the results array from LLM output."""
    import re
    # Try direct parse
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "results" in parsed:
            return parsed["results"]
    except Exception:
        pass
    # Try extracting JSON block
    match = re.search(r'\{[\s\S]*"results"[\s\S]*\}', raw)
    if match:
        try:
            parsed = json.loads(match.group())
            if "results" in parsed:
                return parsed["results"]
        except Exception:
            pass
    return None


class ComplianceCheckRequest(BaseModel):
    source: str
    chunks: List[Chunk]
    documentTitle: Optional[str] = None
    documentSummary: Optional[str] = None


class ComplianceResultItem(BaseModel):
    id: str
    category: str
    requirement: str
    section: str
    status: str          # compliant | partial | non_compliant | not_found
    evidence: Optional[str] = None
    notes: Optional[str] = None


class ComplianceCheckResponse(BaseModel):
    source: str
    document_title: str
    checked_at: str
    chunks_analyzed: int
    chars_analyzed: int
    overall_status: str  # compliant | partial | non_compliant
    compliant: int
    partial: int
    non_compliant: int
    not_found: int
    results: List[ComplianceResultItem]
    duration_ms: int


@app.post("/compliance/check", response_model=ComplianceCheckResponse)
async def compliance_check(req: ComplianceCheckRequest):
    """
    Evaluate a resolution plan (provided as semchunk output) against the 20 mandatory
    requirements of IBC 2016 and IBBI CIRP Regulations 2016.

    Sends chunk content to Sarvam AI in a single structured prompt and returns a
    per-requirement compliance matrix with evidence quotes.
    """
    t_start   = time.time()
    doc_title = req.documentTitle or req.source

    # Concatenate chunk content — up to 25000 chars to stay within context window
    valid_chunks = [c for c in req.chunks if c.content.strip()]
    content_parts = []
    total_chars = 0
    CHAR_LIMIT = 25000
    for chunk in valid_chunks:
        part = ""
        if chunk.parentContext:
            part += f"[{chunk.parentContext.strip()}]\n"
        part += chunk.content.strip()
        if total_chars + len(part) > CHAR_LIMIT:
            remaining = CHAR_LIMIT - total_chars
            if remaining > 200:
                content_parts.append(part[:remaining] + "…[truncated]")
            break
        content_parts.append(part)
        total_chars += len(part)

    content = "\n\n---\n\n".join(content_parts)
    prompt  = _build_compliance_prompt(doc_title, content)

    logger.info(
        f"Compliance check: source='{req.source}' chunks={len(valid_chunks)} "
        f"chars={total_chars}"
    )

    # Single LLM call — all 20 requirements evaluated together
    raw_response = ""
    try:
        raw_response = await sarvam_llm(
            prompt,
            system_prompt=_COMPLIANCE_SYSTEM_PROMPT,
            max_tokens=3000,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")

    results_raw = _parse_compliance_json(raw_response or "")
    if not results_raw:
        logger.error(f"Failed to parse compliance JSON. Raw: {raw_response[:500]}")
        raise HTTPException(
            status_code=502,
            detail="LLM returned unparseable response. Try again."
        )

    # Build result map from LLM output; fill any missing requirements as not_found
    llm_map = {r.get("id"): r for r in results_raw if isinstance(r, dict) and r.get("id")}
    results: List[ComplianceResultItem] = []
    counts = {"compliant": 0, "partial": 0, "non_compliant": 0, "not_found": 0}

    for req_def in IBC_REQUIREMENTS:
        rid    = req_def["id"]
        llm_r  = llm_map.get(rid, {})
        status = llm_r.get("status", "not_found")
        if status not in counts:
            status = "not_found"
        counts[status] += 1
        results.append(ComplianceResultItem(
            id=rid,
            category=req_def["category"],
            requirement=req_def["requirement"],
            section=req_def["section"],
            status=status,
            evidence=llm_r.get("evidence") or None,
            notes=llm_r.get("notes") or None,
        ))

    # Overall status
    if counts["non_compliant"] > 0 or counts["not_found"] > 3:
        overall = "non_compliant"
    elif counts["partial"] > 0 or counts["not_found"] > 0:
        overall = "partial"
    else:
        overall = "compliant"

    duration_ms = int((time.time() - t_start) * 1000)
    logger.info(
        f"Compliance check done: compliant={counts['compliant']} "
        f"partial={counts['partial']} non_compliant={counts['non_compliant']} "
        f"not_found={counts['not_found']} duration={duration_ms}ms"
    )

    return ComplianceCheckResponse(
        source=req.source,
        document_title=doc_title,
        checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        chunks_analyzed=len(valid_chunks),
        chars_analyzed=total_chars,
        overall_status=overall,
        compliant=counts["compliant"],
        partial=counts["partial"],
        non_compliant=counts["non_compliant"],
        not_found=counts["not_found"],
        results=results,
        duration_ms=duration_ms,
    )


# ═════════════════════════════════════════════════════════════════════════════
# MATTER — Structural node-matching compliance verification
#
# Flow:
#   POST /matter/setup          → create matter + register plan
#   POST /matter/plan/index     → embed plan nodes → matter.ibc_plan_nodes
#   POST /matter/plan/verify    → vector match → matter.ibc_compliance + score
#   GET  /matter/plan/{id}      → compliance results for one plan
#   GET  /matter/compare        → plan_comparison view across a matter
#   POST /matter/compliance/human → record human verification / override
# ═════════════════════════════════════════════════════════════════════════════

import numpy as np


class MatterSetupRequest(BaseModel):
    company: str
    cin: Optional[str] = None
    nclt_bench: Optional[str] = None
    case_number: Optional[str] = None
    cirp_start: Optional[str] = None
    rp_name: Optional[str] = None
    # Plan fields
    source: str
    applicant: Optional[str] = None
    applicant_type: Optional[str] = None
    consideration_crore: Optional[float] = None
    upfront_crore: Optional[float] = None
    plan_date: Optional[str] = None


class PlanIndexRequest(BaseModel):
    plan_id: str
    chunks: List[Chunk]


class HumanVerifyRequest(BaseModel):
    plan_id: str
    req_id: str
    status: str           # human-confirmed status
    notes: Optional[str] = None
    verified_by: Optional[str] = "lawyer"


def _cosine(a: List[float], b: List[float]) -> float:
    va, vb = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    return float(np.dot(va, vb) / denom) if denom > 0 else 0.0


@app.post("/matter/setup")
async def matter_setup(req: MatterSetupRequest):
    """Create (or retrieve) a matter and register a resolution plan."""
    matter_id = hashlib.md5(req.company.lower().encode()).hexdigest()[:16]
    plan_id   = hashlib.md5(req.source.encode()).hexdigest()[:16]
    try:
        conn = _pg_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO matter.matters (id, company, cin, nclt_bench, case_number, cirp_start, rp_name)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET
                        nclt_bench=COALESCE(EXCLUDED.nclt_bench, matter.matters.nclt_bench),
                        case_number=COALESCE(EXCLUDED.case_number, matter.matters.case_number),
                        rp_name=COALESCE(EXCLUDED.rp_name, matter.matters.rp_name)
                """, (matter_id, req.company, req.cin, req.nclt_bench,
                      req.case_number, req.cirp_start, req.rp_name))
                cur.execute("""
                    INSERT INTO matter.ibc_plans
                        (id, matter_id, source, applicant, applicant_type,
                         consideration_crore, upfront_crore, plan_date)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET
                        applicant=COALESCE(EXCLUDED.applicant, matter.ibc_plans.applicant),
                        consideration_crore=COALESCE(EXCLUDED.consideration_crore, matter.ibc_plans.consideration_crore),
                        upfront_crore=COALESCE(EXCLUDED.upfront_crore, matter.ibc_plans.upfront_crore)
                """, (plan_id, matter_id, req.source, req.applicant, req.applicant_type,
                      req.consideration_crore, req.upfront_crore, req.plan_date))
        conn.close()
        return {"matter_id": matter_id, "plan_id": plan_id, "status": "registered"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/matter/plan/index")
async def matter_plan_index(req: PlanIndexRequest):
    """
    Embed each plan section (chunk) via InLegal-SBERT and store in
    matter.ibc_plan_nodes with the vector(768) embedding.
    """
    valid = [c for c in req.chunks if c.content.strip()]
    if not valid:
        raise HTTPException(status_code=400, detail="No non-empty chunks provided")

    # Embed all nodes in one SBERT call
    texts = []
    for c in valid:
        heading = (c.parentContext or "").split("\n")[-1].strip() if c.parentContext else ""
        texts.append(f"{heading} {c.content[:600]}".strip())

    vecs = await sbert_embed(texts)

    rows = []
    now  = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for i, (chunk, vec) in enumerate(zip(valid, vecs)):
        node_id  = hashlib.md5(f"{req.plan_id}:{i}:{chunk.content[:80]}".encode()).hexdigest()
        heading  = (chunk.parentContext or "").split("\n")[-1].strip() if chunk.parentContext else ""
        vec_str  = "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
        rows.append((node_id, req.plan_id, i, heading, chunk.parentContext,
                     chunk.content, chunk.pageStart, chunk.pageEnd,
                     chunk.tokenCount, vec_str, now))

    try:
        conn = _pg_conn()
        with conn:
            with conn.cursor() as cur:
                # Clear old nodes for this plan before re-indexing
                cur.execute("DELETE FROM matter.ibc_plan_nodes WHERE plan_id = %s", (req.plan_id,))
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO matter.ibc_plan_nodes
                        (id, plan_id, node_index, heading, section_path, content,
                         page_start, page_end, token_count, embedding, embedded_at)
                    VALUES %s
                """, rows, template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s)")
                cur.execute(
                    "UPDATE matter.ibc_plans SET status='indexed' WHERE id=%s",
                    (req.plan_id,)
                )
        conn.close()
        logger.info(f"Indexed {len(rows)} nodes for plan {req.plan_id}")
        return {"plan_id": req.plan_id, "nodes_indexed": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/matter/plan/verify")
async def matter_plan_verify(plan_id: str):
    """
    For each of the 20 IBC standard requirements:
      1. Query pgvector for the top-3 most similar plan nodes
      2. Apply heading alias bonus (structural match)
      3. Apply keyword signal rules (content check)
      4. Derive status: compliant / partial / non_compliant / not_found
      5. Upsert into matter.ibc_compliance
      6. Recalculate aggregate score
    Returns the full per-requirement compliance report.
    """
    if not _standard_embeddings:
        raise HTTPException(status_code=503, detail="Standard embeddings not ready — service still starting")

    t_start = time.time()
    results = []

    try:
        conn = _pg_conn()
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                for req in IBC_REQUIREMENTS:
                    std_vec  = _standard_embeddings.get(req["id"])
                    if std_vec is None:
                        continue
                    vec_str  = "[" + ",".join(f"{v:.6f}" for v in std_vec) + "]"

                    # pgvector ANN — top 3 candidates
                    cur.execute("""
                        SELECT id, heading, content, section_path,
                               1 - (embedding <=> %s::vector) AS sim
                        FROM matter.ibc_plan_nodes
                        WHERE plan_id = %s
                        ORDER BY embedding <=> %s::vector
                        LIMIT 3
                    """, (vec_str, plan_id, vec_str))
                    candidates = cur.fetchall()

                    best_node, best_score, best_heading = None, 0.0, None
                    for row in candidates:
                        h_bonus  = _heading_score(row["heading"], req.get("aliases", []))
                        combined = 0.70 * float(row["sim"]) + 0.30 * h_bonus
                        if combined > best_score:
                            best_score   = combined
                            best_node    = row
                            best_heading = row["heading"]

                    if best_node:
                        kw     = _keyword_status(
                            best_node["content"],
                            req.get("required_signals", []),
                            req.get("disqualifying_signals", [])
                        )
                        status   = _derive_status(best_score, kw)
                        evidence = best_node["content"][:400].strip()
                        notes    = f"Matched section: '{best_heading}' (score {best_score:.2f})"
                        node_id  = best_node["id"]
                    else:
                        status, evidence, notes, node_id = "not_found", None, None, None

                    # Upsert compliance record
                    cur.execute("""
                        INSERT INTO matter.ibc_compliance
                            (plan_id, req_id, matched_node_id, matched_heading,
                             confidence, status, evidence, notes, checked_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now())
                        ON CONFLICT (plan_id, req_id) DO UPDATE SET
                            matched_node_id = EXCLUDED.matched_node_id,
                            matched_heading = EXCLUDED.matched_heading,
                            confidence      = EXCLUDED.confidence,
                            status          = EXCLUDED.status,
                            evidence        = EXCLUDED.evidence,
                            notes           = EXCLUDED.notes,
                            human_verified  = false,
                            human_override  = null,
                            checked_at      = now()
                    """, (plan_id, req["id"], node_id, best_heading,
                          round(best_score, 4), status, evidence, notes))

                    results.append({
                        "id": req["id"], "category": req["category"],
                        "requirement": req["requirement"], "section": req["section"],
                        "status": status, "confidence": round(best_score, 3),
                        "matched_heading": best_heading, "evidence": evidence, "notes": notes,
                    })

                # Recalculate score + rank
                cur.execute("SELECT matter.recalculate_score(%s)", (plan_id,))
                cur.execute(
                    "UPDATE matter.ibc_plans SET status='verified' WHERE id=%s",
                    (plan_id,)
                )
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    counts = {s: sum(1 for r in results if r["status"] == s)
              for s in ("compliant", "partial", "non_compliant", "not_found")}
    duration_ms = int((time.time() - t_start) * 1000)
    logger.info(f"Verified plan {plan_id}: {counts} in {duration_ms}ms")

    return {
        "plan_id": plan_id,
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_ms": duration_ms,
        **counts,
        "results": results,
    }


@app.get("/matter/plan/{plan_id}")
def matter_plan_get(plan_id: str):
    """Get plan metadata + full compliance results."""
    try:
        conn = _pg_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT p.*, m.company, m.case_number, m.nclt_bench,
                       s.total_score, s.compliant, s.partial,
                       s.non_compliant, s.not_found, s.rank
                FROM matter.ibc_plans p
                JOIN matter.matters m ON m.id = p.matter_id
                LEFT JOIN matter.ibc_scores s ON s.plan_id = p.id
                WHERE p.id = %s
            """, (plan_id,))
            plan = cur.fetchone()
            if not plan:
                raise HTTPException(status_code=404, detail="Plan not found")
            cur.execute("""
                SELECT req_id, status, confidence, matched_heading,
                       evidence, notes, human_verified, human_override, checked_at
                FROM matter.ibc_compliance
                WHERE plan_id = %s ORDER BY req_id
            """, (plan_id,))
            compliance = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"plan": dict(plan), "compliance": compliance}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/matter/compare")
def matter_compare(matter_id: str):
    """Cross-plan comparison view for all plans in a matter."""
    try:
        conn = _pg_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM matter.plan_comparison WHERE company IN "
                "(SELECT company FROM matter.matters WHERE id = %s)",
                (matter_id,)
            )
            plans = [dict(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT * FROM matter.requirement_comparison WHERE matter_id = %s",
                (matter_id,)
            )
            by_req = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"matter_id": matter_id, "plans": plans, "by_requirement": by_req}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/matter/compliance/human")
def matter_human_verify(req: HumanVerifyRequest):
    """Record a human verification or override for a compliance finding."""
    try:
        conn = _pg_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE matter.ibc_compliance
                    SET human_verified = true,
                        human_override = status,
                        status         = %s,
                        notes          = COALESCE(%s, notes),
                        verified_by    = %s
                    WHERE plan_id = %s AND req_id = %s
                """, (req.status, req.notes, req.verified_by, req.plan_id, req.req_id))
                cur.execute("SELECT matter.recalculate_score(%s)", (req.plan_id,))
        conn.close()
        return {"ok": True, "plan_id": req.plan_id, "req_id": req.req_id, "status": req.status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────
# Vault endpoint — ingest from Obsidian vault
# ─────────────────────────────────────────────────────────────

VAULT_ROOT = os.environ.get("VAULT_ROOT", "/vault")


class VaultIngestRequest(BaseModel):
    slug: str


@app.post("/ingest-from-vault", response_model=IngestResponse)
async def ingest_from_vault(req: VaultIngestRequest):
    """
    Read chunk notes from Obsidian vault, reconstruct Chunk[] payloads,
    and ingest into LightRAG + Postgres.
    After ingestion, updates chunk frontmatter (lightrag_ingested: true).
    """
    import frontmatter
    from pathlib import Path

    slug = req.slug
    chunks_dir = Path(VAULT_ROOT) / "chunks" / slug

    if not chunks_dir.exists():
        raise HTTPException(status_code=404, detail=f"No chunks found for: {slug}")

    # Read all chunk notes
    chunk_files = sorted(chunks_dir.glob("chunk-*.md"))
    if not chunk_files:
        raise HTTPException(status_code=404, detail=f"No chunk files found for: {slug}")

    # Read source _index.md for document title/summary
    index_path = Path(VAULT_ROOT) / "sources" / slug / "_index.md"
    doc_title = slug
    doc_summary = ""
    if index_path.exists():
        index_post = frontmatter.load(index_path)
        doc_title = index_post.metadata.get("filename", slug)
        doc_summary = index_post.content[:200] if index_post.content else ""

    # Reconstruct Chunk[] from vault notes
    chunks = []
    for cf in chunk_files:
        post = frontmatter.load(cf)
        m = post.metadata
        chunk = Chunk(
            id=f"chunk-{m.get('chunk_index', 0) + 1:03d}",
            content=post.content,
            parentContext=m.get("parent_context"),
            pageStart=m.get("page_start", 0),
            pageEnd=m.get("page_end", 0),
            tokenCount=m.get("token_count", 0),
            metadata={
                "chunkIndex": m.get("chunk_index", 0),
                "totalChunks": m.get("total_chunks", 0),
                "hasOverlap": m.get("has_overlap", False),
            },
            docType=m.get("doc_type"),
            docDate=m.get("doc_date"),
            parties=m.get("parties"),
            statutoryRefs=m.get("statutory_refs"),
        )
        chunks.append(chunk)

    # Call the existing ingest endpoint logic
    ingest_req = IngestRequest(
        source=slug,
        chunks=chunks,
        documentTitle=doc_title,
        documentSummary=doc_summary,
    )
    result = await ingest(ingest_req)

    # Update chunk frontmatter with ingestion status
    for cf in chunk_files:
        try:
            post = frontmatter.load(cf)
            post.metadata["lightrag_ingested"] = True
            post.metadata["pipeline_stage"] = "ingested"
            post.metadata["ingested_at"] = result.run_id
            with open(cf, "w", encoding="utf-8") as f:
                frontmatter.dump(post, f)
        except Exception as e:
            logger.warning(f"Failed to update vault frontmatter for {cf}: {e}")

    # Update source _index.md pipeline stage
    if index_path.exists():
        try:
            index_post = frontmatter.load(index_path)
            index_post.metadata["pipeline_stage"] = "ingested"
            with open(index_path, "w", encoding="utf-8") as f:
                frontmatter.dump(index_post, f)
        except Exception as e:
            logger.warning(f"Failed to update source pipeline stage: {e}")

    return result
