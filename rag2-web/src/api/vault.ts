/**
 * Vault Pipeline API client — TypeScript types and fetch wrappers.
 * All URLs are relative — Vite dev server proxies /vault→:5004, /lightrag→:5004, /api/lightrag→:8020.
 */

// ──────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────

export interface SourceMeta {
  slug: string;
  pipeline_stage: string;
  filename: string;
  total_pages: number;
  total_chars: number;
  doc_type: string;
  created_at: string;
}

export interface SectionMeta {
  filename: string;
  title: string;
  level: number;
  is_leaf: boolean;
  page_start: number;
  page_end: number;
  word_count: number;
  breadcrumb?: string;
  llm_summary?: string;
}

export interface ChunkMeta {
  chunk_index: number;
  token_count: number;
  page_start: number;
  page_end: number;
  lightrag_ingested: boolean;
  pipeline_stage: string;
}

export interface VaultNote {
  metadata: Record<string, unknown>;
  body: string;
}

export interface ComplianceResult {
  id: string;
  category: string;
  requirement: string;
  section: string;
  status: 'compliant' | 'partial' | 'non_compliant' | 'not_found';
  evidence?: string;
  notes?: string;
}

export interface ComplianceCheckResponse {
  source: string;
  document_title: string;
  checked_at: string;
  chunks_analyzed: number;
  overall_status: string;
  compliant: number;
  partial: number;
  non_compliant: number;
  not_found: number;
  results: ComplianceResult[];
  duration_ms: number;
}

export interface MatterSetupResponse {
  matter_id: string;
  plan_id: string;
  status: string;
}

export interface IngestPdfResponse {
  success: boolean;
  slug: string;
  vault_path: string;
  sections: number;
  total_pages: number;
  total_chars: number;
  message: string;
}

export interface ChunkFromVaultResponse {
  success: boolean;
  slug: string;
  total_chunks: number;
  total_tokens: number;
  message: string;
}

export interface IngestLightragResponse {
  success: boolean;
  slug: string;
  ingested: number;
  skipped: number;
  failed: number;
  run_id: string;
  message: string;
}

// ──────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────

async function api<T>(url: string, opts?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...((opts?.headers as Record<string, string>) || {}) },
    ...opts,
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => resp.statusText);
    throw new Error(detail?.detail || detail?.message || `HTTP ${resp.status}`);
  }
  return resp.json();
}

// ──────────────────────────────────────────────────────────
// Vault Pipeline (port 5004)
// ──────────────────────────────────────────────────────────

