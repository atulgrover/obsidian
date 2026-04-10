<script lang="ts">
  import { vault } from '../api/vault';
  import type { ChunkMeta, VaultNote } from '../api/vault';

  type ChunkFilter = 'all' | 'pending' | 'embedded' | 'long' | 'short';

  let { slug = '' } = $props();

  let chunks: ChunkMeta[] = $state([]);
  let loading = $state(false);
  let error = $state('');
  let expanded: Set<number> = $state(new Set());
  let chunking = $state(false);
  let embedding = $state(false);
  let chunkResult = $state('');
  let embedResult = $state('');
  let chunkDetails: Record<number, VaultNote> = $state({});
  let filter: ChunkFilter = $state('all');

  $effect(() => {
    if (slug) loadChunks();
  });

  async function loadChunks() {
    loading = true;
    error = '';
    try {
      const resp = await vault.listChunks(slug);
      chunks = resp.chunks;
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  function toggle(i: number) {
    const next = new Set(expanded);
    if (next.has(i)) next.delete(i);
    else next.add(i);
    expanded = next;
  }

  async function loadDetail(i: number) {
    try {
      const note = await vault.getChunk(slug, `chunk-${String(i + 1).padStart(3, '0')}`);
      chunkDetails[i] = note;
    } catch {
      // Ignore detail failures to keep the list usable.
    }
  }

  async function runChunk() {
    chunking = true;
    chunkResult = '';
    try {
      const resp = await vault.chunk(slug);
      chunkResult = `Chunked into ${resp.total_chunks} chunks (${resp.total_tokens} tokens)`;
      await loadChunks();
    } catch (e: any) {
      chunkResult = `Error: ${e.message}`;
    } finally {
      chunking = false;
    }
  }

  async function runEmbed() {
    embedding = true;
    embedResult = '';
    try {
      const resp = await vault.ingestLightrag(slug);
      embedResult = `Embedded ${resp.ingested} chunks (skipped ${resp.skipped}, failed ${resp.failed})`;
      await loadChunks();
    } catch (e: any) {
      embedResult = `Error: ${e.message}`;
    } finally {
      embedding = false;
    }
  }

  function matchesFilter(chunk: ChunkMeta): boolean {
    switch (filter) {
      case 'pending':
        return !chunk.lightrag_ingested;
      case 'embedded':
        return chunk.lightrag_ingested;
      case 'long':
        return chunk.token_count >= 500;
      case 'short':
        return chunk.token_count < 200;
      default:
        return true;
    }
  }

  function statusLabel(chunk: ChunkMeta): string {
    return chunk.lightrag_ingested ? 'Embedded' : 'Pending';
  }

  function statusClass(chunk: ChunkMeta): string {
    return chunk.lightrag_ingested ? 'embedded' : 'pending';
  }

  function tokenBand(chunk: ChunkMeta): string {
    if (chunk.token_count >= 500) return 'Long';
    if (chunk.token_count < 200) return 'Short';
    return 'Balanced';
  }

  $effect(() => {
    if (expanded.size > 0) {
      expanded.forEach((i) => {
        if (!chunkDetails[i]) loadDetail(i);
      });
    }
  });

  const totalTokens = $derived(chunks.reduce((n, c) => n + c.token_count, 0));
  const embeddedCount = $derived(chunks.filter((chunk) => chunk.lightrag_ingested).length);
  const pendingCount = $derived(chunks.length - embeddedCount);
  const longCount = $derived(chunks.filter((chunk) => chunk.token_count >= 500).length);
  const filteredChunks = $derived(chunks.filter(matchesFilter));
</script>

<div class="chunk-tab">
  <div class="chunk-header">
    <div>
      <h3>Chunk Triage</h3>
      <p>Review chunk size, context, and embed status before sending to LightRAG.</p>
    </div>
    <div class="toolbar-right">
      <button onclick={runChunk} disabled={chunking}>{chunking ? 'Chunking...' : 'Rebuild Chunks'}</button>
      <button class="embed-btn" onclick={runEmbed} disabled={embedding || chunks.length === 0}>{embedding ? 'Embedding...' : 'Embed To LightRAG'}</button>
    </div>
  </div>

  <div class="stats-grid">
    <div class="stat-card">
      <span class="stat-label">Total</span>
      <strong>{chunks.length}</strong>
      <span class="stat-sub">{totalTokens.toLocaleString()} tokens</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">Pending</span>
      <strong>{pendingCount}</strong>
      <span class="stat-sub">Need embedding</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">Embedded</span>
      <strong>{embeddedCount}</strong>
      <span class="stat-sub">Already sent</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">Long Chunks</span>
      <strong>{longCount}</strong>
      <span class="stat-sub">500+ tokens</span>
    </div>
  </div>

  <div class="filter-row">
    <div class="filter-pills">
      <button class:active={filter === 'all'} onclick={() => filter = 'all'}>All</button>
      <button class:active={filter === 'pending'} onclick={() => filter = 'pending'}>Pending</button>
      <button class:active={filter === 'embedded'} onclick={() => filter = 'embedded'}>Embedded</button>
      <button class:active={filter === 'long'} onclick={() => filter = 'long'}>Long</button>
      <button class:active={filter === 'short'} onclick={() => filter = 'short'}>Short</button>
    </div>
  </div>

  {#if chunkResult}
    <div class="result success">{chunkResult}</div>
  {/if}
  {#if embedResult}
    <div class="result success">{embedResult}</div>
  {/if}
  {#if error}
    <div class="result error">{error}</div>
  {/if}

  {#if loading}
    <div class="empty-state">Loading chunks...</div>
  {:else if filteredChunks.length === 0}
    <div class="empty-state">
      {#if chunks.length === 0}
        No chunks yet. Rebuild chunks to start triage.
      {:else}
        No chunks match the current filter.
      {/if}
    </div>
  {:else}
    <div class="chunk-list">
      {#each filteredChunks as chunk, i}
        <div
          class="chunk-card"
          class:expanded={expanded.has(chunk.chunk_index)}
          role="button"
          tabindex="0"
          onclick={() => toggle(chunk.chunk_index)}
          onkeydown={(e) => e.key === 'Enter' || e.key === ' ' ? toggle(chunk.chunk_index) : null}
        >
          <div class="chunk-summary">
            <div class="chunk-left">
              <span class="chunk-id">Chunk #{chunk.chunk_index + 1}</span>
              <span class="chunk-pages">Pages {chunk.page_start}-{chunk.page_end}</span>
              <span class="chunk-band">{tokenBand(chunk)}</span>
            </div>
            <div class="chunk-right">
              <span class="chunk-tokens">{chunk.token_count} tokens</span>
              <span class={`chunk-status ${statusClass(chunk)}`}>{statusLabel(chunk)}</span>
            </div>
          </div>

          {#if expanded.has(chunk.chunk_index)}
            <div class="chunk-detail">
              {#if chunkDetails[chunk.chunk_index]}
                <div class="detail-meta">
                  <span>Level: {chunkDetails[chunk.chunk_index].metadata?.level || '-'}</span>
                  <span>Overlap: {chunkDetails[chunk.chunk_index].metadata?.has_overlap ? 'Yes' : 'No'}</span>
                </div>
                {#if chunkDetails[chunk.chunk_index].metadata?.parent_context}
                  <div class="detail-context">
                    <span class="context-label">Context</span>
                    <p>{String(chunkDetails[chunk.chunk_index].metadata.parent_context)}</p>
                  </div>
                {/if}
                <pre class="chunk-body">{chunkDetails[chunk.chunk_index].body}</pre>
              {:else}
                <div class="detail-loading">Loading chunk detail...</div>
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .chunk-tab {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 18px 20px 24px;
  }

  .chunk-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
  }
  .chunk-header h3 {
    margin: 0 0 6px;
    font-size: 22px;
    color: var(--text-strong);
  }
  .chunk-header p {
    margin: 0;
    color: var(--text-muted);
    font-size: 13px;
  }

  .toolbar-right {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .toolbar-right button {
    padding: 10px 14px;
    border-radius: 12px;
    border: 1px solid var(--border-soft);
    background: var(--bg-card-soft);
    color: var(--text);
    font-size: 12px;
  }
  .toolbar-right button:disabled { opacity: 0.5; }
  .embed-btn {
    background: linear-gradient(135deg, #16a34a, var(--success)) !important;
    border-color: transparent !important;
    color: white !important;
  }

  .stats-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
  }
  .stat-card {
    padding: 14px;
    border: 1px solid var(--border-strong);
    border-radius: 18px;
    background: var(--bg-card);
  }
  .stat-label {
    display: block;
    margin-bottom: 8px;
    font-size: 11px;
    color: var(--accent-soft);
    text-transform: uppercase;
    letter-spacing: 0.12em;
  }
  .stat-card strong {
    display: block;
    font-size: 24px;
    color: var(--text-strong);
  }
  .stat-sub {
    font-size: 12px;
    color: var(--text-muted);
  }

  .filter-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
  }
  .filter-pills {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .filter-pills button {
    padding: 8px 12px;
    border-radius: 999px;
    border: 1px solid var(--border-soft);
    background: var(--bg-card-soft);
    color: var(--text);
    font-size: 12px;
  }
  .filter-pills button.active {
    background: linear-gradient(135deg, var(--accent), var(--accent-strong));
    border-color: transparent;
    color: white;
  }

  .result {
    padding: 10px 12px;
    border-radius: 12px;
    font-size: 12px;
  }
  .result.success {
    background: color-mix(in srgb, var(--success) 14%, var(--bg-card));
    border: 1px solid color-mix(in srgb, var(--success) 35%, transparent);
    color: #86efac;
  }
  .result.error {
    background: color-mix(in srgb, var(--danger) 10%, var(--bg-card));
    border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent);
    color: #fca5a5;
  }

  .chunk-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .chunk-card {
    border: 1px solid var(--border-strong);
    border-radius: 18px;
    background: var(--bg-card);
    overflow: hidden;
  }
  .chunk-card.expanded {
    border-color: var(--accent-soft);
  }
  .chunk-summary {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    padding: 14px 16px;
  }
  .chunk-left,
  .chunk-right {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }
  .chunk-id {
    font-size: 14px;
    font-weight: 700;
    color: var(--text-strong);
  }
  .chunk-pages,
  .chunk-tokens {
    font-size: 12px;
    color: var(--text-muted);
  }
  .chunk-band {
    padding: 3px 8px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--text-muted) 12%, transparent);
    color: var(--text);
    font-size: 11px;
  }
  .chunk-status {
    padding: 4px 9px;
    border-radius: 999px;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  .chunk-status.pending {
    background: color-mix(in srgb, var(--accent-strong) 14%, transparent);
    color: var(--accent-soft);
  }
  .chunk-status.embedded {
    background: color-mix(in srgb, var(--success) 14%, transparent);
    color: #86efac;
  }

  .chunk-detail {
    padding: 0 16px 16px;
    border-top: 1px solid var(--border);
  }
  .detail-meta {
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
    padding-top: 12px;
    margin-bottom: 10px;
    color: var(--text-muted);
    font-size: 11px;
  }
  .detail-context {
    margin-bottom: 12px;
    padding: 12px;
    border-radius: 14px;
    background: var(--bg-canvas);
  }
  .context-label {
    display: block;
    margin-bottom: 6px;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--accent-soft);
  }
  .detail-context p {
    margin: 0;
    color: var(--text);
    font-size: 12px;
    line-height: 1.5;
    white-space: pre-wrap;
  }
  .chunk-body {
    margin: 0;
    padding: 14px;
    border-radius: 14px;
    background: var(--bg-code);
    color: var(--text);
    font-size: 12px;
    line-height: 1.55;
    white-space: pre-wrap;
    max-height: 260px;
    overflow-y: auto;
  }
  .detail-loading,
  .empty-state {
    padding: 24px;
    border-radius: 16px;
    background: var(--bg-card);
    color: var(--text-faint);
    text-align: center;
  }

  @media (max-width: 1100px) {
    .stats-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @media (max-width: 720px) {
    .chunk-tab {
      padding-left: 14px;
      padding-right: 14px;
    }
    .chunk-header {
      flex-direction: column;
    }
    .stats-grid {
      grid-template-columns: 1fr;
    }
    .chunk-summary {
      flex-direction: column;
      align-items: flex-start;
    }
  }
</style>
