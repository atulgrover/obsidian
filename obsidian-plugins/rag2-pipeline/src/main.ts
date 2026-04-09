import { Plugin, ItemView, WorkspaceLeaf, Notice, TFile, MarkdownRenderer } from 'obsidian';
import { RAG2Settings, DEFAULT_SETTINGS, RAG2SettingTab, api, uploadFile } from '../shared/settings';

export const PIPELINE_VIEW_TYPE = 'rag2-pipeline-view';

// ──────────────────────────────────────────────────────────
// Pipeline View
// ──────────────────────────────────────────────────────────

export class PipelineView extends ItemView {
	plugin: RAG2PipelinePlugin;

	constructor(leaf: WorkspaceLeaf, plugin: RAG2PipelinePlugin) {
		super(leaf);
		this.plugin = plugin;
	}

	getViewType(): string { return PIPELINE_VIEW_TYPE; }
	getDisplayText(): string { return 'RAG2 Pipeline'; }
	getIcon(): string { return 'file-search'; }

	async onOpen() {
		const container = this.containerEl.children[1] || this.containerEl;
		container.empty();
		container.addClass('rag2-pipeline');

		// Header
		const header = container.createEl('div', { cls: 'pipeline-header' });
		header.createEl('h2', { text: 'RAG2 Pipeline' });
		header.createEl('p', { text: 'PDF → LiteParse → PageIndex → SemChunk → LightRAG', cls: 'pipeline-subtitle' });

		// URL input
		const urlSection = container.createEl('div', { cls: 'pipeline-section' });
		urlSection.createEl('h3', { text: 'Stage 1: Ingest PDF' });
		const urlInput = urlSection.createEl('input', { type: 'text', placeholder: 'PDF URL or drop file below...' });
		urlInput.addClass('pipeline-input');

		const btnRow = urlSection.createEl('div', { cls: 'pipeline-btn-row' });
		const ingestBtn = btnRow.createEl('button', { text: 'Ingest PDF', cls: 'pipeline-btn primary' });
		const fullBtn = btnRow.createEl('button', { text: 'Full Pipeline (1→2→3)', cls: 'pipeline-btn accent' });

		// File drop zone
		const dropZone = urlSection.createEl('div', { cls: 'pipeline-drop-zone', text: 'Drop PDF file here' });
		dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.addClass('dragover'); });
		dropZone.addEventListener('dragleave', () => dropZone.removeClass('dragover'));
		dropZone.addEventListener('drop', async (e) => {
			e.preventDefault();
			dropZone.removeClass('dragover');
			const file = e.dataTransfer?.files[0];
			if (file && file.type === 'application/pdf') {
				await this.runUpload(file);
			} else {
				new Notice('Please drop a PDF file');
			}
		});

		// Stage 2: Chunk
		const chunkSection = container.createEl('div', { cls: 'pipeline-section' });
		chunkSection.createEl('h3', { text: 'Stage 2: Chunk' });
		const chunkSlug = chunkSection.createEl('input', { type: 'text', placeholder: 'Source slug...' });
		chunkSlug.addClass('pipeline-input');
		const chunkBtn = chunkSection.createEl('button', { text: 'Chunk from Vault', cls: 'pipeline-btn' });

		// Stage 3: Ingest to LightRAG
		const ingestSection = container.createEl('div', { cls: 'pipeline-section' });
		ingestSection.createEl('h3', { text: 'Stage 3: Ingest to LightRAG' });
		const ingestSlug = ingestSection.createEl('input', { type: 'text', placeholder: 'Source slug...' });
		ingestSlug.addClass('pipeline-input');
		const ingestLrBtn = ingestSection.createEl('button', { text: 'Ingest to LightRAG', cls: 'pipeline-btn success' });

		// Status output
		const statusEl = container.createEl('div', { cls: 'pipeline-status' });
		const statusText = statusEl.createEl('div', { cls: 'pipeline-status-text', text: 'Ready' });

		// Source list
		const sourceSection = container.createEl('div', { cls: 'pipeline-section' });
		sourceSection.createEl('h3', { text: 'Vault Sources' });
		const sourceList = sourceSection.createEl('div', { cls: 'pipeline-source-list' });
		const refreshBtn = sourceSection.createEl('button', { text: 'Refresh', cls: 'pipeline-btn small' });

		const loadSources = async () => {
			sourceList.empty();
			try {
				const resp = await api<{ sources: Array<{ slug: string; pipeline_stage: string; filename: string; total_pages: number }> }>(
					`${this.plugin.settings.vaultPipelineUrl}/vault/sources`
				);
				for (const src of resp.sources) {
					const item = sourceList.createEl('div', { cls: 'pipeline-source-item' });
					item.createEl('span', { text: src.filename || src.slug, cls: 'source-name' });
					const badge = item.createEl('span', { text: src.pipeline_stage, cls: 'source-badge' });
					const stageColors: Record<string, string> = {
						liteparse: '#6366f1', pageindex: '#8b5cf6', semchunk: '#a855f7',
						ingested: '#22c55e', verified: '#16a34a',
					};
					badge.style.background = stageColors[src.pipeline_stage] || '#6b7280';
					item.addEventListener('click', () => {
						chunkSlug.value = src.slug;
						ingestSlug.value = src.slug;
					});
				}
			} catch (e: any) {
				sourceList.createEl('div', { text: `Error: ${e.message}`, cls: 'error' });
			}
		};

		// Button handlers
		ingestBtn.addEventListener('click', async () => {
			if (!urlInput.value) { new Notice('Enter a PDF URL'); return; }
			statusText.setText('Stage 1: Ingesting PDF...');
			try {
				const result = await api(`${this.plugin.settings.vaultPipelineUrl}/vault/ingest-pdf`, {
					url: urlInput.value, max_tokens: 512, overlap_tokens: 75,
				});
				statusText.setText(`Stage 1 done: ${result.sections} sections, ${result.total_pages} pages`);
				chunkSlug.value = result.slug;
				ingestSlug.value = result.slug;
				await loadSources();
				new Notice(`Ingested: ${result.slug}`);
			} catch (e: any) {
				statusText.setText(`Error: ${e.message}`);
				new Notice(`Error: ${e.message}`);
			}
		});

		fullBtn.addEventListener('click', async () => {
			if (!urlInput.value) { new Notice('Enter a PDF URL'); return; }
			statusText.setText('Running full pipeline...');
			try {
				const result = await api(`${this.plugin.settings.vaultPipelineUrl}/vault/full-pipeline`, {
					url: urlInput.value, max_tokens: 512, overlap_tokens: 75,
				});
				statusText.setText('Pipeline complete!');
				await loadSources();
				new Notice('Pipeline complete!');
			} catch (e: any) {
				statusText.setText(`Error: ${e.message}`);
				new Notice(`Error: ${e.message}`);
			}
		});

		chunkBtn.addEventListener('click', async () => {
			if (!chunkSlug.value) { new Notice('Enter a source slug'); return; }
			statusText.setText('Stage 2: Chunking...');
			try {
				const result = await api(`${this.plugin.settings.vaultPipelineUrl}/vault/chunk`, {
					slug: chunkSlug.value, max_tokens: 512, overlap_tokens: 75,
				});
				statusText.setText(`Stage 2 done: ${result.total_chunks} chunks, ${result.total_tokens} tokens`);
				ingestSlug.value = chunkSlug.value;
				new Notice(`Chunked: ${result.total_chunks} chunks`);
			} catch (e: any) {
				statusText.setText(`Error: ${e.message}`);
			}
		});

		ingestLrBtn.addEventListener('click', async () => {
			if (!ingestSlug.value) { new Notice('Enter a source slug'); return; }
			statusText.setText('Stage 3: Ingesting to LightRAG...');
			try {
				const result = await api(`${this.plugin.settings.vaultPipelineUrl}/vault/ingest-lightrag`, {
					slug: ingestSlug.value,
				});
				statusText.setText(`Stage 3 done: ${result.ingested} ingested, ${result.skipped} skipped, ${result.failed} failed`);
				await loadSources();
				new Notice(`Ingested: ${result.ingested} chunks`);
			} catch (e: any) {
				statusText.setText(`Error: ${e.message}`);
			}
		});

		refreshBtn.addEventListener('click', loadSources);
		loadSources();
	}

	async runUpload(file: File) {
		const statusEl = this.containerEl.querySelector('.pipeline-status-text') as HTMLElement;
		if (statusEl) statusEl.setText('Uploading PDF...');
		try {
			const result = await uploadFile(
				`${this.plugin.settings.vaultPipelineUrl}/vault/ingest-pdf-upload`,
				file,
			);
			if (statusEl) statusEl.setText(`Uploaded: ${result.sections} sections, ${result.total_pages} pages`);
			new Notice(`Uploaded: ${result.slug}`);
		} catch (e: any) {
			if (statusEl) statusEl.setText(`Error: ${e.message}`);
			new Notice(`Error: ${e.message}`);
		}
	}
}

