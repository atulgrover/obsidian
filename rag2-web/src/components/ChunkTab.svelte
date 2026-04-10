<script lang="ts">
  import { vault } from '../api/vault';
  import type { ChunkMeta } from '../api/vault';

  let { slug = '' } = $props();

  let chunks: ChunkMeta[] = $state([]);
  let loading = $state(false);
  let error = $state('');
  let expanded: Set<number> = $state(new Set());
  let chunking = $state(false);
  let embedding = $state(false);
  let chunkResult = $state('');
  let embedResult = $state('');
  let chunkDetails: Record<number, any> = $state({});

  $effect(() => { if (slug) loadChunks(); });

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
    if (next.has(i)) next.delete(i); else next.add(i);
    expanded = next;
  }

  async function loadDetail(i: number) {
    try {
      const note = await vault.getChunk(slug, `chunk-${String(i + 1).padStart(3, '0')}`);
      chunkDetails[i] = note;
    } catch { /* ignore */ }
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

  $effect(() => {
    if (expanded.size > 0) {
      expanded.forEach(i => {
        if (!chunkDetails[i]) loadDetail(i);
      });
    }
  });

  const totalTokens = $derived(chunks.reduce((n, c) => n + c.token_count, 0));
</script>

<div class="chunk-tab">
  <div class="toolbar">
    <div class="toolbar-left">
      <span class="chip">{chunks.length} chunks</span>
      <span class="chip">{totalTokens.toLocaleString()} tokens</span>
    </div>
    <div class="toolbar-right">
      <button onclick={runChunk} disabled={chunking}>{chunking ? 'Chunking...' : 'Chunk'}</button>
      <button onclick={runEmbed} disabled={embedding || chunks.length === 0}>{embedding ? 'Embedding...' : 'Embed'}</button>
    </div>
  </div>
  {#if chunkResult}<div class="result">{chunkResult}</div>{/if}
  {#if embedResult}<div class="result">{embedResult}</div>{/if}

  {#if loading}
    <div class="loading">Loading chunks...</div>
  {:else if chunks.length === 0}
    <div class="empty">No chunks yet. Click "Chunk" to create them.</div>
  {:else}
    <div class="chunks-list">
      {#each chunks as chunk, i}
        <div class="chunk-item" role="button" tabindex="0" onclick={() => toggle(i)} onkeydown={(e) => e.key === 'Enter' || e.key === ' ' ? toggle(i) : null}>
          <div class="chunk-row">
            <span class="chunk-toggle">{expanded.has(i) ? '▼' : '▶'}</span>
            <span class="chunk-id">#{i + 1}</span>
            <span class="chunk-pages">p.{chunk.page_start}–{chunk.page_end}</span>
            <span class="chunk-tokens">{chunk.token_count}t</span>
            <span class="chunk-stage" class:ingested={chunk.lightrag_ingested}>
              {chunk.lightrag_ingested ? 'Embedded' : 'Pending'}
            </span>
          </div>
          {#if expanded.has(i) && chunkDetails[i]}
            <div class="chunk-detail">
              <div class="detail-meta">
                <span>Level: {chunkDetails[i].metadata?.level || '-'}</span>
                <span>Overlap: {chunkDetails[i].metadata?.has_overlap ? 'Yes' : 'No'}</span>
              </div>
              {#if chunkDetails[i].metadata?.parent_context}
                <div class="detail-context">
                  <span class="context-label">Context:</span>
                  {chunkDetails[i].metadata.parent_context}
                </div>
              {/if}
              <pre class="chunk-body">{chunkDetails[i].body}</pre>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .chunk-tab { display: flex; flex-direction: column; height: 100%; }
  .toolbar {
    display: flex; justify-content: space-between; align-items: center;
    padding: 8px 16px; border-bottom: 1px solid #312e81; flex-shrink: 0;
  }
  .toolbar-left { display: flex; gap: 6px; }
  .chip { background: #1e1b4b; border: 1px solid #312e81; border-radius: 4px; padding: 2px 8px; font-size: 11px; color: #818cf8; }
  .toolbar-right { display: flex; gap: 6px; }
  .toolbar-right button {
    padding: 5px 14px; border-radius: 4px; border: 1px solid #312e81;
    background: #4f46e5; color: white; cursor: pointer; font-size: 12px;
  }
  .toolbar-right button:disabled { opacity: 0.5; }
  .result { padding: 4px 16px; font-size: 12px; color: #22c55e; }

  .chunks-list { flex: 1; overflow-y: auto; }
  .chunk-item { cursor: pointer; }
  .chunk-row {
    display: flex; align-items: center; gap: 6px; padding: 6px 16px; font-size: 12px; color: #c4b5fd;
    border-bottom: 1px solid #1e1b4b;
  }
  .chunk-row:hover { background: rgba(79, 70, 229, 0.1); }
  .chunk-toggle { width: 14px; font-size: 10px; color: #818cf8; }
  .chunk-id { font-weight: bold; }
  .chunk-pages { color: #6b7280; }
  .chunk-tokens { color: #818cf8; }
  .chunk-stage { margin-left: auto; padding: 1px 6px; border-radius: 10px; font-size: 10px; }
  .chunk-stage.ingested { background: #166534; color: #22c55e; }
  .chunk-stage:not(.ingested) { background: #312e81; color: #818cf8; }

  .chunk-detail { padding: 6px 16px 10px 30px; background: #0f0d2e; }
  .detail-meta { display: flex; gap: 12px; margin-bottom: 6px; font-size: 11px; color: #6b7280; }
  .detail-context { font-size: 11px; color: #818cf8; margin-bottom: 6px; }
  .context-label { color: #a78bfa; font-weight: bold; }
  .chunk-body { white-space: pre-wrap; font-size: 11px; color: #c4b5fd; max-height: 200px; overflow-y: auto; margin: 0; }

  .loading, .empty { padding: 32px; text-align: center; color: #818cf8; }
</style>