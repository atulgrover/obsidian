<script lang="ts">
  import { vault } from '../api/vault';

  let { slug = '' } = $props();

  let sourceData: Record<string, unknown> | null = $state(null);
  let sections: any[] = $state([]);
  let loading = $state(false);
  let error = $state('');
  let expanded: Set<string> = $state(new Set());

  $effect(() => { if (slug) loadEnrichment(); });

  async function loadEnrichment() {
    loading = true;
    error = '';
    try {
      const [src, secs] = await Promise.all([
        vault.getSource(slug),
        vault.listSections(slug),
      ]);
      sourceData = src.metadata;
      sections = secs.sections;
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  function toggle(id: string) {
    const next = new Set(expanded);
    if (next.has(id)) next.delete(id); else next.add(id);
    expanded = next;
  }

  const docMetaKeys = ['doc_type', 'doc_date', 'filename', 'total_pages', 'total_chars', 'pipeline_stage', 'parties', 'statutory_refs'];
</script>

<div class="enrich-tab">
  {#if loading}
    <div class="loading">Loading enrichment data...</div>
  {:else if error}
    <div class="error">{error}</div>
  {:else if !sourceData}
    <div class="empty">Run the pipeline to see enrichment data.</div>
  {:else}
    <div class="section">
      <h3>Document Metadata</h3>
      <div class="meta-grid">
        {#each docMetaKeys as key}
          {#if sourceData[key] !== undefined && sourceData[key] !== null && sourceData[key] !== ''}
            <div class="meta-item">
              <span class="meta-key">{key.replace(/_/g, ' ')}</span>
              <span class="meta-val">{Array.isArray(sourceData[key]) ? (sourceData[key] as any[]).join(', ') : String(sourceData[key])}</span>
            </div>
          {/if}
        {/each}
      </div>
    </div>

    <div class="section">
      <h3>Section Summaries ({sections.length})</h3>
      <div class="sections-list">
        {#each sections as sec}
          <div class="sec-item" role="button" tabindex="0" onclick={() => toggle(sec.filename)} onkeydown={(e) => e.key === 'Enter' || e.key === ' ' ? toggle(sec.filename) : null}>
            <div class="sec-row">
              <span class="sec-toggle">{expanded.has(sec.filename) ? '▼' : '▶'}</span>
              <span class="sec-level">L{sec.level}</span>
              <span class="sec-title">{sec.title}</span>
              <span class="sec-pages">p.{sec.page_start}–{sec.page_end}</span>
              <span class="sec-words">{sec.word_count}w</span>
              {#if sec.is_leaf}
                <span class="leaf-badge">leaf</span>
              {/if}
            </div>
            {#if expanded.has(sec.filename)}
              <div class="sec-body">
                {#if sec.breadcrumb}<div class="breadcrumb">{sec.breadcrumb}</div>{/if}
                {#if sec.llm_summary}<div class="summary">{sec.llm_summary}</div>{:else}<em>No summary yet — run Enrich stage</em>{/if}
              </div>
            {/if}
          </div>
        {/each}
      </div>
    </div>
  {/if}
</div>

<style>
  .enrich-tab { display: flex; flex-direction: column; height: 100%; overflow-y: auto; }
  .section { padding: 12px 16px; border-bottom: 1px solid #1e1b4b; }
  .section h3 { margin: 0 0 8px; font-size: 13px; color: #a78bfa; }

  .meta-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 6px; }
  .meta-item { background: #0f0d2e; border: 1px solid #1e1b4b; border-radius: 4px; padding: 6px 10px; }
  .meta-key { font-size: 10px; color: #6b7280; text-transform: uppercase; display: block; }
  .meta-val { font-size: 12px; color: #e0e7ff; }

  .sec-item { cursor: pointer; }
  .sec-row {
    display: flex; align-items: center; gap: 6px; padding: 5px 8px; font-size: 12px; color: #c4b5fd;
  }
  .sec-row:hover { background: rgba(79, 70, 229, 0.1); }
  .sec-toggle { width: 14px; font-size: 10px; color: #818cf8; }
  .sec-level { background: #312e81; padding: 1px 4px; border-radius: 3px; font-size: 10px; color: #a78bfa; }
  .sec-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sec-pages { color: #6b7280; font-size: 10px; }
  .sec-words { color: #6b7280; font-size: 10px; }
  .leaf-badge { font-size: 9px; background: #1e3a1e; color: #22c55e; padding: 1px 4px; border-radius: 3px; }
  .sec-body { padding: 4px 8px 8px 28px; font-size: 11px; color: #818cf8; }
  .breadcrumb { font-size: 10px; color: #6b7280; margin-bottom: 4px; }
  .summary { color: #c4b5fd; }

  .loading, .error, .empty { padding: 32px; text-align: center; color: #818cf8; }
  .error { color: #ef4444; }
</style>
