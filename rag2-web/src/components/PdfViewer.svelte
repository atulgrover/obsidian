<script lang="ts">
  let { url = '' }: { url?: string } = $props();
  let annotations: { page: number; x: number; y: number; text: string; color?: string }[] = $state([]);

  let showIframe = $state(true);
  let annoMode = $state(false);
  let annoText = $state('');
  let annoColor = $state('#ef4444');
  let pendingPoint: { x: number; y: number } | null = $state(null);

  const colors = ['#ef4444', '#f59e0b', '#22c55e', '#3b82f6', '#8b5cf6'];

  function removeAnno(index: number) {
    annotations = annotations.filter((_, i) => i !== index);
  }

  function startAnnotate() {
    annoMode = true;
  }

  function cancelAnnotate() {
    annoMode = false;
    pendingPoint = null;
    annoText = '';
  }

  function handleCanvasClick(e: MouseEvent) {
    if (!annoMode) return;
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    pendingPoint = {
      x: ((e.clientX - rect.left) / rect.width) * 100,
      y: ((e.clientY - rect.top) / rect.height) * 100,
    };
  }

  function saveAnnotation() {
    if (!pendingPoint || !annoText.trim()) return;
    annotations = [...annotations, {
      page: 1,
      x: pendingPoint.x,
      y: pendingPoint.y,
      text: annoText.trim(),
      color: annoColor,
    }];
    pendingPoint = null;
    annoText = '';
    annoMode = false;
  }
</script>

