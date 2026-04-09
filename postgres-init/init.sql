-- Run once on first container start (docker-entrypoint-initdb.d)
-- Enables Apache AGE (graph), pgvector (vector search), and full audit schema.

-- ── pgvector ──────────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS vector;

-- ── Apache AGE ────────────────────────────────────────────────────────────────
LOAD 'age';
CREATE EXTENSION IF NOT EXISTS age;
SET search_path = ag_catalog, "$user", public;
SELECT create_graph('lightrag_graph');

-- ── Ingest run log ────────────────────────────────────────────────────────────
-- One row per call to POST /ingest. Provides document-level audit trail.
CREATE TABLE IF NOT EXISTS rag2_ingest_log (
    run_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source               TEXT NOT NULL,       -- media ID or external URL
    document_title       TEXT,
    triggered_at         TIMESTAMPTZ DEFAULT now(),
    triggered_by         TEXT DEFAULT 'api',  -- 'dokuwiki', 'cli', 'api'
    chunks_total         INT  DEFAULT 0,
    chunks_ingested      INT  DEFAULT 0,
    chunks_skipped       INT  DEFAULT 0,
    chunks_failed        INT  DEFAULT 0,
    duration_ms          INT,
    contextual_retrieval BOOLEAN DEFAULT false,
    status               TEXT DEFAULT 'pending'  -- 'success' | 'partial' | 'failed'
);

CREATE INDEX IF NOT EXISTS rag2_ingest_log_source_idx ON rag2_ingest_log (source);
CREATE INDEX IF NOT EXISTS rag2_ingest_log_triggered_at_idx ON rag2_ingest_log (triggered_at DESC);

-- ── Chunk metadata + audit ────────────────────────────────────────────────────
-- One row per chunk. Populated during /ingest alongside LightRAG's own storage.
-- Serves three purposes:
--   1. BM25 full-text search (content_tsv GIN) — hybrid retrieval
--   2. Metadata pre-filtering (source, page, section) — narrow ANN search space
--   3. Audit trail — per-chunk ingestion status and enrichment record
CREATE TABLE IF NOT EXISTS rag2_chunks (
    -- Identity
    id               TEXT PRIMARY KEY,
    source           TEXT NOT NULL,
    ingest_run_id    UUID REFERENCES rag2_ingest_log(run_id),

    -- Location
    document_title   TEXT,
    page_start       INT,
    page_end         INT,
    chunk_index      INT,
    section_path     TEXT,               -- parentContext breadcrumb
    token_count      INT,

    -- Content (raw, before enrichment)
    content          TEXT NOT NULL,

    -- Domain metadata (extracted during ingest)
    doc_type         TEXT,               -- 'ibbi_order' | 'sebi_circular' | 'nclt_judgment' | 'nclat_order' | 'circular' | 'other'
    doc_date         DATE,               -- document date
    parties          TEXT[],             -- party names extracted from content
    statutory_refs   TEXT[],             -- e.g. 'Section 53 IBC 2016', 'Regulation 4(2) SEBI'

    -- Vector embedding for hybrid search (InLegal-SBERT of enriched_text)
    embedding        vector(768),

    -- BM25 index (auto-maintained, weighted: title × content)
    content_tsv      TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english',
            coalesce(document_title, '') || ' ' ||
            coalesce(section_path, '')  || ' ' ||
            content
        )
    ) STORED,

    -- Audit: what was actually sent to rag.ainsert()
    enriched_text_hash   TEXT,           -- md5 of [Situating Context] + [Section Path] + [Content]
    context_generated    BOOLEAN DEFAULT false,
    context_text         TEXT,           -- the Sarvam-generated situating blurb

    -- Audit: ingestion outcome
    lightrag_ingested    BOOLEAN DEFAULT false,
    ingested_at          TIMESTAMPTZ,
    ingest_error         TEXT,           -- error message if failed

    -- Housekeeping
    created_at           TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS rag2_chunks_tsv_idx        ON rag2_chunks USING GIN (content_tsv);
