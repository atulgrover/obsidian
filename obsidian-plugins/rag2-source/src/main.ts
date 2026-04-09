import { Plugin, ItemView, WorkspaceLeaf, Notice, TFile, MarkdownRenderer } from 'obsidian';
import { RAG2Settings, DEFAULT_SETTINGS, RAG2SettingTab, api } from '../shared/settings';

export const SOURCE_VIEW_TYPE = 'rag2-source-view';

export class SourceView extends ItemView {
	plugin: RAG2SourcePlugin;
	slug: string = '';
	activeTab: string = 'tree';

	constructor(leaf: WorkspaceLeaf, plugin: RAG2SourcePlugin) {
		super(leaf);
		this.plugin = plugin;
	}

	getViewType(): string { return SOURCE_VIEW_TYPE; }
	getDisplayText(): string { return `Source: ${this.slug || '...'}`; }
	getIcon(): string { return 'document'; }

	async onOpen() {
		await this.render();
	}

	async setSlug(slug: string) {
		this.slug = slug;
		await this.render();
	}

	async render() {
		const container = this.containerEl.children[1] || this.containerEl;
		container.empty();
		container.addClass('rag2-source');

		if (!this.slug) {
			container.createEl('div', { text: 'Open a source document note (type: source-document) to view it here.', cls: 'empty-state' });
			return;
		}

		// Fetch source metadata from vault-pipeline
		let source: any = null;
		try {
			source = await api(`${this.plugin.settings.vaultPipelineUrl}/vault/sources/${this.slug}`);
		} catch (e: any) {
			container.createEl('div', { text: `Error: ${e.message}`, cls: 'error' });
			return;
		}

		const meta = source.metadata || {};

		// Header
		const header = container.createEl('div', { cls: 'source-header' });
		header.createEl('h2', { text: meta.filename || this.slug });

		// Badges
		const badges = header.createEl('div', { cls: 'badges' });
		const stageColors: Record<string, string> = {
			liteparse: '#6366f1', pageindex: '#8b5cf6', semchunk: '#a855f7',
			ingested: '#22c55e', verified: '#16a34a',
		};
		const stage = meta.pipeline_stage || 'unknown';
		badges.createEl('span', { text: stage, cls: 'badge' }).style.background = stageColors[stage] || '#6b7280';
		badges.createEl('span', { text: `${meta.total_pages || 0} pages`, cls: 'badge gray' });
		badges.createEl('span', { text: `${(meta.total_chars || 0).toLocaleString()} chars`, cls: 'badge gray' });

		// Tab bar
		const tabBar = container.createEl('div', { cls: 'tab-bar' });
		for (const tab of ['tree', 'text', 'metadata']) {
			const btn = tabBar.createEl('button', { text: tab.charAt(0).toUpperCase() + tab.slice(1), cls: 'tab-btn' });
			if (tab === this.activeTab) btn.addClass('active');
			btn.addEventListener('click', () => { this.activeTab = tab; this.render(); });
		}

		// Content area
		const content = container.createEl('div', { cls: 'source-content' });

		if (this.activeTab === 'tree') {
			await this.renderTree(content, source);
		} else if (this.activeTab === 'text') {
			await this.renderFullText(content);
		} else {
			this.renderMetadata(content, meta);
		}
	}

	async renderTree(container: HTMLElement, source: any) {
		let sections: any[] = [];
		try {
			const resp = await api(`${this.plugin.settings.vaultPipelineUrl}/vault/sources/${this.slug}/sections`);
			sections = resp.sections || [];
		} catch { sections = []; }

		if (sections.length === 0) {
			container.createEl('div', { text: 'No sections found. Run the pipeline first.', cls: 'empty-state' });
			return;
		}

		for (const sec of sections) {
			const item = container.createEl('div', { cls: 'section-item' });
			item.style.paddingLeft = `${(sec.level || 1) * 16}px`;

			const level = item.createEl('span', { text: `L${sec.level}`, cls: 'level-badge' });
			item.createEl('span', { text: sec.title || sec.filename, cls: 'sec-title' });
			item.createEl('span', { text: `pp.${sec.page_start}-${sec.page_end}`, cls: 'sec-meta' });
			if (sec.is_leaf) item.createEl('span', { text: 'leaf', cls: 'leaf-badge' });
		}
	}

	async renderFullText(container: HTMLElement) {
		// Try reading from vault directly
		const filePath = `sources/${this.slug}/full-text.md`;
		const file = this.app.vault.getFileByPath(filePath);
		if (file) {
			const content = await this.app.vault.read(file);
			// Strip frontmatter
			const body = content.replace(/^---\n[\s\S]*?\n---\n?/, '');
			const pre = container.createEl('pre', { cls: 'full-text-content' });
			pre.textContent = body;
		} else {
			container.createEl('div', { text: 'Full text not available. Run Stage 1 to generate it.', cls: 'empty-state' });
		}
	}

	renderMetadata(container: HTMLElement, meta: Record<string, any>) {
		const grid = container.createEl('div', { cls: 'meta-grid' });
		for (const [key, value] of Object.entries(meta)) {
			if (key === 'type') continue;
			const row = grid.createEl('div', { cls: 'meta-row' });
			row.createEl('span', { text: key, cls: 'meta-key' });
			row.createEl('span', { text: typeof value === 'object' ? JSON.stringify(value) : String(value), cls: 'meta-val' });
		}
	}
}

export default class RAG2SourcePlugin extends Plugin {
	settings: RAG2Settings = { ...DEFAULT_SETTINGS };

	async onload() {
		await this.loadSettings();

		this.registerView(SOURCE_VIEW_TYPE, (leaf) => new SourceView(leaf, this));

		// Auto-activate when opening a source-document note
		this.registerEvent(this.app.workspace.on('file-open', (file) => {
			if (file && file.path.startsWith('sources/') && file.path.endsWith('/_index.md')) {
				this.activateView(file.path.split('/')[1]);
			}
		}));

		this.addCommand({
			id: 'open-rag2-source',
			name: 'Open Source Viewer',
			callback: () => this.activateView(''),
		});

		this.addSettingTab(new RAG2SettingTab(this.app, this));
	}

	async onunload() {
		this.app.workspace.detachLeavesOfType(SOURCE_VIEW_TYPE);
	}

	async loadSettings() { this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData()); }
	async saveSettings() { await this.saveData(this.settings); }

	async activateView(slug: string) {
		const { workspace } = this.app;
		let leaf = workspace.getLeavesOfType(SOURCE_VIEW_TYPE)[0];
		if (!leaf) {
			leaf = workspace.getRightLeaf(false);
			if (leaf) await leaf.setViewState({ type: SOURCE_VIEW_TYPE, active: true });
		}
		if (leaf && slug) {
			const view = leaf.view as SourceView;
			view.setSlug(slug);
		}
		if (leaf) workspace.revealLeaf(leaf);
	}
}