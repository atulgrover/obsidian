<script lang="ts">
  import { vault } from './api/vault';
  import type { SourceMeta } from './api/vault';
  import PdfViewer from './components/PdfViewer.svelte';
  import ParseTab from './components/ParseTab.svelte';
  import CleanseTab from './components/CleanseTab.svelte';
  import EnrichTab from './components/EnrichTab.svelte';
  import IndexTab from './components/IndexTab.svelte';
  import ChunkTab from './components/ChunkTab.svelte';

  let sources: SourceMeta[] = $state([]);
  let selectedSlug = $state('');
  let activePanel = $state('parse');
  let loading = $state(false);
  let error = $state('');

  // Upload controls
  let pipelineUrl = $state('');
  let pipelineFile: File | null = $state(null);
  let pipelineMode: 'url' | 'file' = $state('file');
  let uploading = $state(false);

  // Processing controls
  let processing = $state(false);
  let processingStage = $state('');
  let processingResult: Record<string, unknown> | null = $state(null);

  // Source data
  let sourceMeta: Record<string, unknown> = $state({});

  const stages = [
    { id: 'parse',    label: 'Parse',    icon: 'P' },
    { id: 'cleanse',  label: 'Cleanse',  icon: 'C' },
    { id: 'enrich',   label: 'Enrich',   icon: 'E' },
    { id: 'index',    label: 'Index',    icon: 'I' },
    { id: 'chunk',    label: 'Chunk',    icon: 'K' },
  ];

  async function loadSources() {
    loading = true;
    try {
      const resp = await vault.listSources();
      sources = resp.sources;
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function selectSource(slug: string) {
    selectedSlug = slug;
    error = '';
    try {
      const src = await vault.getSource(slug);
      sourceMeta = src.metadata;
    } catch (e: any) {
      error = e.message;
    }
  }

  // Step 1: Upload/Download PDF → save to vault → show in viewer
  async function uploadPdf() {
    uploading = true;
    error = '';
    try {
      let result;
      if (pipelineMode === 'file' && pipelineFile) {
        result = await vault.savePdfUpload(pipelineFile);
      } else if (pipelineMode === 'url' && pipelineUrl) {
        result = await vault.savePdfUrl(pipelineUrl);
      } else {
        error = pipelineMode === 'file' ? 'Select a PDF file' : 'Enter a PDF URL';
        return;
      }
      await loadSources();
      if (result.slug) await selectSource(result.slug);
    } catch (e: any) {
      error = e.message;
    } finally {
      uploading = false;
    }
  }

  // Step 2: Process the PDF through the pipeline
  async function processPdf() {
    if (!selectedSlug) return;
    processing = true;
    processingResult = null;
    error = '';

    const stageNames = ['parse', 'cleanse', 'extract', 'index', 'enrich', 'chunk', 'embed', 'karpathy'];

    try {
      const results: Record<string, unknown> = {};

      for (const stage of stageNames) {
        processingStage = stage;
        try {
          const resp = await vault.runStage(stage as any, selectedSlug);
          results[stage] = resp;
          // Refresh source metadata after each stage
          const src = await vault.getSource(selectedSlug);
          sourceMeta = src.metadata;
        } catch (e: any) {
          results[stage] = { error: e.message };
          break; // Stop pipeline on error
        }
      }

      processingResult = results;
      await loadSources();
    } catch (e: any) {
      error = e.message;
    } finally {
      processing = false;
      processingStage = '';
    }
  }

  function handleFileInput(event: Event) {
    const target = event.target as HTMLInputElement;
    if (target.files && target.files.length > 0) {
      pipelineFile = target.files[0];
    }
  }

  function stageColor(stage: string): string {
    const map: Record<string, string> = {
      uploaded: '#6b7280',
      liteparse: '#6366f1', pageindex: '#8b5cf6', semchunk: '#a855f7',
      extracted: '#f59e0b', enriched: '#0ea5e9',
      ingested: '#22c55e', verified: '#16a34a', error: '#ef4444',
    };
    return map[stage] || '#6b7280';
  }

  async function deleteSource(slug: string, e: MouseEvent) {
    e.stopPropagation();
    if (!confirm(`Delete "${slug}" from vault? This cannot be undone.`)) return;
    try {
      await vault.deleteSource(slug);
      if (selectedSlug === slug) { selectedSlug = ''; sourceMeta = {}; }
      await loadSources();
    } catch (err: any) {
      error = err.message;
    }
  }

  async function reingestSource(slug: string, e: MouseEvent) {
    e.stopPropagation();
    await selectSource(slug);
    await processPdf();
  }

  $effect(() => { if (sources.length === 0) loadSources(); });
</script>

<div class="app">
  <!-- Left sidebar -->
  <aside class="sidebar">
    <div class="logo">
      <h1>RAG2</h1>
      <span class="subtitle">Resolution Bazaar</span>
    </div>

    <!-- Upload section -->
    <div class="upload-section">
      <h3>Upload PDF</h3>
      <div class="mode-tabs">
        <button class="mode-tab" class:active={pipelineMode === 'file'} onclick={() => pipelineMode = 'file'}>Local File</button>
        <button class="mode-tab" class:active={pipelineMode === 'url'} onclick={() => pipelineMode = 'url'}>From URL</button>
      </div>
      {#if pipelineMode === 'file'}
        <label class="file-label">
          <input type="file" accept=".pdf" onchange={handleFileInput} />
          {pipelineFile ? pipelineFile.name : 'Choose PDF...'}
        </label>
      {:else}
        <input type="text" bind:value={pipelineUrl} placeholder="https://example.com/document.pdf" />
      {/if}
      <button onclick={uploadPdf} disabled={uploading || (pipelineMode === 'url' ? !pipelineUrl : !pipelineFile)}>
        {uploading ? 'Uploading...' : 'Upload & View'}
      </button>
    </div>

    <!-- Source list -->
    <div class="source-list">
      <div class="source-header">
        <h3>Sources</h3>
        <button class="refresh-btn" onclick={loadSources} disabled={loading}>Refresh</button>
      </div>
      {#if loading}
        <div class="loading-sm">Loading...</div>
      {:else if sources.length === 0}
        <div class="empty-sm">No sources yet.</div>
      {:else}
        {#each sources as src}
          <div
            class="source-item"
            class:selected={selectedSlug === src.slug}
            role="button"
            tabindex="0"
            onclick={() => selectSource(src.slug)}
            onkeydown={(e) => e.key === 'Enter' || e.key === ' ' ? selectSource(src.slug) : null}
          >
            <span class="source-name">{src.filename || src.slug}</span>
            <span class="source-actions">
              <button
                class="icon-btn reingest-btn"
                title="Re-ingest"
                onclick={(e) => reingestSource(src.slug, e)}
                disabled={processing}
              >&#x21BB;</button>
              <button
                class="icon-btn delete-btn"
                title="Delete"
                onclick={(e) => deleteSource(src.slug, e)}
              >&#x2715;</button>
            </span>
          </div>
        {/each}
      {/if}
    </div>
  </aside>

  <!-- Middle: PDF Viewer -->
  <section class="pdf-panel">
    {#if selectedSlug}
      <PdfViewer url={vault.getPdfUrl(selectedSlug)} />
    {:else}
      <div class="pdf-empty">
        <div class="pdf-empty-icon">&#128196;</div>
        <p>Upload a PDF or select a source</p>
      </div>
    {/if}
  </section>

  <!-- Right: Pipeline tabs -->
  <section class="content-panel">
    {#if !selectedSlug}
      <div class="welcome">
        <h2>RAG2 &mdash; Resolution Bazaar</h2>
        <p>Upload a PDF to start the pipeline.</p>
        <div class="pipeline-flow">
          <div class="flow-step"><span class="flow-num">1</span> Parse: PDF &rarr; Text</div>
          <div class="flow-arrow">&rarr;</div>
          <div class="flow-step"><span class="flow-num">2</span> Cleanse: Structure</div>
          <div class="flow-arrow">&rarr;</div>
          <div class="flow-step"><span class="flow-num">3</span> Enrich: Summaries</div>
          <div class="flow-arrow">&rarr;</div>
          <div class="flow-step"><span class="flow-num">4</span> Index: Save</div>
          <div class="flow-arrow">&rarr;</div>
          <div class="flow-step"><span class="flow-num">5</span> Chunk & Embed</div>
        </div>
      </div>
    {:else}
      <!-- Process button + status -->
      <div class="process-bar">
        <div class="process-left">
          <span class="slug-label">{selectedSlug}</span>
          {#if sourceMeta.pipeline_stage && sourceMeta.pipeline_stage !== 'uploaded'}
            <span class="stage-chip" style="background:{stageColor(sourceMeta.pipeline_stage as string)}">{sourceMeta.pipeline_stage}</span>
          {/if}
        </div>
        <div class="process-right">
          {#if processing}
            <span class="processing-label">Processing: {processingStage}...</span>
          {/if}
          <button class="process-btn" onclick={processPdf} disabled={processing || sourceMeta.pipeline_stage === 'ingested'}>
            {#if processing}
              Processing...
            {:else if sourceMeta.pipeline_stage === 'ingested'}
              Completed
            {:else}
              Process
            {/if}
          </button>
        </div>
      </div>

      <div class="tab-bar">
        {#each stages as s}
          <button class="tab" class:active={activePanel === s.id} onclick={() => activePanel = s.id}>
            <span class="tab-icon">{s.icon}</span> {s.label}
          </button>
        {/each}
      </div>
      <div class="panel-content">
        {#if activePanel === 'parse'}
          <ParseTab slug={selectedSlug} />
        {:else if activePanel === 'cleanse'}
          <CleanseTab slug={selectedSlug} />
        {:else if activePanel === 'enrich'}
          <EnrichTab slug={selectedSlug} />
        {:else if activePanel === 'index'}
          <IndexTab slug={selectedSlug} />
        {:else if activePanel === 'chunk'}
          <ChunkTab slug={selectedSlug} />
        {/if}
      </div>
    {/if}
  </section>
</div>

{#if error}
  <button class="error-toast" onclick={() => error = ''}>
    {error}
    <span class="close">&times;</span>
  </button>
{/if}

<style>
  :global(body) { margin: 0; background: #0f0d2e; color: #e0e7ff; font-family: system-ui, -apple-system, sans-serif; }
  :global(*) { box-sizing: border-box; }

  .app { display: flex; height: 100vh; }

  .sidebar {
    width: 280px; min-width: 280px; background: #1a1744; border-right: 1px solid #312e81;
    display: flex; flex-direction: column; overflow-y: auto;
  }
  .logo { padding: 16px; border-bottom: 1px solid #312e81; }
  .logo h1 { margin: 0; font-size: 20px; color: #a78bfa; }
  .logo .subtitle { font-size: 11px; color: #6b7280; }

  .upload-section { padding: 12px; border-bottom: 1px solid #312e81; }
  .upload-section h3 { margin: 0 0 6px; font-size: 12px; color: #818cf8; text-transform: uppercase; }
  .mode-tabs { display: flex; gap: 4px; margin-bottom: 6px; }
  .mode-tab {
    flex: 1; padding: 5px; background: #0f0d2e; border: 1px solid #312e81;
    border-radius: 4px; color: #818cf8; cursor: pointer; font-size: 11px; text-align: center;
  }
  .mode-tab.active { background: #4f46e5; color: white; border-color: #4f46e5; }
  .file-label {
    display: block; padding: 8px 10px; background: #0f0d2e; border: 1px dashed #312e81;
    border-radius: 4px; color: #6b7280; font-size: 12px; text-align: center;
    cursor: pointer; margin-bottom: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .file-label input[type="file"] { display: none; }
  .upload-section input[type="text"] {
    width: 100%; padding: 6px 10px; background: #0f0d2e; border: 1px solid #312e81;
    border-radius: 4px; color: #e0e7ff; font-size: 12px; margin-bottom: 6px;
  }
  .upload-section button {
    width: 100%; padding: 7px; background: #4f46e5; color: white; border: none;
    border-radius: 4px; cursor: pointer; font-size: 12px;
  }
  .upload-section button:disabled { opacity: 0.5; }

  .source-list { flex: 1; overflow-y: auto; }
  .source-header { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; }
  .source-header h3 { margin: 0; font-size: 12px; color: #818cf8; text-transform: uppercase; }
  .refresh-btn { background: transparent; border: 1px solid #312e81; color: #818cf8; padding: 3px 6px; border-radius: 3px; cursor: pointer; font-size: 10px; }

  .source-item {
    display: flex; justify-content: space-between; align-items: center;
    width: 100%; padding: 8px 12px; background: transparent;
    border-bottom: 1px solid #1e1b4b; cursor: pointer; text-align: left; color: #c4b5fd;
  }
  .source-item:hover { background: rgba(79, 70, 229, 0.15); }
  .source-item:hover .source-actions { opacity: 1; }
  .source-item.selected { background: #312e81; }
  .source-name { font-size: 12px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-right: 6px; }
  .source-actions { display: flex; gap: 2px; align-items: center; opacity: 0; transition: opacity 0.15s; flex-shrink: 0; }
  .source-item.selected .source-actions { opacity: 1; }
  .icon-btn {
    background: transparent; border: none; cursor: pointer;
    padding: 2px 5px; border-radius: 3px; font-size: 13px; line-height: 1;
    transition: background 0.15s;
  }
  .reingest-btn { color: #818cf8; }
  .reingest-btn:hover:not(:disabled) { background: rgba(99, 102, 241, 0.2); }
  .reingest-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .delete-btn { color: #f87171; }
  .delete-btn:hover { background: rgba(239, 68, 68, 0.15); }

  .pdf-panel { flex: 1; min-width: 0; border-right: 1px solid #312e81; display: flex; flex-direction: column; }
  .pdf-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: #6b7280; }
  .pdf-empty-icon { font-size: 48px; margin-bottom: 12px; }

  .content-panel { flex: 1; min-width: 0; display: flex; flex-direction: column; }

  .welcome { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; padding: 32px; }
  .welcome h2 { color: #a78bfa; margin-bottom: 8px; }
  .welcome p { color: #6b7280; margin-bottom: 24px; }
  .pipeline-flow { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; justify-content: center; }
  .flow-step { display: flex; align-items: center; gap: 4px; color: #c4b5fd; font-size: 12px; }
  .flow-num { background: #4f46e5; color: white; width: 18px; height: 18px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 10px; }
  .flow-arrow { color: #6b7280; font-size: 14px; }

  .process-bar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 8px 16px; background: #1a1744; border-bottom: 1px solid #312e81; flex-shrink: 0;
  }
  .process-left { display: flex; align-items: center; gap: 8px; }
  .slug-label { font-size: 13px; color: #c4b5fd; font-weight: bold; }
  .stage-chip { padding: 2px 8px; border-radius: 8px; font-size: 10px; color: white; }
  .process-right { display: flex; align-items: center; gap: 8px; }
  .processing-label { font-size: 11px; color: #f59e0b; }
  .process-btn {
    padding: 6px 20px; background: #22c55e; color: white; border: none;
    border-radius: 4px; cursor: pointer; font-size: 13px; font-weight: bold;
  }
  .process-btn:disabled { opacity: 0.5; background: #6b7280; }

  .tab-bar { display: flex; background: #1a1744; border-bottom: 1px solid #312e81; flex-shrink: 0; }
  .tab {
    padding: 8px 14px; background: transparent; border: none; border-bottom: 2px solid transparent;
    cursor: pointer; color: #818cf8; font-size: 13px;
  }
  .tab:hover { background: rgba(79, 70, 229, 0.1); }
  .tab.active { border-bottom-color: #a78bfa; color: white; background: #1e1b4b; }
  .tab-icon { margin-right: 3px; font-size: 11px; }

  .panel-content { flex: 1; overflow-y: auto; }
  .loading-sm, .empty-sm { text-align: center; padding: 12px; color: #6b7280; font-size: 12px; }

  .error-toast {
    position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
    background: #7f1d1d; color: #fca5a5; padding: 10px 20px; border-radius: 6px;
    font-size: 13px; cursor: pointer; z-index: 1000;
    display: flex; align-items: center; gap: 12px;
    border: none; font-family: inherit;
  }
  .close { font-size: 18px; }
</style>