CREATE INDEX IF NOT EXISTS rag2_chunks_source_idx     ON rag2_chunks (source);
CREATE INDEX IF NOT EXISTS rag2_chunks_run_idx        ON rag2_chunks (ingest_run_id);
CREATE INDEX IF NOT EXISTS rag2_chunks_ingested_idx   ON rag2_chunks (lightrag_ingested, ingested_at);
CREATE INDEX IF NOT EXISTS rag2_chunks_page_idx       ON rag2_chunks (source, page_start, page_end);
CREATE INDEX IF NOT EXISTS rag2_chunks_doc_type_idx   ON rag2_chunks (doc_type);
CREATE INDEX IF NOT EXISTS rag2_chunks_doc_date_idx   ON rag2_chunks (doc_date);
CREATE INDEX IF NOT EXISTS rag2_chunks_embedding_hnsw_idx ON rag2_chunks USING hnsw (embedding vector_cosine_ops);

-- ── Helper: RRF score for hybrid BM25 + vector search ────────────────────────
-- Usage: SELECT rag2_rrf_score(bm25_rank, vector_rank)  → float score
-- Standard k=60. Weight: 60% BM25 (exact statutory terms), 40% dense (semantic).
CREATE OR REPLACE FUNCTION rag2_rrf_score(
    bm25_rank INT, vector_rank INT, k INT DEFAULT 60
) RETURNS FLOAT AS $$
    SELECT (0.6 / (k + bm25_rank)) + (0.4 / (k + vector_rank));
$$ LANGUAGE SQL IMMUTABLE;

-- ════════════════════════════════════════════════════════════════════════════
-- MATTER SCHEMA — Internal CIRP / Resolution Plan Working Documents
--
-- Separate from the public RAG knowledge base. Stores per-matter documents:
-- resolution plans (competing applicants), financial statements, information
-- memoranda. Supports multi-plan comparison, compliance scoring, and ranking.
--
-- Storage strategy:
--   plan nodes (headings + content) → matter.ibc_plan_nodes with vector(768)
--   all vector queries use pgvector — same extension, no new service
--   compliance results → matter.ibc_compliance (one row per plan × requirement)
--   scores → matter.ibc_scores (aggregate, ranked across plans in a matter)
-- ════════════════════════════════════════════════════════════════════════════

CREATE SCHEMA IF NOT EXISTS matter;