// ──────────────────────────────────────────────────────────
// Plugin
// ──────────────────────────────────────────────────────────

export default class RAG2PipelinePlugin extends Plugin {
	settings: RAG2Settings = { ...DEFAULT_SETTINGS };

	async onload() {
		await this.loadSettings();

		this.registerView(PIPELINE_VIEW_TYPE, (leaf) => new PipelineView(leaf, this));

		this.addRibbonIcon('file-search', 'RAG2 Pipeline', () => {
			this.activateView();
		});

		this.addCommand({
			id: 'open-rag2-pipeline',
			name: 'Open RAG2 Pipeline',
			callback: () => this.activateView(),
		});

		this.addSettingTab(new RAG2SettingTab(this.app, this));
	}

	async onunload() {
		this.app.workspace.detachLeavesOfType(PIPELINE_VIEW_TYPE);
	}

	async loadSettings() {
		this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
	}

	async saveSettings() {
		await this.saveData(this.settings);
	}

	async activateView() {
		const { workspace } = this.app;
		let leaf = workspace.getLeavesOfType(PIPELINE_VIEW_TYPE)[0];
		if (!leaf) {
			const rightLeaf = workspace.getRightLeaf(false);
			if (rightLeaf) {
				await rightLeaf.setViewState({ type: PIPELINE_VIEW_TYPE, active: true });
				leaf = rightLeaf;
			}
		}
		if (leaf) workspace.revealLeaf(leaf);
	}
}