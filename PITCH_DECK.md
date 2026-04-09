# RAG2 — Pitch Deck

---

## Slide 1: Title

# RAG2
### AI-Powered Insolvency Compliance Platform

> Turn 200-page resolution plans into scored, ranked, auditable compliance reports — inside your wiki.

---

## Slide 2: The Problem

### India's insolvency lawyers are drowning in paper

- **~6,000 active CIRP cases** under IBC 2016, each with 3–5 competing resolution plans
- Each plan: 150–400 pages of dense legal/financial text
- Lawyers must manually verify **20 mandatory statutory requirements** per plan — Section 53 priority, OC minimum liquidation value, dissenting FC protection, Section 29A eligibility, etc.
- **3–5 plans per case** → 60–100 manual compliance checks per matter
- Average review: **2–3 weeks per plan**. Errors are common. Missed requirements get challenged in NCLT.
- No tool exists for this. Legal AI products are generic chatbots — none understand IBC structure.

**Bottom line:** A ₹50 crore plan can be rejected for a missed Section 53(1)(b) compliance gap that a lawyer overlooked on page 187.

---

## Slide 3: The Solution

### RAG2 — Purpose-built IBC compliance engine

RAG2 is not a chatbot. It is a **structured compliance verification system** with two engines:

| | LLM Engine | Deterministic Engine |
|---|---|---|
| How | Sarvam AI reads the full plan text | InLegal-SBERT vectors matched against 20 requirement embeddings |
| Speed | ~30 seconds per plan | ~5 seconds per plan |
| Strength | Contextual understanding, evidence extraction | Auditable, no hallucination, mathematically grounded scores |
| Use | First-pass screening | Verification & ranking |

**Both engines produce the same output:** a 20-row compliance matrix with status, evidence quote, and confidence score.

---

## Slide 4: How It Works

### PDF → Scored Compliance Report in 60 seconds

```
1. UPLOAD          Lawyer drops a PDF onto a wiki page
   {{ibcverify>pdf:plan_alpha.pdf}}

2. PARSE           LiteParse extracts text with page numbers,
                    India-specific heuristics (footnote annotations,
                    legal headings, OCR for scanned orders)

3. STRUCTURE       PageIndex stitches cross-page sections into
                    a hierarchical tree with LLM-generated summaries

4. CHUNK           SemChunk splits into 512-token chunks with
                    75-token overlap + ancestor breadcrumbs

5. VERIFY          pgvector matches each of 20 IBC requirements
                    against plan section embeddings (0.70 cosine +
                    0.30 heading match + keyword signals)

6. REVIEW          Lawyer sees confidence bars, evidence quotes,
                    and can override any finding with one click

7. COMPARE         Multiple plans ranked side-by-side:
                    Plan A scores 78/100, Plan B scores 64/100
```

---

## Slide 5: The Deterministic Engine — Our Moat

### No other legal AI product does this

The deterministic engine uses **no LLM during verification**. It's pure vector math:

1. Each of the 20 IBC requirements has pre-computed embeddings and keyword rules
2. Plan sections are embedded via **InLegal-SBERT** (768-dim, trained on Indian legal text)
3. Cosine similarity + heading alias overlap + keyword signals → composite score
4. Score thresholds map to compliant / partial / non-compliant / not-found

**Why this matters:**
- LLMs hallucinate. Judges don't accept hallucinated compliance.
- Deterministic scores are **reproducible** — run it twice, same answer.
- Lawyers can **explain the score**: "Section 53 matched at 0.82 cosine to plan page 143, confirmed by keywords 'waterfall distribution' and 'operational creditors'"
- Enables **multi-plan ranking** — compare 5 plans on the same mathematical basis

---

## Slide 6: The Compliance Matrix

### 20 requirements across 6 categories, every time

| Category | Requirements | What It Checks |
|---|---|---|
| **A — Priority Payments** | A1, A2 | CIRP costs funded? Priority under S.53? |
| **B — Operational Creditors** | B1, B2, B3 | OC minimum liquidation value? Timeline? Employee dues? |
| **C — Financial Creditors** | C1, C2, C3, C4 | Total consideration? Distribution plan? Dissenting FC? Payment schedule? |
| **D — Default & Viability** | D1, D2, D3, D4 | Cause addressed? Implementation viable? Projections? Going concern? |
| **E — Governance** | E1, E2, E3, E4 | Management structure? Shareholding? Timeline? Monitoring committee? |
| **F — Regulatory** | F1, F2, F3 | Approvals identified? Non-contravention? S.29A eligible? |

