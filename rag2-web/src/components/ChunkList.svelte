<script lang="ts">
  import { vault } from '../api/vault';
  import type { ChunkMeta } from '../api/vault';

  export let slug = '';

  let chunks: ChunkMeta[] = [];
  let loading = false;
  let ingesting = false;
  let error = '';
  let expandedChunk = -1;
  let chunkDetail: Record<string, unknown> | null = null;

  $: if (slug) loadChunks();

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

  async function runChunking() {
    loading = true;
    error = '';
    try {
      const resp = await vault.chunk(slug);
      chunks = (await vault.listChunks(slug)).chunks;
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function runIngest() {
    ingesting = true;
    error = '';
    try {
      await vault.ingestLightrag(slug);
      await loadChunks();
    } catch (e: any) {
      error = e.message;
    } finally {
      ingesting = false;
    }
  }

  async function toggleChunk(idx: number) {
    if (expandedChunk === idx) {
      expandedChunk = -1;
      chunkDetail = null;
    } else {
      expandedChunk = idx;
      try {
        chunkDetail = await vault.getChunk(slug, `chunk-${String(idx + 1).padStart(3, '0')}`);
      } catch {
        chunkDetail = null;
      }
    }
  }

  function ingestStatus(ingested: boolean): { label: string; color: string } {
    return ingested
      ? { label: 'Ingested', color: '#22c55e' }
      : { label: 'Pending', color: '#f59e0b' };
  }
</script>

<div class="chunk-list">
  <div class="header">
    <h2>Chunks: {slug}</h2>
    <div class="actions">
      <button on:click={runChunking} disabled={loading}>Chunk from Vault</button>
      <button on:click={runIngest} disabled={ingesting} class="ingest-btn">
        {ingesting ? 'Ingesting...' : 'Ingest to LightRAG'}
      </button>
    </div>
    {#if chunks.length > 0}
      <div class="summary">{chunks.length} chunks · {chunks.reduce((s, c) => s + c.token_count, 0).toLocaleString()} tokens</div>
    {/if}
  </div>

  {#if error}
    <div class="error">{error}</div>
  {/if}

  {#if loading && chunks.length === 0}
    <div class="loading">Loading chunks...</div>
  {:else}
    <div class="chunks">
      {#each chunks as chunk, i}
        <div class="chunk-item" on:click={() => toggleChunk(i)}>
          <div class="chunk-header">
            <span class="chunk-id">chunk-{String(chunk.chunk_index + 1).padStart(3, '0')}</span>
            <span class="chunk-pages">pp.{chunk.page_start}-{chunk.page_end}</span>
            <span class="chunk-tokens">{chunk.token_count} tokens</span>
            <span class="status-badge" style="background:{ingestStatus(chunk.lightrag_ingested).color}">
              {ingestStatus(chunk.lightrag_ingested).label}
            </span>
          </div>
          {#if expandedChunk === i && chunkDetail}
            <div class="chunk-body">
              <pre>{chunkDetail.body || ''}</pre>
              {#if chunkDetail.metadata}
                <div class="chunk-meta">
                  {#each Object.entries(chunkDetail.metadata) as [k, v]}
                    {#if k !== 'type'}
                      <span class="meta-tag">{k}: {typeof v === 'object' ? JSON.stringify(v) : v}</span>
                    {/if}
                  {/each}
                </div>
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .chunk-list { font-family: system-ui, sans-serif; }
  .header { display: flex; align-items: center; gap: 12px; padding: 12px 16px; background: #1e1b4b; border-radius: 8px 8px 0 0; flex-wrap: wrap; }
  .header h2 { margin: 0; color: #e0e7ff; font-size: 16px; }
  .actions { display: flex; gap: 8px; }
  .actions button { padding: 6px 14px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; background: #4f46e5; color: white; }
  .actions button:disabled { opacity: 0.5; cursor: not-allowed; }
  .ingest-btn { background: #059669 !important; }
  .summary { color: #a5b4fc; font-size: 13px; }
  .chunks { max-height: 600px; overflow-y: auto; }
  .chunk-item { border-bottom: 1px solid #312e81; cursor: pointer; }
  .chunk-item:hover { background: rgba(79, 70, 229, 0.1); }
  .chunk-header { display: flex; align-items: center; gap: 10px; padding: 10px 16px; }
  .chunk-id { font-family: monospace; color: #a78bfa; font-size: 13px; min-width: 100px; }
  .chunk-pages { color: #6b7280; font-size: 12px; }
  .chunk-tokens { color: #6b7280; font-size: 12px; }
  .status-badge { padding: 2px 8px; border-radius: 10px; font-size: 11px; color: white; }
  .chunk-body { padding: 0 16px 12px; }
  .chunk-body pre { white-space: pre-wrap; font-size: 12px; color: #c4b5fd; background: #0f0d2e; padding: 12px; border-radius: 6px; max-height: 200px; overflow-y: auto; }
  .chunk-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
  .meta-tag { background: #312e81; color: #c4b5fd; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
  .loading, .error { text-align: center; padding: 20px; }
  .error { color: #f87171; }
</style>