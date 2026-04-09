<script lang="ts">
  import { lightrag, vault } from '../api/vault';
  import type { ChunkMeta } from '../api/vault';

  export let slug = '';

  let chunks: ChunkMeta[] = [];
  let auditData: Record<string, unknown> | null = null;
  let loading = false;
  let reingesting = false;
  let error = '';

  $: if (slug) loadAudit();

  async function loadAudit() {
    loading = true;
    error = '';
    try {
      // Try LightRAG audit first
      auditData = await lightrag.auditSource(slug);
      chunks = (await vault.listChunks(slug)).chunks;
    } catch {
      // Fallback: just show vault chunks
      try {
        chunks = (await vault.listChunks(slug)).chunks;
      } catch (e: any) {
        error = e.message;
      }
    } finally {
      loading = false;
    }
  }

  async function reingest() {
    reingesting = true;
    try {
      await vault.ingestLightrag(slug);
      await loadAudit();
    } catch (e: any) {
      error = e.message;
    } finally {
      reingesting = false;
    }
  }

  function chunkStatus(chunk: ChunkMeta): { label: string; color: string; icon: string } {
    if (chunk.lightrag_ingested) return { label: 'Ingested', color: '#22c55e', icon: '✓' };
    if (chunk.pipeline_stage === 'error') return { label: 'Failed', color: '#ef4444', icon: '✗' };
    return { label: 'Pending', color: '#f59e0b', icon: '○' };
  }
</script>

<div class="chunk-audit">
  <div class="header">
    <h2>Chunk Audit: {slug}</h2>
    <button on:click={reingest} disabled={reingesting}>
      {reingesting ? 'Re-ingesting...' : 'Re-ingest to LightRAG'}
    </button>
  </div>

  {#if error}
    <div class="error">{error}</div>
  {/if}

  {#if auditData}
    {@const summary = auditData.summary as Record<string, number>}
    <div class="summary-bar">
      <span class="stat total">Total: {summary.total || chunks.length}</span>
      <span class="stat ingested" style="color:#22c55e">✓ Ingested: {summary.ingested || 0}</span>
      <span class="stat failed" style="color:#ef4444">✗ Failed: {summary.failed || 0}</span>
      <span class="stat pending" style="color:#f59e0b">○ Pending: {summary.pending || 0}</span>
    </div>
  {:else if chunks.length > 0}
    <div class="summary-bar">
      <span class="stat total">Total: {chunks.length}</span>
      <span class="stat ingested" style="color:#22c55e">✓ {chunks.filter(c => c.lightrag_ingested).length}</span>
      <span class="stat pending" style="color:#f59e0b">○ {chunks.filter(c => !c.lightrag_ingested).length}</span>
    </div>
  {/if}

  {#if loading}
    <div class="loading">Loading audit data...</div>
  {:else if chunks.length > 0}
    <table>
      <thead>
        <tr>
          <th>Status</th>
          <th>ID</th>
          <th>Pages</th>
          <th>Tokens</th>
          <th>Stage</th>
          <th>Ingested</th>
        </tr>
      </thead>
      <tbody>
        {#each chunks as chunk}
          {@const status = chunkStatus(chunk)}
          <tr>
            <td><span class="status-icon" style="color:{status.color}">{status.icon}</span></td>
            <td class="chunk-id">chunk-{String(chunk.chunk_index + 1).padStart(3, '0')}</td>
            <td>{chunk.page_start}-{chunk.page_end}</td>
            <td>{chunk.token_count}</td>
            <td><span class="stage-badge">{chunk.pipeline_stage || '—'}</span></td>
            <td>{chunk.lightrag_ingested ? '✓' : '—'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <div class="empty">No audit data available. Ingest a document first.</div>
  {/if}
</div>

<style>
  .chunk-audit { font-family: system-ui, sans-serif; }
  .header { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; background: linear-gradient(135deg, #1e3a5f, #1e1b4b); border-radius: 8px 8px 0 0; }
  .header h2 { margin: 0; color: #e0e7ff; font-size: 16px; }
  .header button { padding: 8px 16px; background: #059669; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; }
  .header button:disabled { opacity: 0.5; }
  .summary-bar { display: flex; gap: 16px; padding: 12px 20px; background: #1e1b4b; }
  .stat { font-size: 14px; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; padding: 8px 12px; background: #1e1b4b; color: #a78bfa; font-size: 11px; text-transform: uppercase; }
  td { padding: 8px 12px; border-bottom: 1px solid #312e81; color: #e0e7ff; font-size: 13px; }
  .status-icon { font-size: 16px; }
  .chunk-id { font-family: monospace; color: #818cf8; }
  .stage-badge { background: #312e81; color: #c4b5fd; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
  .loading, .empty { text-align: center; padding: 40px; color: #6b7280; }
  .error { color: #f87171; padding: 16px; }
</style>