Each requirement carries **statutory section reference**, **heading aliases** (for matching), **required signals** (must-appear keywords), and **disqualifying signals** (red flags).

---

## Slide 7: Human-in-the-Loop

### AI suggests. The lawyer decides.

Every finding has four override buttons: **Confirm → Partial → Non-Compliant → Not Found**

- Override is recorded with lawyer identity + timestamp
- Original AI status preserved in audit trail
- Aggregate score and rank **automatically recalculate** after any override
- Verified findings get a checkmark — clear visual signal for reviewers and NCLT

This is not black-box AI. It's **AI-assisted legal work product** with a defensible audit trail.

---

## Slide 8: Multi-Plan Comparison

### The real value: rank competing plans objectively

When 3 resolution applicants submit plans for the same CIRP case:

```
┌──────────────────┬────────┬────────┬────────┐
│                  │ Plan A │ Plan B │ Plan C │
├──────────────────┼────────┼────────┼────────┤
│ Score            │ 78/100 │ 64/100 │ 51/100 │
│ Rank             │   #1   │   #2   │   #3   │
│ Consideration    │ ₹450cr │ ₹380cr │ ₹290cr │
│ Upfront Cash     │ ₹120cr │  ₹95cr │  ₹60cr │
│ Compliant reqs   │   14   │   10   │    6   │
│ Partial reqs     │    4   │    4   │    5   │
│ Non-compliant    │    2   │    4   │    7   │
│ Human verified   │   18   │    5   │    0   │
└──────────────────┴────────┴────────┴────────┘
```

Click any requirement to drill down: "Plan A is compliant on B3 (employee dues) with 0.89 confidence, matched to page 143. Plan B is partial with 0.61 confidence, matched to page 98."

---

## Slide 9: Technology Stack

### Built for Indian legal text, not generic RAG

| Layer | Choice | Why |
|---|---|---|
| **Embeddings** | InLegal-SBERT (768-dim) | Fine-tuned on Indian legal corpus, not generic Wikipedia |
| **LLM** | Sarvam AI sarvam-m | Indian-built, understands Hindi/English legal code-switching |
| **Graph** | Apache AGE on PostgreSQL | Entity-relation knowledge graph in standard SQL |
| **Vectors** | pgvector HNSW | ANN search in same Postgres container, no separate vector DB |
| **Search** | Hybrid BM25 + dense + RRF | 60% exact-term / 40% semantic — statutory terms need BM25 |
| **PDF Parsing** | LiteParse + India heuristics | Handles IBBI's HTML-wrapped PDFs, scanned orders, legal annotations |
| **Frontend** | DokuWiki plugins | Lawyers live in wikis — no new app to learn |
| **Storage** | PostgreSQL (single container) | KV + vector + graph + audit in one 200MB container |

---

## Slide 10: Contextual Retrieval + Metadata

### Tier-1 quality improvements already in production

**Contextual Retrieval (Anthropic 2024):**
Each chunk gets a 2–3 sentence situating blurb from Sarvam AI before embedding:
> *"This is a liquidation order by NCLT Mumbai concerning ABC Steel Pvt Ltd, appointing Mr X as liquidator under Section 33 of IBC 2016, dated 15 September 2023."*

35–49% reduction in retrieval failure rate.

**Structured Metadata Extraction:**
Every chunk carries `doc_type`, `doc_date`, `parties[]`, `statutory_refs[]` — extracted via LLM + regex (IBC sections, SEBI regulations, Companies Act rules). Enables:
- "Show me only IBBI orders from 2024"
- "Find all documents mentioning ABC Steel as corporate debtor"
- "Which orders cite Section 53 IBC?"

**75-token chunk overlap** prevents reasoning split at boundaries.

---

## Slide 11: The Knowledge Graph

### Beyond search — structured legal intelligence

LightRAG extracts entities and relations with a **custom Indian legal taxonomy**:

