<script lang="ts">
  import { vault } from '../api/vault';
  import type { SourceMeta, SectionMeta, VaultNote } from '../api/vault';

  export let slug = '';

  let source: { slug: string; metadata: Record<string, unknown>; body: string; sections_count: number } | null = null;
  let sections: SectionMeta[] = [];
  let fullText = '';
  let activeTab = 'tree'; // tree | text | metadata
  let loading = false;
  let error = '';
  let expandedSections = new Set<string>();

  $: if (slug) loadSource();

  async function loadSource() {
    loading = true;
    error = '';
    try {
      source = await vault.getSource(slug);
      const secResp = await vault.listSections(slug);
      sections = secResp.sections;
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function loadFullText() {
    try {
      const note = await vault.getSection(slug, 'full-text');
      // full-text is stored as sources/{slug}/full-text.md, not in sections/
      const resp = await fetch(`${import.meta.env.VITE_VAULT_URL || 'http://localhost:5004'}/vault/sources/${slug}/full-text.md`);
      if (resp.ok) fullText = await resp.text();
    } catch { fullText = ''; }
  }

  function toggleSection(id: string) {
    if (expandedSections.has(id)) expandedSections.delete(id);
    else expandedSections.add(id);
    expandedSections = expandedSections; // trigger reactivity
  }

  function stageBadge(stage: string) {
    const colors: Record<string, string> = {
      liteparse: '#6366f1', pageindex: '#8b5cf6', semchunk: '#a855f7',
      ingested: '#22c55e', verified: '#16a34a', error: '#ef4444',
    };
    return colors[stage] || '#6b7280';
  }
</script>

<div class="source-viewer">
  {#if loading}
    <div class="loading">Loading source document...</div>
  {:else if error}
    <div class="error">{error}</div>
  {:else if source}
    <!-- Header -->
    <div class="header">
      <h2>{source.metadata.filename || slug}</h2>
      <div class="badges">
        <span class="badge" style="background:{stageBadge(source.metadata.pipeline_stage as string || '')}">
          {source.metadata.pipeline_stage || 'unknown'}
        </span>
        <span class="badge gray">{source.metadata.total_pages || 0} pages</span>
        <span class="badge gray">{(source.metadata.total_chars || 0).toLocaleString()} chars</span>
        <span class="badge gray">{sections.length} sections</span>
      </div>
    </div>

    <!-- Tab bar -->
    <div class="tabs">
      <button class:active={activeTab === 'tree'} on:click={() => { activeTab = 'tree'; }}>Tree</button>
      <button class:active={activeTab === 'text'} on:click={() => { activeTab = 'text'; loadFullText(); }}>Full Text</button>
      <button class:active={activeTab === 'metadata'} on:click={() => activeTab = 'metadata'}>Metadata</button>
    </div>

    <!-- Tree tab -->
    {#if activeTab === 'tree'}
      <div class="tree">
        {#each sections as sec}
          <div class="section-item" style="padding-left: {sec.level * 20}px">
            <button class="toggle" on:click={() => toggleSection(sec.filename)}>
              {#if expandedSections.has(sec.filename)}▼{:else}▶{/if}
            </button>
            <span class="sec-level">L{sec.level}</span>
            <span class="sec-title">{sec.title || sec.filename}</span>
            <span class="sec-meta">pp.{sec.page_start}-{sec.page_end} · {sec.word_count}w</span>
            {#if sec.is_leaf}<span class="leaf-badge">leaf</span>{/if}
          </div>
        {/each}
      </div>
    {/if}

    <!-- Full text tab -->
    {#if activeTab === 'text'}
      <div class="full-text">
        <pre>{fullText || 'Loading...'}</pre>
      </div>
    {/if}

    <!-- Metadata tab -->
    {#if activeTab === 'metadata'}
      <div class="metadata-grid">
        {#each Object.entries(source.metadata) as [key, val]}
          <div class="meta-row">
            <span class="meta-key">{key}</span>
            <span class="meta-val">{typeof val === 'object' ? JSON.stringify(val) : String(val)}</span>
          </div>
        {/each}
      </div>
    {/if}
  {:else}
    <div class="empty">Select a source document to view</div>
  {/if}
</div>

<style>
  .source-viewer { font-family: system-ui, sans-serif; }
  .header { background: linear-gradient(135deg, #7c3aed, #6d28d9); color: white; padding: 16px 20px; border-radius: 8px 8px 0 0; }
  .header h2 { margin: 0 0 8px; font-size: 18px; }
  .badges { display: flex; gap: 8px; flex-wrap: wrap; }
  .badge { padding: 2px 10px; border-radius: 12px; font-size: 12px; color: white; }
  .badge.gray { background: rgba(255,255,255,0.2); }
  .tabs { display: flex; gap: 0; background: #1e1b4b; }
  .tabs button { padding: 10px 20px; background: transparent; color: #c4b5fd; border: none; cursor: pointer; font-size: 14px; }
  .tabs button.active { background: #312e81; color: white; border-bottom: 2px solid #a78bfa; }
  .tree { padding: 12px; max-height: 500px; overflow-y: auto; }
  .section-item { display: flex; align-items: center; gap: 6px; padding: 6px 0; border-bottom: 1px solid #1e1b4b; }
  .toggle { background: none; border: none; cursor: pointer; color: #818cf8; font-size: 10px; width: 16px; }
  .sec-level { background: #312e81; color: #a78bfa; padding: 1px 6px; border-radius: 4px; font-size: 11px; }
  .sec-title { flex: 1; font-size: 14px; color: #e0e7ff; }
  .sec-meta { font-size: 11px; color: #6b7280; }
  .leaf-badge { background: #065f46; color: #34d399; padding: 1px 6px; border-radius: 4px; font-size: 10px; }
  .full-text { padding: 16px; max-height: 500px; overflow-y: auto; }
  .full-text pre { white-space: pre-wrap; font-size: 13px; color: #e0e7ff; line-height: 1.6; }
  .metadata-grid { padding: 16px; }
  .meta-row { display: flex; gap: 12px; padding: 6px 0; border-bottom: 1px solid #1e1b4b; }
  .meta-key { font-weight: 600; color: #a78bfa; min-width: 140px; font-size: 13px; }
  .meta-val { color: #e0e7ff; font-size: 13px; word-break: break-all; }
  .loading, .empty { text-align: center; padding: 40px; color: #6b7280; }
  .error { color: #f87171; padding: 16px; }
</style>