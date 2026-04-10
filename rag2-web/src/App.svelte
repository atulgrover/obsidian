<script lang="ts">
  import { vault } from './api/vault';
  import type { SourceMeta } from './api/vault';
  import PdfViewer from './components/PdfViewer.svelte';
  import ParseTab from './components/ParseTab.svelte';
  import CleanseTab from './components/CleanseTab.svelte';
  import EnrichTab from './components/EnrichTab.svelte';
  import IndexTab from './components/IndexTab.svelte';
  import ChunkTab from './components/ChunkTab.svelte';

  type Pane = 'sources' | 'document' | 'pipeline';
  type TabId = 'parse' | 'cleanse' | 'enrich' | 'chunk' | 'index';
  type StepState = 'pending' | 'running' | 'done' | 'failed';
  type ThemeMode = 'dark' | 'light';

  let sources: SourceMeta[] = $state([]);
  let selectedSlug = $state('');
  let activePanel: TabId = $state('parse');
  let activePane: Pane = $state('sources');
  let loading = $state(false);
  let error = $state('');
  let showAdvanced = $state(false);
  let theme: ThemeMode = $state('dark');

  let pipelineUrl = $state('');
  let pipelineFile: File | null = $state(null);
  let pipelineMode: 'url' | 'file' = $state('file');
  let uploading = $state(false);

  let processing = $state(false);
  let processingStage = $state('');
  let processingResult: Record<string, unknown> | null = $state(null);

  let sourceMeta: Record<string, unknown> = $state({});

  const stageSequence = [
    { id: 'parse', label: 'Parse', short: 'P' },
    { id: 'cleanse', label: 'Cleanse', short: 'C' },
    { id: 'extract', label: 'Extract', short: 'X' },
    { id: 'index', label: 'Index', short: 'I' },
    { id: 'enrich', label: 'Enrich', short: 'E' },
    { id: 'chunk', label: 'Chunk', short: 'K' },
    { id: 'embed', label: 'Embed', short: 'B' },
    { id: 'karpathy', label: 'Karpathy', short: 'R' },
  ] as const;

  const tabs: Array<{ id: TabId; label: string; advanced?: boolean }> = [
    { id: 'parse', label: 'Parse' },
    { id: 'cleanse', label: 'Structure' },
    { id: 'enrich', label: 'Enrichment' },
    { id: 'chunk', label: 'Chunks' },
    { id: 'index', label: 'Vault', advanced: true },
  ];

  const stageRank: Record<string, number> = {
    uploaded: 0,
    liteparse: 1,
    pageindex: 2,
    extracted: 3,
    indexed: 4,
    enriched: 5,
    semchunk: 6,
    ingested: 7,
    verified: 8,
  };

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
      activePane = 'document';
    } catch (e: any) {
      error = e.message;
    }
  }

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

  async function processPdf() {
    if (!selectedSlug) return;
    processing = true;
    processingResult = null;
    error = '';
    activePane = 'pipeline';

    try {
      const results: Record<string, unknown> = {};

      for (const stage of stageSequence) {
        processingStage = stage.id;
        try {
          const resp = await vault.runStage(stage.id, selectedSlug);
          results[stage.id] = resp;
          const src = await vault.getSource(selectedSlug);
          sourceMeta = src.metadata;
        } catch (e: any) {
          results[stage.id] = { error: e.message };
          break;
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
      uploaded: '#64748b',
      liteparse: '#2563eb',
      pageindex: '#7c3aed',
      extracted: '#ea580c',
      indexed: '#0ea5e9',
      enriched: '#0891b2',
      semchunk: '#8b5cf6',
      ingested: '#16a34a',
      verified: '#15803d',
      error: '#dc2626',
    };
    return map[stage] || '#475569';
  }

  function stageLabel(stage: string): string {
    const map: Record<string, string> = {
      uploaded: 'Uploaded',
      liteparse: 'Parsed',
      pageindex: 'Structured',
      extracted: 'Extracted',
      indexed: 'Indexed',
      enriched: 'Enriched',
      semchunk: 'Chunked',
      ingested: 'Embedded',
      verified: 'Verified',
      error: 'Error',
    };
    return map[stage] || stage || 'Unknown';
  }

  function createdAtLabel(value: string): string {
    if (!value) return 'No timestamp';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  }

  function inferStepState(stage: string): StepState {
    const result = processingResult?.[stage] as Record<string, unknown> | undefined;
    if (result?.error) return 'failed';
    if (processing && processingStage === stage) return 'running';
    if (result) return 'done';

    const currentStage = String(sourceMeta.pipeline_stage || '');
    const currentRank = stageRank[currentStage] || 0;
    const stagePosition = stageSequence.findIndex((item) => item.id === stage) + 1;
    if (!processing && currentRank >= stagePosition) return 'done';
    return 'pending';
  }

  function stepMessage(stage: string): string {
    const result = processingResult?.[stage] as Record<string, unknown> | undefined;
    if (result?.error) return String(result.error);
    const state = inferStepState(stage);
    if (state === 'running') return 'In progress';
    if (state === 'done') return 'Completed';
    return 'Waiting';
  }

  function visibleTabs() {
    return tabs.filter((tab) => showAdvanced || !tab.advanced);
  }

  async function deleteSource(slug: string, e: MouseEvent) {
    e.stopPropagation();
    if (!confirm(`Delete "${slug}" from vault? This cannot be undone.`)) return;
    try {
      await vault.deleteSource(slug);
      if (selectedSlug === slug) {
        selectedSlug = '';
        sourceMeta = {};
        activePane = 'sources';
      }
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

  function toggleAdvanced() {
    showAdvanced = !showAdvanced;
    if (!showAdvanced && activePanel === 'index') activePanel = 'parse';
  }

  function toggleTheme() {
    theme = theme === 'dark' ? 'light' : 'dark';
  }

  $effect(() => {
    if (sources.length === 0) loadSources();
  });

  $effect(() => {
    if (typeof window === 'undefined') return;
    const saved = window.localStorage.getItem('rag2-theme') as ThemeMode | null;
    if (saved === 'dark' || saved === 'light') {
      theme = saved;
      return;
    }
    theme = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  });

  $effect(() => {
    if (typeof document === 'undefined') return;
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem('rag2-theme', theme);
  });
</script>

<div class="mobile-nav">
  <button class:active={activePane === 'sources'} onclick={() => activePane = 'sources'}>Sources</button>
  <button class:active={activePane === 'document'} onclick={() => activePane = 'document'} disabled={!selectedSlug}>Document</button>
  <button class:active={activePane === 'pipeline'} onclick={() => activePane = 'pipeline'} disabled={!selectedSlug}>Pipeline</button>
</div>

<div class="app">
  <aside class="sidebar" class:mobile-hidden={activePane !== 'sources'}>
    <div class="logo">
      <div class="logo-row">
        <div>
          <h1>RAG2</h1>
          <span class="subtitle">Resolution Bazaar</span>
        </div>
        <button class="theme-toggle" onclick={toggleTheme}>
          {theme === 'dark' ? 'Light' : 'Dark'}
        </button>
      </div>
    </div>

    <div class="upload-section">
      <h3>Add Document</h3>
      <div class="mode-tabs">
        <button class="mode-tab" class:active={pipelineMode === 'file'} onclick={() => pipelineMode = 'file'}>Local File</button>
        <button class="mode-tab" class:active={pipelineMode === 'url'} onclick={() => pipelineMode = 'url'}>From URL</button>
      </div>
      {#if pipelineMode === 'file'}
        <label class="file-label">
          <input type="file" accept=".pdf" onchange={handleFileInput} />
          {pipelineFile ? pipelineFile.name : 'Choose a PDF to inspect'}
        </label>
      {:else}
        <input type="text" bind:value={pipelineUrl} placeholder="https://example.com/document.pdf" />
      {/if}
      <button class="upload-btn" onclick={uploadPdf} disabled={uploading || (pipelineMode === 'url' ? !pipelineUrl : !pipelineFile)}>
        {uploading ? 'Uploading...' : 'Add To Workspace'}
      </button>
    </div>

    <div class="source-list">
      <div class="source-header">
        <h3>Workspace</h3>
        <button class="refresh-btn" onclick={loadSources} disabled={loading}>Refresh</button>
      </div>

      {#if loading}
        <div class="loading-sm">Loading documents...</div>
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
            <div class="source-main">
              <div class="source-topline">
                <span class="source-name">{src.filename || src.slug}</span>
                <span class="source-stage" style="background:{stageColor(src.pipeline_stage)}">{stageLabel(src.pipeline_stage)}</span>
              </div>
              <div class="source-meta">
                <span>{src.total_pages || 0} pages</span>
                <span>{(src.total_chars || 0).toLocaleString()} chars</span>
                <span>{createdAtLabel(src.created_at)}</span>
              </div>
            </div>
            <div class="source-actions">
              <button
                class="icon-btn reingest-btn"
                title="Re-run pipeline"
                onclick={(e) => reingestSource(src.slug, e)}
                disabled={processing}
              >&#x21BB;</button>
              <button
                class="icon-btn delete-btn"
                title="Delete"
                onclick={(e) => deleteSource(src.slug, e)}
              >&#x2715;</button>
            </div>
          </div>
        {/each}
      {/if}
    </div>
  </aside>

  <section class="pdf-panel" class:mobile-hidden={activePane !== 'document'}>
    {#if selectedSlug}
      <PdfViewer url={vault.getPdfUrl(selectedSlug)} />
    {:else}
      <div class="panel-empty">
        <div class="panel-empty-icon">&#128196;</div>
        <p>Select a document to preview it.</p>
      </div>
    {/if}
  </section>

  <section class="content-panel" class:mobile-hidden={activePane !== 'pipeline'}>
    {#if !selectedSlug}
      <div class="welcome">
        <h2>Document Pipeline</h2>
        <p>Add a PDF, select it from the workspace, then run the processing stages.</p>
      </div>
    {:else}
      <div class="pipeline-header">
        <div class="pipeline-header-main">
          <div class="pipeline-title-row">
            <h2>{selectedSlug}</h2>
            <span class="stage-chip" style="background:{stageColor(String(sourceMeta.pipeline_stage || 'uploaded'))}">
              {stageLabel(String(sourceMeta.pipeline_stage || 'uploaded'))}
            </span>
          </div>
          <p>Track processing, inspect structure, and review chunk quality from one panel.</p>
        </div>
        <div class="pipeline-header-actions">
          {#if processing}
            <span class="processing-label">Running {processingStage}...</span>
          {/if}
          <button class="process-btn" onclick={processPdf} disabled={processing || sourceMeta.pipeline_stage === 'ingested'}>
            {#if processing}
              Processing...
            {:else if sourceMeta.pipeline_stage === 'ingested'}
              Completed
            {:else}
              Run Pipeline
            {/if}
          </button>
        </div>
      </div>

      <div class="stepper-card">
        <div class="stepper-header">
          <h3>Pipeline Progress</h3>
          <button class="advanced-toggle" onclick={toggleAdvanced}>
            {showAdvanced ? 'Hide Vault Debug' : 'Show Vault Debug'}
          </button>
        </div>
        <div class="stepper-grid">
          {#each stageSequence as stage, index}
            <div class={`step-card state-${inferStepState(stage.id)}`}>
              <div class="step-card-top">
                <span class="step-index">{index + 1}</span>
                <span class="step-short">{stage.short}</span>
              </div>
              <div class="step-name">{stage.label}</div>
              <div class="step-message">{stepMessage(stage.id)}</div>
            </div>
          {/each}
        </div>
      </div>

      <div class="tab-bar">
        {#each visibleTabs() as tab}
          <button class="tab" class:active={activePanel === tab.id} onclick={() => activePanel = tab.id}>
            {tab.label}
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
        {:else if activePanel === 'chunk'}
          <ChunkTab slug={selectedSlug} />
        {:else if activePanel === 'index'}
          <IndexTab slug={selectedSlug} />
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
  :global(body) { margin: 0; color: var(--text); font-family: var(--font-ui); }
  :global(*) { box-sizing: border-box; }

  .mobile-nav {
    display: none;
    gap: 8px;
    padding: 12px;
    background: var(--bg-panel-strong);
    border-bottom: 1px solid var(--border);
  }
  .mobile-nav button {
    flex: 1;
    padding: 10px 12px;
    border: 1px solid var(--border-strong);
    border-radius: 999px;
    background: var(--bg-card-soft);
    color: var(--text);
    font-size: 12px;
  }
  .mobile-nav button.active {
    background: linear-gradient(135deg, var(--accent), var(--accent-strong));
    border-color: transparent;
    color: white;
  }
  .mobile-nav button:disabled { opacity: 0.45; }

  .app {
    display: flex;
    height: 100vh;
    background:
      var(--bg-app);
  }

  .sidebar {
    width: 360px;
    min-width: 360px;
    background: var(--bg-panel-strong);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    overflow-y: auto;
  }

  .logo {
    padding: 22px 20px 18px;
    border-bottom: 1px solid var(--border);
  }
  .logo-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
  }
  .logo h1 {
    margin: 0;
    font-size: 24px;
    color: var(--text-strong);
    letter-spacing: 0.05em;
  }
  .logo .subtitle {
    display: inline-block;
    margin-top: 6px;
    font-size: 11px;
    color: var(--accent-soft);
    text-transform: uppercase;
    letter-spacing: 0.18em;
  }
  .theme-toggle {
    padding: 8px 11px;
    border: 1px solid var(--border-strong);
    border-radius: 999px;
    background: var(--bg-card-soft);
    color: var(--text);
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  .upload-section {
    padding: 16px 20px 18px;
    border-bottom: 1px solid var(--border);
  }
  .upload-section h3 {
    margin: 0 0 10px;
    font-size: 12px;
    color: var(--accent-soft);
    text-transform: uppercase;
    letter-spacing: 0.12em;
  }
  .mode-tabs {
    display: flex;
    gap: 6px;
    margin-bottom: 10px;
  }
  .mode-tab {
    flex: 1;
    padding: 8px 10px;
    background: var(--bg-card-deep);
    border: 1px solid var(--border-strong);
    border-radius: 999px;
    color: var(--text);
    font-size: 12px;
  }
  .mode-tab.active {
    background: linear-gradient(135deg, var(--accent), var(--accent-strong));
    border-color: transparent;
    color: white;
  }
  .file-label {
    display: block;
    padding: 14px 12px;
    margin-bottom: 10px;
    background: var(--bg-card-deep);
    border: 1px dashed var(--border-soft);
    border-radius: 16px;
    color: var(--text-muted);
    font-size: 12px;
    text-align: center;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .file-label input[type="file"] { display: none; }
  .upload-section input[type="text"] {
    width: 100%;
    padding: 12px 14px;
    margin-bottom: 10px;
    background: var(--bg-card-deep);
    border: 1px solid var(--border-strong);
    border-radius: 16px;
    color: var(--text);
    font-size: 13px;
  }
  .upload-btn {
    width: 100%;
    padding: 11px 14px;
    background: linear-gradient(135deg, #f97316, #ea580c);
    color: white;
    border: none;
    border-radius: 16px;
    font-size: 13px;
    font-weight: 800;
  }
  .upload-btn:disabled { opacity: 0.5; }

  .source-list {
    flex: 1;
    overflow-y: auto;
    padding-bottom: 14px;
  }
  .source-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 14px 20px 12px;
  }
  .source-header h3 {
    margin: 0;
    font-size: 12px;
    color: var(--accent-soft);
    text-transform: uppercase;
    letter-spacing: 0.12em;
  }
  .refresh-btn {
    padding: 5px 10px;
    border: 1px solid var(--border-soft);
    border-radius: 999px;
    background: transparent;
    color: var(--text);
    font-size: 11px;
  }

  .source-item {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    margin: 0 14px 10px;
    padding: 14px;
    background: var(--bg-card);
    border: 1px solid var(--border-strong);
    border-radius: 20px;
    cursor: pointer;
  }
  .source-item:hover {
    border-color: var(--accent-soft);
    transform: translateY(-1px);
  }
  .source-item.selected {
    background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 14%, transparent), color-mix(in srgb, var(--accent-strong) 10%, transparent));
    border-color: var(--accent-soft);
  }
  .source-main {
    flex: 1;
    min-width: 0;
  }
  .source-topline {
    display: flex;
    align-items: center;
    gap: 8px;
    justify-content: space-between;
    margin-bottom: 8px;
  }
  .source-name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 14px;
    font-weight: 700;
    color: var(--text-strong);
  }
  .source-stage {
    padding: 4px 9px;
    border-radius: 999px;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: white;
    flex-shrink: 0;
  }
  .source-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    font-size: 11px;
    color: var(--text-muted);
  }
  .source-actions {
    display: flex;
    gap: 4px;
    flex-shrink: 0;
  }
  .icon-btn {
    padding: 7px 9px;
    border: 1px solid var(--border-soft);
    border-radius: 10px;
    background: var(--bg-card-deep);
    line-height: 1;
  }
  .reingest-btn { color: var(--accent-soft); }
  .delete-btn { color: #fb7185; }
  .reingest-btn:disabled { opacity: 0.4; }

  .pdf-panel {
    flex: 1.08;
    min-width: 0;
    display: flex;
    flex-direction: column;
    border-right: 1px solid var(--border);
    background: var(--bg-canvas);
  }

  .content-panel {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    background: var(--bg-panel);
  }

  .welcome,
  .panel-empty {
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 32px;
    color: var(--text-muted);
    text-align: center;
  }
  .welcome h2 {
    margin: 0 0 8px;
    font-size: 30px;
    color: var(--text-strong);
  }
  .panel-empty-icon {
    font-size: 46px;
    margin-bottom: 14px;
  }

  .pipeline-header {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    padding: 22px 22px 16px;
    border-bottom: 1px solid var(--border);
  }
  .pipeline-header-main h2 {
    margin: 0;
    font-size: 24px;
    color: var(--text-strong);
  }
  .pipeline-header-main p {
    margin: 8px 0 0;
    color: var(--text-muted);
    font-size: 13px;
  }
  .pipeline-title-row {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }
  .stage-chip {
    padding: 5px 10px;
    border-radius: 999px;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: white;
  }
  .pipeline-header-actions {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  .processing-label {
    font-size: 11px;
    color: var(--warning);
  }
  .process-btn {
    padding: 10px 16px;
    border: none;
    border-radius: 14px;
    background: linear-gradient(135deg, #22c55e, var(--success));
    color: white;
    font-size: 13px;
    font-weight: 800;
  }
  .process-btn:disabled { opacity: 0.5; }

  .stepper-card {
    padding: 16px 22px 18px;
    border-bottom: 1px solid var(--border);
  }
  .stepper-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    margin-bottom: 12px;
  }
  .stepper-header h3 {
    margin: 0;
    font-size: 12px;
    color: var(--accent-soft);
    text-transform: uppercase;
    letter-spacing: 0.12em;
  }
  .advanced-toggle {
    padding: 6px 11px;
    border: 1px solid var(--border-soft);
    border-radius: 999px;
    background: transparent;
    color: var(--text);
    font-size: 11px;
  }
  .stepper-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
  }
  .step-card {
    min-height: 98px;
    padding: 12px;
    border: 1px solid var(--border-strong);
    border-radius: 18px;
    background: var(--bg-card);
  }
  .step-card-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 14px;
  }
  .step-index,
  .step-short {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: 800;
  }
  .step-index {
    background: color-mix(in srgb, var(--text-faint) 25%, transparent);
    color: var(--text);
  }
  .step-short {
    background: color-mix(in srgb, var(--text-strong) 10%, transparent);
    color: var(--text-strong);
  }
  .step-name {
    margin-bottom: 6px;
    font-size: 14px;
    font-weight: 700;
    color: var(--text-strong);
  }
  .step-message {
    font-size: 11px;
    color: var(--text-muted);
    line-height: 1.4;
  }
  .step-card.state-done {
    border-color: color-mix(in srgb, var(--success) 50%, transparent);
    background: color-mix(in srgb, var(--success) 16%, var(--bg-card));
  }
  .step-card.state-done .step-index {
    background: #22c55e;
    color: white;
  }
  .step-card.state-running {
    border-color: color-mix(in srgb, var(--accent) 55%, transparent);
    background: color-mix(in srgb, var(--accent) 15%, var(--bg-card));
  }
  .step-card.state-running .step-index {
    background: var(--accent);
    color: white;
  }
  .step-card.state-failed {
    border-color: color-mix(in srgb, var(--danger) 55%, transparent);
    background: color-mix(in srgb, var(--danger) 12%, var(--bg-card));
  }
  .step-card.state-failed .step-index {
    background: var(--danger);
    color: white;
  }

  .tab-bar {
    display: flex;
    gap: 8px;
    padding: 12px 22px;
    border-bottom: 1px solid var(--border);
    overflow-x: auto;
  }
  .tab {
    padding: 9px 14px;
    border: 1px solid var(--border-strong);
    border-radius: 999px;
    background: var(--bg-card-soft);
    color: var(--text);
    font-size: 13px;
  }
  .tab.active {
    background: linear-gradient(135deg, var(--accent), var(--accent-strong));
    border-color: transparent;
    color: white;
  }

  .panel-content {
    flex: 1;
    overflow-y: auto;
  }

  .loading-sm,
  .empty-sm {
    padding: 16px 20px;
    color: var(--text-faint);
    font-size: 12px;
  }

  .error-toast {
    position: fixed;
    left: 50%;
    bottom: 20px;
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 16px;
    border: none;
    border-radius: 12px;
    background: color-mix(in srgb, var(--danger) 75%, #111827);
    color: #fecaca;
    font-size: 13px;
    z-index: 1000;
  }
  .close { font-size: 18px; }

  @media (max-width: 1200px) {
    .stepper-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @media (max-width: 960px) {
    .mobile-nav { display: flex; }
    .app {
      display: block;
      height: calc(100vh - 61px);
    }
    .sidebar,
    .pdf-panel,
    .content-panel {
      width: 100%;
      min-width: 0;
      height: 100%;
      border-right: none;
    }
    .mobile-hidden { display: none; }
    .pipeline-header {
      flex-direction: column;
      align-items: stretch;
    }
    .stepper-card,
    .tab-bar {
      padding-left: 14px;
      padding-right: 14px;
    }
    .stepper-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