**Entity types:** Person, Organization, Location, CourtTribunal, StatuteProvision, LegalConcept, RegulatoryInstrument, PartyRole, CaseReference

**Example graph:**
```
ABC Steel (Organization) ─FILED_AGAINST→ SBI (Financial Creditor)
ABC Steel ─APPOINTED_AS→ Mr. X (Resolution Professional)
NCLT Mumbai (CourtTribunal) ─GOVERNS→ CP(IB)123/MB/2021 (CaseReference)
Section 33 IBC (StatuteProvision) ─CITED_AS_PRECEDENT→ This Order
```

Enables multi-hop queries:
- *"Find orders citing Section 53 with above-liquidation-value distribution"*
- *"Which RPs have been appointed in cases involving SBI as FC?"*
- *"SEBI circulars that supersede Circular No. SEBI/2023/42"*

---

## Slide 12: Market Opportunity

### IBC 2016 created a $2B+ legal services market

- **~6,000 active CIRP cases** at any time (IBBI data)
- **1,200+ new admissions per year** at NCLT benches
- Each case requires: compliance verification, plan comparison, regulatory cross-referencing
- **Resolution Professionals** (1,300+ registered) are personally liable for compliance gaps
- **CoC members** (banks, FIs) need independent compliance opinions before voting
- **NCLT/NCLAT** need transparent, reproducible compliance assessments

**Current spend:** Law firms charge ₹15–50 lakh per CIRP case for plan review. Much of this is document reading and compliance checking — exactly what RAG2 automates.

---

## Slide 13: Competitive Landscape

### No one is building this for Indian insolvency

| | RAG2 | Generic Legal AI (Harvey, CoCounsel) | Indian Legal Tech (Sirion, SpotDraft) |
|---|---|---|---|
| IBC-specific compliance | 20 requirements, deterministic | Generic Q&A | No |
| Indian legal embeddings | InLegal-SBERT | GPT embeddings | N/A |
| Multi-plan ranking | Scored & ranked | No | No |
| Human-in-the-loop audit | Override + recalculated scores | Chat history | No |
| Deterministic verification | pgvector matching | LLM-only | LLM-only |
| India-specific PDF parsing | IBBI/SEBI heuristics | Generic PDF | Generic PDF |
| Wiki-native workflow | DokuWiki plugins | Separate app | Separate app |

---

## Slide 14: Roadmap

### What's built and what's next

**Now (working):**
- Full PDF → compliance pipeline
- Two compliance engines (LLM + deterministic)
- Multi-plan comparison & ranking
- Human verification with audit trail
- Hybrid BM25 + vector search with metadata filtering
- Knowledge graph with legal entity taxonomy
- 6 DokuWiki plugins

**Next 3 months (Tier 2):**
- Citation graph edges via regex (Section/Regulation cross-references as AGE edges)
- Temporal edges for SEBI circulars (supersedes chains with effective dates)
- HyDE query expansion for analytical queries
- Scalar quantization (halfvec for 2x storage efficiency)
- Full custom entity taxonomy (CLAIM_AMOUNT, LIQUIDATION_VALUE, INSOLVENCY_COMMENCEMENT)

**Next 6 months (Tier 3):**
- RAPTOR summary tree for global/thematic queries
- Co-reference resolution (replace "the Respondent" with entity names)
- MRL fine-tuned InLegal-SBERT (256-dim fast retrieval + 768-dim reranking)
- Claim/proposition extraction as atomic fact nodes
- Poly-vector indexing (content + label embeddings)

---

## Slide 15: The Team & Ask

### Built by practitioners, for practitioners

RAG2 was built from the ground up by someone who understands:
- The IBC workflow (what lawyers actually do day-to-day)
- Indian legal document quirks (IBBI PDF formatting, code-switching, scanned orders)
- The gap between "AI can answer questions" and "AI can produce auditable legal work product"

**The ask:**
- We're looking for early adopters among resolution professionals and insolvency law firms
- Pilot with 5 firms → validate scoring accuracy against human review → build case studies for NCLT admissibility

---

## Slide 16: Closing

> **Don't read 400 pages. Verify 20 requirements.**

RAG2 turns hours of document review into seconds of structured, auditable compliance scoring — and gives lawyers the override button that makes it legally defensible.

---

*Contact: [your details]*