<div class="pdf-viewer">
  {#if !url}
    <div class="pdf-empty">
      <div class="pdf-empty-icon">&#128196;</div>
      <p>Upload a PDF or select a source to view it</p>
    </div>
  {:else}
    <div class="pdf-toolbar">
      <div class="pdf-toolbar-left">
        <button class="tool-btn" class:active={showIframe} onclick={() => showIframe = true}>View</button>
        <button class="tool-btn" class:active={!showIframe} onclick={() => showIframe = false}>Annotate</button>
      </div>
      {#if !showIframe}
        <div class="pdf-toolbar-center">
          {#if !annoMode}
            <button class="anno-btn" onclick={startAnnotate}>+ Add Note</button>
          {:else if pendingPoint}
            <div class="anno-form">
              <input type="text" bind:value={annoText} placeholder="Note text..." />
              <div class="color-pick">
                {#each colors as c}
                  <button class="color-dot" style="background:{c}" class:active={annoColor === c} onclick={() => annoColor = c}></button>
                {/each}
              </div>
              <button class="save-btn" onclick={saveAnnotation} disabled={!annoText.trim()}>Save</button>
              <button class="cancel-btn" onclick={cancelAnnotate}>Cancel</button>
            </div>
          {:else}
            <span class="anno-hint">Click on the document to place a note</span>
            <button class="cancel-btn" onclick={cancelAnnotate}>Cancel</button>
          {/if}
        </div>
      {/if}
      <div class="pdf-toolbar-right">
        <span class="pdf-info">{annotations.length} note{annotations.length !== 1 ? 's' : ''}</span>
      </div>
    </div>

    <div class="pdf-content">
      {#if showIframe}
        <iframe src={url} title="PDF Viewer" class="pdf-iframe"></iframe>
      {:else}
        <div class="anno-canvas" onclick={handleCanvasClick}>
          <iframe src={url} title="PDF Background" class="pdf-iframe-bg"></iframe>
          {#each annotations as anno, i}
            <div
              class="anno-marker"
              style="left:{anno.x}%; top:{anno.y}%; background:{anno.color || '#ef4444'}"
              title={anno.text}
            >
              {i + 1}
            </div>
          {/each}
          {#if pendingPoint}
            <div class="anno-marker pending" style="left:{pendingPoint.x}%; top:{pendingPoint.y}%; background:{annoColor}">
              ?
            </div>
          {/if}
        </div>
      {/if}

      {#if annotations.length > 0 && !showIframe}
        <div class="anno-list">
          {#each annotations as anno, i}
            <div class="anno-item">
              <span class="anno-dot" style="background:{anno.color || '#ef4444'}">{i + 1}</span>
              <span class="anno-text">{anno.text}</span>
              <button class="anno-remove" onclick={() => removeAnno(i)}>&times;</button>
            </div>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .pdf-viewer { display: flex; flex-direction: column; height: 100%; background: #1a1a2e; }

  .pdf-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: #6b7280; }
  .pdf-empty-icon { font-size: 48px; margin-bottom: 12px; }

  .pdf-toolbar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 6px 12px; background: #1a1744; border-bottom: 1px solid #312e81; flex-shrink: 0;
  }
  .pdf-toolbar-left { display: flex; gap: 4px; }
  .pdf-toolbar-center { display: flex; align-items: center; gap: 8px; }
  .pdf-toolbar-right { display: flex; align-items: center; gap: 8px; }
  .pdf-info { color: #818cf8; font-size: 12px; }

  .tool-btn {
    padding: 4px 12px; border-radius: 4px; border: 1px solid #312e81;
    background: transparent; color: #818cf8; cursor: pointer; font-size: 12px;
  }
  .tool-btn.active { background: #4f46e5; color: white; border-color: #4f46e5; }
  .tool-btn:hover { background: #312e81; }

  .anno-btn {
    padding: 4px 10px; border-radius: 4px; border: 1px solid #312e81;
    background: #4f46e5; color: white; cursor: pointer; font-size: 12px;
  }
  .anno-btn:hover { background: #6366f1; }

  .anno-form { display: flex; align-items: center; gap: 6px; }
  .anno-form input {
    padding: 4px 8px; background: #0f0d2e; border: 1px solid #312e81;
    border-radius: 4px; color: #e0e7ff; font-size: 12px; width: 160px;
  }
  .color-pick { display: flex; gap: 4px; }
  .color-dot {
    width: 18px; height: 18px; border-radius: 50%; border: 2px solid transparent;
    cursor: pointer;
  }
  .color-dot.active { border-color: white; }
  .save-btn {
    padding: 4px 10px; background: #22c55e; color: white; border: none;
    border-radius: 4px; cursor: pointer; font-size: 12px;
  }
  .save-btn:disabled { opacity: 0.5; }
  .cancel-btn {
    padding: 4px 10px; background: transparent; color: #818cf8; border: 1px solid #312e81;
    border-radius: 4px; cursor: pointer; font-size: 12px;
  }
  .anno-hint { color: #f59e0b; font-size: 12px; }

  .pdf-content { flex: 1; display: flex; flex-direction: column; overflow: hidden; position: relative; }

  .pdf-iframe { width: 100%; height: 100%; border: none; flex: 1; }
  .pdf-iframe-bg { width: 100%; height: 100%; border: none; }

  .anno-canvas { position: relative; flex: 1; overflow: auto; }
  .anno-marker {
    position: absolute; width: 22px; height: 22px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    color: white; font-size: 11px; font-weight: bold;
    cursor: pointer; transform: translate(-50%, -50%);
    box-shadow: 0 2px 6px rgba(0,0,0,0.4); z-index: 10;
  }
  .anno-marker.pending { animation: pulse 1s infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }

  .anno-list {
    flex-shrink: 0; max-height: 150px; overflow-y: auto;
    background: #1a1744; border-top: 1px solid #312e81; padding: 8px;
  }
  .anno-item {
    display: flex; align-items: center; gap: 8px; padding: 4px 0;
    border-bottom: 1px solid #1e1b4b; font-size: 12px; color: #c4b5fd;
  }
  .anno-dot {
    width: 18px; height: 18px; border-radius: 50%; display: flex;
    align-items: center; justify-content: center; color: white;
    font-size: 10px; font-weight: bold; flex-shrink: 0;
  }
  .anno-text { flex: 1; }
  .anno-remove {
    background: none; border: none; color: #6b7280; cursor: pointer;
    font-size: 16px; padding: 0 4px;
  }
  .anno-remove:hover { color: #ef4444; }
</style>