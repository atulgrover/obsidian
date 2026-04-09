<script lang="ts">
  import { marked } from 'marked';

  let { markdown = '', metadata = {} }: { markdown?: string; metadata?: Record<string, unknown> } = $props();

  let renderedHtml = $state('');

  $effect(() => {
    try {
      renderedHtml = marked(markdown || '') as string;
    } catch {
      renderedHtml = `<pre>${markdown}</pre>`;
    }
  });

  function formatMeta(key: string, val: unknown): string {
    if (Array.isArray(val)) return val.join(', ');
    if (typeof val === 'string' && val.startsWith('[[')) return val; // wikilinks
    return String(val ?? '');
  }

  const displayKeys = ['filename', 'total_pages', 'total_chars', 'pipeline_stage', 'doc_type', 'doc_date', 'slug'];
</script>

<div class="md-viewer">
  {#if Object.keys(metadata).length > 0}
    <div class="meta-bar">
      {#each displayKeys as key}
        {#if metadata[key] !== undefined && metadata[key] !== null && metadata[key] !== ''}
          <span class="meta-chip">
            <span class="meta-label">{key.replace(/_/g, ' ')}</span>
            <span class="meta-value">{formatMeta(key, metadata[key])}</span>
          </span>
        {/if}
      {/each}
    </div>
  {/if}
  <div class="md-content">
    {@html renderedHtml}
  </div>
</div>

<style>
  .md-viewer { display: flex; flex-direction: column; height: 100%; background: #0f0d2e; }

  .meta-bar {
    display: flex; flex-wrap: wrap; gap: 6px; padding: 10px 16px;
    background: #1a1744; border-bottom: 1px solid #312e81; flex-shrink: 0;
  }
  .meta-chip {
    display: inline-flex; align-items: center; gap: 4px;
    background: #1e1b4b; border: 1px solid #312e81; border-radius: 4px;
    padding: 3px 8px; font-size: 11px;
  }
  .meta-label { color: #818cf8; }
  .meta-value { color: #e0e7ff; }

  .md-content {
    flex: 1; overflow-y: auto; padding: 20px 24px;
    color: #c4b5fd; line-height: 1.7; font-size: 14px;
  }
  .md-content :global(h1) { color: #a78bfa; font-size: 20px; margin: 20px 0 8px; border-bottom: 1px solid #312e81; padding-bottom: 6px; }
  .md-content :global(h2) { color: #818cf8; font-size: 17px; margin: 16px 0 6px; }
  .md-content :global(h3) { color: #818cf8; font-size: 15px; margin: 12px 0 4px; }
  .md-content :global(p) { margin: 6px 0; }
  .md-content :global(ul), .md-content :global(ol) { padding-left: 20px; margin: 6px 0; }
  .md-content :global(li) { margin: 2px 0; }
  .md-content :global(code) { background: #1e1b4b; padding: 1px 4px; border-radius: 3px; font-size: 13px; }
  .md-content :global(pre) { background: #1e1b4b; padding: 12px; border-radius: 6px; overflow-x: auto; }
  .md-content :global(table) { border-collapse: collapse; width: 100%; margin: 10px 0; }
  .md-content :global(th), .md-content :global(td) { border: 1px solid #312e81; padding: 6px 10px; text-align: left; }
  .md-content :global(th) { background: #1a1744; color: #a78bfa; }
  .md-content :global(blockquote) { border-left: 3px solid #4f46e5; padding-left: 12px; color: #818cf8; margin: 8px 0; }
  .md-content :global(strong) { color: #e0e7ff; }
  .md-content :global(a) { color: #818cf8; text-decoration: underline; }
</style>