-- ── Matter registry ───────────────────────────────────────────────────────────
-- A "matter" is one CIRP case. Multiple plans belong to one matter.
CREATE TABLE IF NOT EXISTS matter.matters (
    id           TEXT PRIMARY KEY,          -- md5(company_name + cin)
    company      TEXT NOT NULL,             -- corporate debtor name
    cin          TEXT,                      -- Corporate Identity Number
    nclt_bench   TEXT,                      -- e.g. "NCLT Mumbai"
    case_number  TEXT,                      -- e.g. "CP (IB) No. 123/MB/2021"
    cirp_start   DATE,
    rp_name      TEXT,                      -- Resolution Professional
    status       TEXT DEFAULT 'active',     -- active | resolved | liquidation
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- ── Resolution plan registry ──────────────────────────────────────────────────
-- One row per competing resolution plan submitted to the CoC.
CREATE TABLE IF NOT EXISTS matter.ibc_plans (
    id                  TEXT PRIMARY KEY,   -- md5(source)
    matter_id           TEXT REFERENCES matter.matters(id) ON DELETE CASCADE,
    source              TEXT NOT NULL,      -- "pdf:plan_a_xyz_corp.pdf"
    applicant           TEXT,               -- resolution applicant name
    applicant_type      TEXT,               -- "strategic" | "financial" | "promoter"
    consideration_crore REAL,               -- total offer (₹ crore)
    upfront_crore       REAL,               -- upfront cash component
    plan_date           DATE,
    coc_vote_pct        REAL,               -- % voting share in CoC approval (if approved)
    added_at            TIMESTAMPTZ DEFAULT now(),
    status              TEXT DEFAULT 'pending'  -- pending | checked | scored | approved | rejected
);

CREATE INDEX IF NOT EXISTS ibc_plans_matter_idx ON matter.ibc_plans (matter_id);

-- ── Plan structural nodes ─────────────────────────────────────────────────────
-- Section-level nodes extracted from the resolution plan PDF via pageindex/semchunk.
-- Each node gets an embedding for SBERT-based matching against standard requirements.
CREATE TABLE IF NOT EXISTS matter.ibc_plan_nodes (
    id           TEXT PRIMARY KEY,          -- md5(source + heading + page_start)
    plan_id      TEXT REFERENCES matter.ibc_plans(id) ON DELETE CASCADE,
    node_index   INTEGER NOT NULL,
    heading      TEXT,
    section_path TEXT,                      -- breadcrumb from pageindex tree
    content      TEXT NOT NULL,
    page_start   INTEGER,
    page_end     INTEGER,
    token_count  INTEGER,
    embedding    vector(768),               -- InLegal-SBERT embedding of heading + content
    embedded_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ibc_plan_nodes_plan_idx ON matter.ibc_plan_nodes (plan_id);
CREATE INDEX IF NOT EXISTS ibc_plan_nodes_hnsw_idx
    ON matter.ibc_plan_nodes USING hnsw (embedding vector_cosine_ops);

-- ── Compliance check results ──────────────────────────────────────────────────
-- One row per (plan × IBC requirement). Populated by the compliance engine.
-- human_verified = true once a lawyer has confirmed or overridden the AI finding.
CREATE TABLE IF NOT EXISTS matter.ibc_compliance (
    id               SERIAL PRIMARY KEY,
    plan_id          TEXT REFERENCES matter.ibc_plans(id) ON DELETE CASCADE,
    req_id           TEXT NOT NULL,         -- "A1", "B1", "C2", ... (20 standard reqs)
    matched_node_id  TEXT REFERENCES matter.ibc_plan_nodes(id),
    matched_heading  TEXT,                  -- denormalised for display
    confidence       REAL,                  -- cosine similarity score 0.0–1.0
    status           TEXT NOT NULL,         -- compliant | partial | non_compliant | not_found
    evidence         TEXT,                  -- verbatim quote or paraphrase from plan
    notes            TEXT,                  -- legal observation or gap
    human_verified   BOOLEAN DEFAULT false,
    human_override   TEXT,                  -- if human changed the status, record original
    verified_by      TEXT,                  -- lawyer/user who verified
    checked_at       TIMESTAMPTZ DEFAULT now(),
    UNIQUE (plan_id, req_id)                -- one result per plan per requirement
);

CREATE INDEX IF NOT EXISTS ibc_compliance_plan_idx ON matter.ibc_compliance (plan_id);
CREATE INDEX IF NOT EXISTS ibc_compliance_req_idx  ON matter.ibc_compliance (req_id);
CREATE INDEX IF NOT EXISTS ibc_compliance_status_idx ON matter.ibc_compliance (status);

-- ── Aggregate compliance scores ───────────────────────────────────────────────
-- One row per plan. Recalculated after each compliance run or human verification.
-- Scoring: compliant=5, partial=2, non_compliant=0, not_found=0
-- Rank is within the matter (among competing plans).
CREATE TABLE IF NOT EXISTS matter.ibc_scores (
    plan_id           TEXT PRIMARY KEY REFERENCES matter.ibc_plans(id) ON DELETE CASCADE,
    total_score       REAL,                 -- weighted 0–100
    compliant         INTEGER DEFAULT 0,
    partial           INTEGER DEFAULT 0,
    non_compliant     INTEGER DEFAULT 0,
    not_found         INTEGER DEFAULT 0,
    human_verified_ct INTEGER DEFAULT 0,    -- how many findings human-confirmed
    rank              INTEGER,              -- rank within matter (1 = best)
    scored_at         TIMESTAMPTZ DEFAULT now()
);

-- ── Information Memorandum sections ──────────────────────────────────────────
-- Structural nodes from the IM. Used to cross-reference claims in resolution plans.
CREATE TABLE IF NOT EXISTS matter.im_sections (
    id           TEXT PRIMARY KEY,          -- md5(source + heading + page_start)
    matter_id    TEXT REFERENCES matter.matters(id) ON DELETE CASCADE,
    source       TEXT NOT NULL,             -- "pdf:information_memorandum.pdf"
    node_index   INTEGER,
    heading      TEXT,
    section_path TEXT,
    content      TEXT NOT NULL,
    page_start   INTEGER,
    page_end     INTEGER,
    embedding    vector(768),
    embedded_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS im_sections_matter_idx ON matter.im_sections (matter_id);
CREATE INDEX IF NOT EXISTS im_sections_hnsw_idx
    ON matter.im_sections USING hnsw (embedding vector_cosine_ops);

-- ── Financial statement metrics ───────────────────────────────────────────────
-- Key financial figures extracted from audited financials or IM financial tables.
-- Used to verify resolution plan claims (e.g. liquidation value stated in plan
-- vs. liquidation value in the IM or valuation report).
CREATE TABLE IF NOT EXISTS matter.financial_metrics (
    id           SERIAL PRIMARY KEY,
    matter_id    TEXT REFERENCES matter.matters(id) ON DELETE CASCADE,
    source       TEXT NOT NULL,             -- "pdf:financials_fy2024.pdf"
    metric_name  TEXT NOT NULL,             -- "net_worth" | "total_debt" | "liquidation_value"
    metric_value REAL,
    unit         TEXT DEFAULT 'crore_inr',
    period       TEXT,                      -- "FY2023-24" | "as_on_cirp_commencement"
    extracted_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS financial_metrics_matter_idx ON matter.financial_metrics (matter_id);
CREATE UNIQUE INDEX IF NOT EXISTS financial_metrics_uniq
    ON matter.financial_metrics (matter_id, source, metric_name, period);

-- ── Cross-plan comparison view ────────────────────────────────────────────────
-- Quick summary of all plans in a matter with their scores and key financial terms.
-- Used by the ibccompare DokuWiki plugin.
CREATE OR REPLACE VIEW matter.plan_comparison AS
SELECT
    m.company,
    m.case_number,
    m.nclt_bench,
    p.id                                        AS plan_id,
    p.applicant,
    p.applicant_type,
    p.consideration_crore,
    p.upfront_crore,
    p.plan_date,
    p.status                                    AS plan_status,
    s.total_score,
    s.compliant,
    s.partial,
    s.non_compliant,
    s.not_found,
    s.human_verified_ct,
    s.rank,
    -- Compliance pct among checked requirements
    ROUND(
        100.0 * s.compliant / NULLIF(s.compliant + s.partial + s.non_compliant + s.not_found, 0),
        1
    )                                           AS compliance_pct
FROM matter.matters m
JOIN matter.ibc_plans p     ON p.matter_id = m.id
LEFT JOIN matter.ibc_scores s ON s.plan_id  = p.id
ORDER BY m.id, s.rank NULLS LAST;

-- ── Per-requirement cross-plan view ──────────────────────────────────────────
-- For a given requirement, how does each plan score? Used for drill-down comparison.
CREATE OR REPLACE VIEW matter.requirement_comparison AS
SELECT
    p.matter_id,
    p.applicant,
    c.req_id,
    c.status,
    c.confidence,
    c.matched_heading,
    c.human_verified,
    c.evidence
FROM matter.ibc_compliance c
JOIN matter.ibc_plans p ON p.id = c.plan_id
ORDER BY p.matter_id, c.req_id, c.confidence DESC;

-- ── Scoring function ──────────────────────────────────────────────────────────
-- Recalculate and upsert score for a plan after compliance run.
-- Weights: compliant=5, partial=2, non_compliant=0, not_found=0
-- Max score = 20 requirements × 5 = 100
CREATE OR REPLACE FUNCTION matter.recalculate_score(p_plan_id TEXT)
RETURNS VOID AS $$
DECLARE
    v_compliant     INT;
    v_partial       INT;
    v_non_compliant INT;
    v_not_found     INT;
    v_verified      INT;
    v_score         REAL;
BEGIN
    SELECT
        COUNT(*) FILTER (WHERE status = 'compliant'),
        COUNT(*) FILTER (WHERE status = 'partial'),
        COUNT(*) FILTER (WHERE status = 'non_compliant'),
        COUNT(*) FILTER (WHERE status = 'not_found'),
        COUNT(*) FILTER (WHERE human_verified = true)
    INTO v_compliant, v_partial, v_non_compliant, v_not_found, v_verified
    FROM matter.ibc_compliance
    WHERE plan_id = p_plan_id;

    v_score := ROUND(
        100.0 * ((v_compliant * 5) + (v_partial * 2))
        / NULLIF((v_compliant + v_partial + v_non_compliant + v_not_found) * 5, 0),
        1
    );

    INSERT INTO matter.ibc_scores
        (plan_id, total_score, compliant, partial, non_compliant, not_found, human_verified_ct, scored_at)
    VALUES
        (p_plan_id, v_score, v_compliant, v_partial, v_non_compliant, v_not_found, v_verified, now())
    ON CONFLICT (plan_id) DO UPDATE SET
        total_score       = EXCLUDED.total_score,
        compliant         = EXCLUDED.compliant,
        partial           = EXCLUDED.partial,
        non_compliant     = EXCLUDED.non_compliant,
        not_found         = EXCLUDED.not_found,
        human_verified_ct = EXCLUDED.human_verified_ct,
        scored_at         = EXCLUDED.scored_at;

    -- Update ranks within the matter
    WITH ranked AS (
        SELECT p.id, RANK() OVER (
            PARTITION BY p.matter_id
            ORDER BY s.total_score DESC NULLS LAST
        ) AS r
        FROM matter.ibc_plans p
        JOIN matter.ibc_scores s ON s.plan_id = p.id
        WHERE p.matter_id = (SELECT matter_id FROM matter.ibc_plans WHERE id = p_plan_id)
    )
    UPDATE matter.ibc_scores s
    SET rank = ranked.r
    FROM ranked
    WHERE s.plan_id = ranked.id;
END;
$$ LANGUAGE plpgsql;

-- ── Staleness view ────────────────────────────────────────────────────────────
-- A chunk is "stale" if it's in rag2_chunks but has never been ingested,
-- or if there's a newer ingest_log run for the same source that didn't re-process it.
CREATE OR REPLACE VIEW rag2_staleness AS
SELECT
    c.source,
    c.document_title,
    COUNT(*)                                        AS total_chunks,
    SUM(CASE WHEN c.lightrag_ingested THEN 1 ELSE 0 END) AS ingested_chunks,
    SUM(CASE WHEN NOT c.lightrag_ingested THEN 1 ELSE 0 END) AS pending_chunks,
    SUM(CASE WHEN c.ingest_error IS NOT NULL THEN 1 ELSE 0 END) AS failed_chunks,
    MAX(c.ingested_at)                              AS last_ingested_at,
    CASE
        WHEN MAX(c.ingested_at) IS NULL THEN 'never_ingested'
        WHEN SUM(CASE WHEN c.ingest_error IS NOT NULL THEN 1 ELSE 0 END) > 0 THEN 'partial'
        WHEN SUM(CASE WHEN NOT c.lightrag_ingested THEN 1 ELSE 0 END) > 0 THEN 'partial'
        ELSE 'ok'
    END                                             AS status
FROM rag2_chunks c
GROUP BY c.source, c.document_title;
