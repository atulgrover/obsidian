import { Plugin, ItemView, WorkspaceLeaf, Notice } from 'obsidian';
import { RAG2Settings, DEFAULT_SETTINGS, RAG2SettingTab, api } from '../shared/settings';

export const AUDIT_VIEW_TYPE = 'rag2-chunkaudit-view';

export class ChunkAuditView extends ItemView {
	plugin: RAG2ChunkAuditPlugin;
	slug: string = '';
	chunks: any[] = [];
	auditData: any = null;
	loading = false;

	constructor(leaf: WorkspaceLeaf, plugin: RAG2ChunkAuditPlugin) {
		super(leaf);
		this.plugin = plugin;
	}

	getViewType(): string { return AUDIT_VIEW_TYPE; }
	getDisplayText(): string { return `Chunk Audit: ${this.slug || '...'}`; }
	getIcon(): string { return 'bar-chart'; }

	async onOpen() { await this.render(); }

	async setSlug(slug: string) { this.slug = slug; await this.render(); }

	async render() {
		const container = this.containerEl.children[1] || this.containerEl;
		container.empty();
		container.addClass('rag2-chunkaudit');

		// Header
		const header = container.createEl('div', { cls: 'audit-header' });
		header.createEl('h2', { text: `Chunk Audit: ${this.slug}` });
		const reingestBtn = header.createEl('button', { text: this.loading ? 'Re-ingesting...' : 'Re-ingest to LightRAG', cls: 'audit-btn' });
		reingestBtn.disabled = this.loading;
		reingestBtn.addEventListener('click', async () => {
			this.loading = true; await this.render();
			try {
				await api(`${this.plugin.settings.vaultPipelineUrl}/vault/ingest-lightrag`, { slug: this.slug });
				new Notice('Re-ingestion complete');
			} catch (e: any) { new Notice(`Error: ${e.message}`); }
			finally { this.loading = false; await this.loadAudit(); await this.render(); }
		});

		// Load data
		if (!this.slug) {
			container.createEl('div', { text: 'Enter a source slug to view audit data.', cls: 'empty-state' });
			const slugInput = container.createEl('input', { type: 'text', placeholder: 'Source slug...', cls: 'audit-input' });
			slugInput.addEventListener('change', async () => {
				this.slug = slugInput.value;
				await this.loadAudit();
				await this.render();
			});
			return;
		}

		await this.loadAudit();

		if (this.loading) {
			container.createEl('div', { text: 'Loading...', cls: 'loading' });
			return;
		}

		// Summary
		if (this.auditData) {
			const summary = this.auditData.summary || {};
			const summaryBar = container.createEl('div', { cls: 'audit-summary' });
			summaryBar.createEl('span', { text: `Total: ${summary.total || this.chunks.length}`, cls: 'stat total' });
			summaryBar.createEl('span', { text: `✓ Ingested: ${summary.ingested || 0}`, cls: 'stat ingested' });
			summaryBar.createEl('span', { text: `✗ Failed: ${summary.failed || 0}`, cls: 'stat failed' });
			summaryBar.createEl('span', { text: `○ Pending: ${summary.pending || 0}`, cls: 'stat pending' });
		} else if (this.chunks.length > 0) {
			const summaryBar = container.createEl('div', { cls: 'audit-summary' });
			summaryBar.createEl('span', { text: `Total: ${this.chunks.length}`, cls: 'stat total' });
			const ingested = this.chunks.filter((c: any) => c.lightrag_ingested).length;
			summaryBar.createEl('span', { text: `✓ Ingested: ${ingested}`, cls: 'stat ingested' });
			summaryBar.createEl('span', { text: `○ Pending: ${this.chunks.length - ingested}`, cls: 'stat pending' });
		}

		// Table
		if (this.chunks.length > 0) {
			const table = container.createEl('table');
			const thead = table.createEl('thead');
			const headerRow = thead.createEl('tr');
			headerRow.createEl('th', { text: 'Status' });
			headerRow.createEl('th', { text: 'ID' });
			headerRow.createEl('th', { text: 'Pages' });
			headerRow.createEl('th', { text: 'Tokens' });
			headerRow.createEl('th', { text: 'Stage' });

			const tbody = table.createEl('tbody');
			for (const chunk of this.chunks) {
				const row = tbody.createEl('tr');
				const statusIcon = chunk.lightrag_ingested ? '✓' : '○';
				const statusColor = chunk.lightrag_ingested ? '#22c55e' : '#f59e0b';
				const statusCell = row.createEl('td');
				statusCell.createEl('span', { text: statusIcon }).style.color = statusColor;
				row.createEl('td', { text: `chunk-${String(chunk.chunk_index + 1).padStart(3, '0')}`, cls: 'chunk-id' });
				row.createEl('td', { text: `${chunk.page_start}-${chunk.page_end}` });
				row.createEl('td', { text: String(chunk.token_count) });
				const stageCell = row.createEl('td');
				stageCell.createEl('span', { text: chunk.pipeline_stage || '—', cls: 'stage-badge' });
			}
		} else {
			container.createEl('div', { text: 'No chunks found. Run the pipeline first.', cls: 'empty-state' });
		}
	}

	async loadAudit() {
		try {
			this.chunks = (await api(`${this.plugin.settings.vaultPipelineUrl}/vault/chunks/${this.slug}`)).chunks || [];
			try {
				this.auditData = await api(`${this.plugin.settings.lightragUrl}/audit/source?src=${this.slug}`);
			} catch { this.auditData = null; }
		} catch (e: any) {
			this.chunks = [];
			this.auditData = null;
		}
	}
}

export default class RAG2ChunkAuditPlugin extends Plugin {
	settings: RAG2Settings = { ...DEFAULT_SETTINGS };

	async onload() {
		await this.loadSettings();
		this.registerView(AUDIT_VIEW_TYPE, (leaf) => new ChunkAuditView(leaf, this));
		this.addCommand({ id: 'open-chunk-audit', name: 'Open Chunk Audit', callback: () => this.activateView('') });
		this.addSettingTab(new RAG2SettingTab(this.app, this));
	}

	async onunload() { this.app.workspace.detachLeavesOfType(AUDIT_VIEW_TYPE); }
	async loadSettings() { this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData()); }
	async saveSettings() { await this.saveData(this.settings); }

	async activateView(slug?: string) {
		let leaf = this.app.workspace.getLeavesOfType(AUDIT_VIEW_TYPE)[0];
		if (!leaf) { leaf = this.app.workspace.getRightLeaf(false); if (leaf) await leaf.setViewState({ type: AUDIT_VIEW_TYPE, active: true }); }
		if (leaf && slug) (leaf.view as ChunkAuditView).setSlug(slug);
		if (leaf) this.app.workspace.revealLeaf(leaf);
	}
}