export const vault = {
  /** Save PDF only (no processing) — upload from local file */
  savePdfUpload: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return fetch(`/vault/save-pdf-upload`, { method: 'POST', body: form }).then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json() as Promise<{ success: boolean; slug: string; filename: string; message: string }>;
    });
  },

  /** Save PDF only (no processing) — from URL */
  savePdfUrl: (url: string) =>
    api<{ success: boolean; slug: string; filename: string; message: string }>(`/vault/save-pdf-url`, {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),

  /** Stage 1: PDF → LiteParse → PageIndex → vault markdown */
  ingestPdf: (url: string, maxTokens = 512, overlapTokens = 75) =>
    api<IngestPdfResponse>(`/vault/ingest-pdf`, {
      method: 'POST',
      body: JSON.stringify({ url, max_tokens: maxTokens, overlap_tokens: overlapTokens }),
    }),

  /** Stage 1 via file upload */
  ingestPdfUpload: (file: File, maxTokens = 512, overlapTokens = 75) => {
    const form = new FormData();
    form.append('file', file);
    form.append('max_tokens', String(maxTokens));
    form.append('overlap_tokens', String(overlapTokens));
    return fetch(`/vault/ingest-pdf-upload`, { method: 'POST', body: form }).then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json() as Promise<IngestPdfResponse>;
    });
  },

  /** Stage 2: vault sections → SemChunk → vault chunks */
  chunk: (slug: string, maxTokens = 512, overlapTokens = 75) =>
    api<ChunkFromVaultResponse>(`/vault/chunk`, {
      method: 'POST',
      body: JSON.stringify({ slug, max_tokens: maxTokens, overlap_tokens: overlapTokens }),
    }),

  /** Stage 3: vault chunks → LightRAG → Postgres */
  ingestLightrag: (slug: string) =>
    api<IngestLightragResponse>(`/vault/ingest-lightrag`, {
      method: 'POST',
      body: JSON.stringify({ slug }),
    }),

  /** Stages 1→2→3 in sequence (URL) */
  fullPipeline: (url: string, maxTokens = 512, overlapTokens = 75) =>
    api<Record<string, unknown>>(`/vault/full-pipeline`, {
      method: 'POST',
      body: JSON.stringify({ url, max_tokens: maxTokens, overlap_tokens: overlapTokens }),
    }),

  /** Stages 1→2→3 in sequence (file upload) */
  fullPipelineUpload: (file: File, maxTokens = 512, overlapTokens = 75) => {
    const form = new FormData();
    form.append('file', file);
    form.append('max_tokens', String(maxTokens));
    form.append('overlap_tokens', String(overlapTokens));
    return fetch(`/vault/full-pipeline-upload`, { method: 'POST', body: form }).then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json() as Promise<Record<string, unknown>>;
    });
  },

  /** List all source documents */
  listSources: () =>
    api<{ sources: SourceMeta[] }>(`/vault/sources`),

  /** Get source document metadata */
  getSource: (slug: string) =>
    api<{ slug: string; metadata: Record<string, unknown>; body: string; sections_count: number }>(
      `/vault/sources/${slug}`,
    ),

  /** List section notes */
  listSections: (slug: string) =>
    api<{ slug: string; sections: SectionMeta[] }>(`/vault/sources/${slug}/sections`),

  /** Get section note */
  getSection: (slug: string, sectionId: string) =>
    api<VaultNote>(`/vault/sources/${slug}/sections/${sectionId}`),

  /** List chunk notes */
  listChunks: (slug: string) =>
    api<{ slug: string; chunks: ChunkMeta[] }>(`/vault/chunks/${slug}`),

  /** Get chunk note */
  getChunk: (slug: string, chunkId: string) =>
    api<VaultNote>(`/vault/chunks/${slug}/${chunkId}`),

  /** Get PDF URL for a source document */
  getPdfUrl: (slug: string) =>
    `/vault/attachments/${slug}`,

  /** Get full-text markdown for a source document */
  getFullText: (slug: string) =>
    api<{ metadata: Record<string, unknown>; body: string }>(`/vault/sources/${slug}/full-text`),

  /** Get cached LiteParse output */
  getParse: (slug: string) =>
    api<Record<string, unknown>>(`/vault/sources/${slug}/parse`),

  /** Get cached PageIndex tree */
  getTree: (slug: string) =>
    api<Record<string, unknown>>(`/vault/sources/${slug}/tree`),

  /** Delete a source document from the vault */
  deleteSource: (slug: string) =>
    api<{ success: boolean; slug: string; removed: string[] }>(`/vault/sources/${slug}`, {
      method: 'DELETE',
    }),

  /** Run a single pipeline stage */
  runStage: (stage: 'parse' | 'cleanse' | 'extract' | 'index' | 'enrich' | 'chunk' | 'embed' | 'karpathy', slug: string, maxTokens = 512, overlapTokens = 75) =>
    api<Record<string, unknown>>(`/vault/stage/${stage}`, {
      method: 'POST',
      body: JSON.stringify({ slug, max_tokens: maxTokens, overlap_tokens: overlapTokens }),
    }),
};

// ──────────────────────────────────────────────────────────
// LightRAG (port 8020)
// ──────────────────────────────────────────────────────────

export const lightrag = {
  /** IBC Compliance Check */
  complianceCheck: (slug: string) =>
    api<ComplianceCheckResponse>(`/lightrag/compliance/check`, {
      method: 'POST',
      body: JSON.stringify({ slug }),
    }),

  /** Matter setup */
  matterSetup: (data: {
    company: string; cin?: string; nclt_bench?: string; case_number?: string;
    source: string; applicant?: string; applicant_type?: string;
    consideration_crore?: number; upfront_crore?: number;
  }) =>
    api<MatterSetupResponse>(`/api/lightrag/matter/setup`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /** Index plan sections */
  matterPlanIndex: (planId: string, slug: string) =>
    api<{ plan_id: string; nodes_indexed: number }>(`/api/lightrag/matter/plan/index`, {
      method: 'POST',
      body: JSON.stringify({ plan_id: planId, chunks: [] }),
    }),

  /** Verify compliance */
  matterPlanVerify: (planId: string) =>
    api<Record<string, unknown>>(`/api/lightrag/matter/plan/verify?plan_id=${planId}`, {
      method: 'POST',
    }),

  /** Human verification override */
  matterComplianceHuman: (planId: string, reqId: string, status: string, notes?: string) =>
    api<{ ok: boolean }>(`/api/lightrag/matter/compliance/human`, {
      method: 'POST',
      body: JSON.stringify({ plan_id: planId, req_id: reqId, status, notes, verified_by: 'web-ui' }),
    }),

  /** Audit source */
  auditSource: (src: string) =>
    api<Record<string, unknown>>(`/api/lightrag/audit/source?src=${encodeURIComponent(src)}`),

  /** Health */
  health: () =>
    api<{ status: string }>(`/api/lightrag/health`),
};