<script lang="ts">
  import { vault } from '../api/vault';

  let { slug = '' } = $props();

  let parseData: Record<string, unknown> | null = $state(null);
  let loading = $state(false);
  let error = $state('');
  let viewMode: 'text' | 'markdown' | 'paragraphs' = $state('markdown');

  $effect(() => { if (slug) loadParse(); });

  async function loadParse() {
    loading = true;
    error = '';
    try {
      parseData = await vault.getParse(slug);
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  function getPages(): any[] {
    return (parseData?.pages as any[]) || [];
  }

  function getParagraphs(page: any): any[] {
    return page?.paragraphs || [];
  }

  const meta = $derived(parseData?.metadata as Record<string, number> || {});
</script>

<div class="parse-tab">
  {#if loading}
    <div class="loading">Loading parse data...</div>
  {:else if error}
    <div class="error">{error}</div>
  {:else if !parseData}
    <div class="empty">No parse data. Run the pipeline first.</div>
  {:else}
    <div class="meta-bar">
      <span class="chip">Pages: {meta.totalPages || 0}</span>
      <span class="chip">Chars: {(meta.characterCount || 0).toLocaleString()}</span>
      <span class="chip">Paragraphs: {getPages().reduce((n: number, p: any) => n + (p.paragraphs?.length || 0), 0)}</span>
    </div>

    <div class="view-tabs">
      <button class:active={viewMode === 'text'} onclick={() => viewMode = 'text'}>Raw Text</button>
      <button class:active={viewMode === 'markdown'} onclick={() => viewMode = 'markdown'}>Markdown</button>
      <button class:active={viewMode === 'paragraphs'} onclick={() => viewMode = 'paragraphs'}>Paragraphs</button>
    </div>

    <div class="content">
      {#if viewMode === 'text'}
        <pre class="text-view">{parseData.text || ''}</pre>
      {:else if viewMode === 'markdown'}
        <pre class="text-view">{parseData.markdown || ''}</pre>
      {:else}
        {#each getPages() as page, pi}
          <div class="page-block">
            <div class="page-header">Page {page.pageNum}</div>
            {#each getParagraphs(page) as para, j}
              <div class="para-row" class:heading={para.isHeading} class:footer={para.isFooter} class:list={para.isList} class:table={para.isTable}>
                <span class="para-flags">
                  {para.isHeading ? `<H${para.headingLevel}>` : ''}
                  {para.isFooter ? 'FOOT' : ''}
                  {para.isList ? 'LIST' : ''}
                  {para.isTable ? 'TABLE' : ''}
                </span>
                <span class="para-font">{para.avgFontSize?.toFixed(1) || ''}</span>
                <span class="para-text">{para.text}</span>
              </div>
            {/each}
          </div>
        {/each}
      {/if}
    </div>
  {/if}
</div>

<style>
  .parse-tab { display: flex; flex-direction: column; height: 100%; }
  .meta-bar { display: flex; gap: 6px; padding: 8px 16px; border-bottom: 1px solid #312e81; }
  .chip { background: #1e1b4b; border: 1px solid #312e81; border-radius: 4px; padding: 2px 8px; font-size: 11px; color: #818cf8; }

  .view-tabs { display: flex; gap: 2px; padding: 6px 16px; border-bottom: 1px solid #312e81; }
  .view-tabs button { padding: 4px 12px; border-radius: 4px; border: 1px solid #312e81; background: transparent; color: #818cf8; cursor: pointer; font-size: 12px; }
  .view-tabs button.active { background: #4f46e5; color: white; border-color: #4f46e5; }

  .content { flex: 1; overflow-y: auto; padding: 12px 16px; }
  .text-view { white-space: pre-wrap; font-size: 13px; color: #c4b5fd; line-height: 1.6; margin: 0; }

  .page-block { margin-bottom: 16px; }
  .page-header { font-size: 12px; color: #a78bfa; margin-bottom: 6px; font-weight: bold; }
  .para-row { display: flex; gap: 8px; padding: 3px 0; font-size: 12px; color: #c4b5fd; border-bottom: 1px solid #1e1b4b; }
  .para-row.heading { color: #a78bfa; font-weight: bold; }
  .para-row.footer { color: #6b7280; text-decoration: line-through; }
  .para-flags { min-width: 60px; font-size: 10px; color: #f59e0b; }
  .para-font { min-width: 32px; color: #818cf8; font-size: 10px; }
  .para-text { flex: 1; }

  .loading, .error, .empty { padding: 32px; text-align: center; color: #818cf8; }
  .error { color: #ef4444; }
</style>