<script lang="ts">
  let { url = '' }: { url?: string } = $props();

  function openInNewTab() {
    if (!url) return;
    window.open(url, '_blank', 'noopener,noreferrer');
  }
</script>

<div class="pdf-viewer">
  {#if !url}
    <div class="pdf-empty">
      <div class="pdf-empty-icon">&#128196;</div>
      <p>Select a source to view its PDF.</p>
    </div>
  {:else}
    <div class="pdf-toolbar">
      <div class="pdf-title">
        <span class="eyebrow">Document Preview</span>
        <strong>Original PDF</strong>
      </div>
      <div class="pdf-actions">
        <a class="action-btn subtle" href={url} target="_blank" rel="noreferrer">Open Raw</a>
        <button class="action-btn primary" onclick={openInNewTab}>Open In Tab</button>
      </div>
    </div>

    <div class="pdf-frame-wrap">
      <iframe src={url} title="PDF Viewer" class="pdf-iframe"></iframe>
    </div>
  {/if}
</div>

<style>
  .pdf-viewer {
    display: flex;
    flex-direction: column;
    height: 100%;
    background:
      linear-gradient(180deg, color-mix(in srgb, var(--accent) 6%, transparent), transparent 18%),
      var(--bg-canvas);
  }

  .pdf-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--text-faint);
  }
  .pdf-empty-icon {
    font-size: 46px;
    margin-bottom: 12px;
  }

  .pdf-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 16px 18px;
    border-bottom: 1px solid var(--border);
    background: color-mix(in srgb, var(--bg-panel-strong) 94%, transparent);
    backdrop-filter: blur(8px);
  }
  .pdf-title {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .eyebrow {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--accent-soft);
  }
  .pdf-title strong {
    font-size: 15px;
    color: var(--text-strong);
  }

  .pdf-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .action-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 9px 12px;
    border-radius: 12px;
    border: 1px solid var(--border-soft);
    font-size: 12px;
    text-decoration: none;
    cursor: pointer;
  }
  .action-btn.subtle {
    background: transparent;
    color: var(--text);
  }
  .action-btn.primary {
    background: linear-gradient(135deg, var(--accent), var(--accent-strong));
    border-color: transparent;
    color: white;
  }

  .pdf-frame-wrap {
    flex: 1;
    padding: 14px;
    min-height: 0;
  }
  .pdf-iframe {
    width: 100%;
    height: 100%;
    border: 1px solid var(--border-strong);
    border-radius: 20px;
    background: white;
    box-shadow: var(--shadow-lg);
  }

  @media (max-width: 720px) {
    .pdf-toolbar {
      flex-direction: column;
      align-items: stretch;
    }
    .pdf-actions {
      width: 100%;
    }
    .action-btn {
      flex: 1;
    }
    .pdf-frame-wrap {
      padding: 10px;
    }
  }
</style>
