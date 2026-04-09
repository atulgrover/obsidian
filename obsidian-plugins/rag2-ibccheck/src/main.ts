import { Plugin, ItemView, WorkspaceLeaf, Notice } from 'obsidian';
import { RAG2Settings, DEFAULT_SETTINGS, RAG2SettingTab, api } from '../shared/settings';

export const CHECK_VIEW_TYPE = 'rag2-ibccheck-view';

const CATEGORIES: Record<string, string> = {
	A: 'Corporate Debtor', B: 'Resolution Applicant', C: 'Resolution Plan Content',
	D: 'Feasibility & Viability', E: 'Compliance with Law', F: 'Additional Requirements',
};

export class IBCCheckView extends ItemView {
	plugin: RAG2IBCCheckPlugin;
	slug: string = '';
	result: any = null;
	checking = false;

	constructor(leaf: WorkspaceLeaf, plugin: RAG2IBCCheckPlugin) {
		super(leaf);
		this.plugin = plugin;
	}

	getViewType(): string { return CHECK_VIEW_TYPE; }
	getDisplayText(): string { return `IBC Check: ${this.slug || '...'}`; }
	getIcon(): string { return 'check-circle'; }

	async onOpen() { await this.render(); }

	async setSlug(slug: string) {
		this.slug = slug;
		await this.render();
	}

	async render() {
		const container = this.containerEl.children[1] || this.containerEl;
		container.empty();
		container.addClass('rag2-ibccheck');

		// Header
		const header = container.createEl('div', { cls: 'check-header' });
		header.createEl('h2', { text: `IBC Compliance Check: ${this.slug}` });
		const runBtn = header.createEl('button', { text: this.checking ? 'Analysing...' : 'Run Compliance Check', cls: 'check-btn' });
		runBtn.disabled = this.checking;
		runBtn.addEventListener('click', async () => {
			this.checking = true;
			await this.render();
			try {
				this.result = await api(`${this.plugin.settings.vaultPipelineUrl}/lightrag/compliance/check`, { slug: this.slug });
				new Notice('Compliance check complete');
			} catch (e: any) {
				new Notice(`Error: ${e.message}`);
			} finally {
				this.checking = false;
				await this.render();
			}
		});

		if (!this.result) {
			container.createEl('div', { text: 'Click "Run Compliance Check" to evaluate against 20 mandatory IBC requirements.', cls: 'empty-state' });
			return;
		}

		// Summary bar
		const statusColors: Record<string, string> = { compliant: '#22c55e', partial: '#f59e0b', non_compliant: '#ef4444' };
		const summary = container.createEl('div', { cls: 'check-summary' });
		summary.style.borderLeft = `4px solid ${statusColors[this.result.overall_status] || '#6b7280'}`;
		summary.createEl('div', { text: this.result.overall_status?.replace(/_/g, ' ').toUpperCase(), cls: 'overall-status' });
		summary.style.color = statusColors[this.result.overall_status] || '#6b7280';
		const counts = summary.createEl('div', { cls: 'check-counts' });
		counts.createEl('span', { text: `✓ ${this.result.compliant}`, cls: 'count compliant' });
		counts.createEl('span', { text: `⚠ ${this.result.partial}`, cls: 'count partial' });
		counts.createEl('span', { text: `✗ ${this.result.non_compliant}`, cls: 'count non-compliant' });
		counts.createEl('span', { text: `— ${this.result.not_found}`, cls: 'count not-found' });
		summary.createEl('div', { text: `${this.result.chunks_analyzed} chunks · ${this.result.duration_ms}ms`, cls: 'check-meta' });

		// Grouped tables
		const grouped: Record<string, any[]> = {};
		for (const r of (this.result.results || [])) {
			const cat = r.id?.charAt(0) || 'X';
			if (!grouped[cat]) grouped[cat] = [];
			grouped[cat].push(r);
		}

		for (const [cat, items] of Object.entries(grouped)) {
			const section = container.createEl('div', { cls: 'check-category' });
			section.createEl('h3', { text: `${cat}. ${CATEGORIES[cat] || cat}` });
			const table = section.createEl('table');
			const thead = table.createEl('thead');
			const headerRow = thead.createEl('tr');
			headerRow.createEl('th', { text: 'ID' });
			headerRow.createEl('th', { text: 'Requirement' });
			headerRow.createEl('th', { text: 'Section' });
			headerRow.createEl('th', { text: 'Status' });

			const tbody = table.createEl('tbody');
			for (const item of items) {
				const row = tbody.createEl('tr');
				row.createEl('td', { text: item.id, cls: 'req-id' });
				row.createEl('td', { text: item.requirement });
				row.createEl('td', { text: item.section, cls: 'sec-ref' });
				const statusTd = row.createEl('td');
				const badge = statusTd.createEl('span', { cls: 'status-badge' });
				badge.textContent = item.status;
				badge.style.background = statusColors[item.status] || '#6b7280';

				if (item.evidence) {
					const evRow = tbody.createEl('tr', { cls: 'evidence-row' });
					const evCell = evRow.createEl('td', { attr: { colspan: '4' } });
					const details = evCell.createEl('details');
					details.createEl('summary', { text: 'Evidence' });
					details.createEl('p', { text: item.evidence });
				}
			}
		}
	}
}

export default class RAG2IBCCheckPlugin extends Plugin {
	settings: RAG2Settings = { ...DEFAULT_SETTINGS };

	async onload() {
		await this.loadSettings();
		this.registerView(CHECK_VIEW_TYPE, (leaf) => new IBCCheckView(leaf, this));
		this.addCommand({ id: 'open-ibc-check', name: 'Open IBC Check', callback: () => this.activateView('') });
		this.addSettingTab(new RAG2SettingTab(this.app, this));
	}

	async onunload() { this.app.workspace.detachLeavesOfType(CHECK_VIEW_TYPE); }
	async loadSettings() { this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData()); }
	async saveSettings() { await this.saveData(this.settings); }

	async activateView(slug?: string) {
		let leaf = this.app.workspace.getLeavesOfType(CHECK_VIEW_TYPE)[0];
		if (!leaf) { leaf = this.app.workspace.getRightLeaf(false); if (leaf) await leaf.setViewState({ type: CHECK_VIEW_TYPE, active: true }); }
		if (leaf && slug) (leaf.view as IBCCheckView).setSlug(slug);
		if (leaf) this.app.workspace.revealLeaf(leaf);
	}
}