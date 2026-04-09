<script lang="ts">
  import { vault } from '../api/vault';

  let { slug = '' } = $props();

  let files: { name: string; size: number; type: string }[] = $state([]);
  let loading = $state(false);
  let error = $state('');
  let saving = $state(false);
  let saveResult = $state('');
  let indexMeta: Record<string, unknown> | null = $state(null);

  $effect(() => { if (slug) loadIndex(); });

  async function loadIndex() {
    loading = true;
    error = '';
    try {
      const src = await vault.getSource(slug);
      indexMeta = src.metadata;
      // Build file list from known vault structure
      files = [
        { name: '_index.md', size: 0, type: 'root' },
        { name: 'full-text.md', size: 0, type: 'text' },
        { name: '_parse.json', size: 0, type: 'cache' },
        { name: '_tree.json', size: 0, type: 'cache' },
      ];
      if (src.sections_count) {
        files.push({ name: `sections/ (${src.sections_count} files)`, size: 0, type: 'section' });
      }
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function runIndex() {
    saving = true;
    saveResult = '';
    try {
      const result = await vault.runStage('index', slug);
      saveResult = `Saved ${result.sections || 0} sections to vault`;
      await loadIndex();
    } catch (e: any) {
      saveResult = `Error: ${e.message}`;
    } finally {
      saving = false;
    }
  }

  function stageIcon(type: string): string {
    const map: Record<string, string> = { root: 'R', text: 'T', cache: 'C', section: 'S', pdf: 'P' };
    return map[type] || '?';
  }

  const displayMeta = ['filename', 'pipeline_stage', 'doc_type', 'doc_date', 'total_pages', 'total_chars'];
</script>

<div class="index-tab">
  {#if loading}
    <div class="loading">Loading index data...</div>
  {:else if error}
    <div class="error">{error}</div>
  {:else if !indexMeta}
    <div class="empty">Run the pipeline to see index data.</div>
  {:else}
    <div class="section">
      <h3>Vault Files</h3>
      <div class="file-list">
        {#each files as f}
          <div class="file-row">
            <span class="file-type">{stageIcon(f.type)}</span>
            <span class="file-name">{f.name}</span>
          </div>
        {/each}
      </div>
      <button class="save-btn" onclick={runIndex} disabled={saving}>
        {saving ? 'Saving...' : 'Re-save to Vault'}
      </button>
      {#if saveResult}
        <div class="save-result">{saveResult}</div>
      {/if}
    </div>

    <div class="section">
      <h3>Document Metadata</h3>
      <div class="meta-grid">
        {#each displayMeta as key}
          {#if indexMeta[key] !== undefined && indexMeta[key] !== null && indexMeta[key] !== ''}
            <div class="meta-item">
              <span class="meta-key">{key.replace(/_/g, ' ')}</span>
              <span class="meta-val">{String(indexMeta[key])}</span>
            </div>
          {/if}
        {/each}
      </div>
    </div>

    <div class="section">
      <h3>Frontmatter Preview</h3>
      <pre class="frontmatter">---
{#each Object.entries(indexMeta) as [k, v]}
{#if v !== null && v !== undefined && v !== ''}
{k}: {Array.isArray(v) ? v.join(', ') : v}{/if}
{/each}
---</pre>
    </div>
  {/if}
</div>

<style>
  .index-tab { display: flex; flex-direction: column; height: 100%; overflow-y: auto; }
  .section { padding: 12px 16px; border-bottom: 1px solid #1e1b4b; }
  .section h3 { margin: 0 0 8px; font-size: 13px; color: #a78bfa; }

  .file-list { margin-bottom: 10px; }
  .file-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 12px; color: #c4b5fd; }
  .file-type { width: 20px; height: 20px; border-radius: 3px; background: #1e1b4b; display: flex; align-items: center; justify-content: center; font-size: 10px; color: #818cf8; }
  .file-name { flex: 1; }

  .save-btn {
    width: 100%; padding: 8px; background: #22c55e; color: white; border: none;
    border-radius: 6px; cursor: pointer; font-size: 13px; margin-top: 8px;
  }
  .save-btn:disabled { opacity: 0.5; }
  .save-result { margin-top: 6px; font-size: 12px; color: #22c55e; }

  .meta-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 6px; }
  .meta-item { background: #0f0d2e; border: 1px solid #1e1b4b; border-radius: 4px; padding: 6px 10px; }
  .meta-key { font-size: 10px; color: #6b7280; text-transform: uppercase; display: block; }
  .meta-val { font-size: 12px; color: #e0e7ff; }

  .frontmatter { background: #0a0a1a; padding: 12px; border-radius: 6px; font-size: 11px; color: #818cf8; overflow-x: auto; white-space: pre-wrap; }

  .loading, .error, .empty { padding: 32px; text-align: center; color: #818cf8; }
  .error { color: #ef4444; }
</style>