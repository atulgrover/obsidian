import { Plugin, ItemView, WorkspaceLeaf, Notice } from 'obsidian';
import { RAG2Settings, DEFAULT_SETTINGS, RAG2SettingTab, api, updateFrontmatter } from '../shared/settings';

export const VERIFY_VIEW_TYPE = 'rag2-ibcverify-view';

export class IBCVerifyView extends ItemView {
	plugin: RAG2IBCVerifyPlugin;
	slug: string = '';
	step: number = 1;
	planId: string = '';
	result: any = null;
	loading = false;
	humanOverrides: Record<string, string> = {};

	// Setup form fields
	company = ''; applicant = ''; applicantType = 'strategic';
	considerationCrore = ''; upfrontCrore = ''; ncltBench = ''; caseNumber = '';

	constructor(leaf: WorkspaceLeaf, plugin: RAG2IBCVerifyPlugin) {
		super(leaf);
		this.plugin = plugin;
	}

	getViewType(): string { return VERIFY_VIEW_TYPE; }
	getDisplayText(): string { return `IBC Verify: ${this.slug || '...'}`; }
	getIcon(): string { return 'shield-check'; }

	async onOpen() { await this.render(); }

	async setSlug(slug: string) { this.slug = slug; await this.render(); }

	async render() {
		const container = this.containerEl.children[1] || this.containerEl;
		container.empty();
		container.addClass('rag2-ibcverify');

		// Header
		const header = container.createEl('div', { cls: 'verify-header' });
		header.createEl('h2', { text: `IBC Verification: ${this.slug}` });
		const stepIndicator = header.createEl('div', { cls: 'step-indicator' });
		for (const [num, label] of [[1, 'Setup'], [2, 'Index'], [3, 'Verify']] as [number, string][]) {
			const s = stepIndicator.createEl('span', { text: `${num}. ${label}`, cls: 'step' });
			if (num <= this.step) s.addClass('active');
		}

		if (this.loading) {
			container.createEl('div', { text: 'Processing...', cls: 'loading' });
			return;
		}

		// Step 1: Setup
		if (this.step === 1) {
			const form = container.createEl('div', { cls: 'verify-form' });
			form.createEl('h3', { text: 'Register Matter & Plan' });
			const fields: [string, string, string][] = [
				['company', 'Corporate Debtor *', 'text'], ['applicant', 'Resolution Applicant', 'text'],
				['ncltBench', 'NCLT Bench', 'text'], ['caseNumber', 'Case Number', 'text'],
				['considerationCrore', 'Total Consideration (₹ Cr)', 'number'], ['upfrontCrore', 'Upfront Cash (₹ Cr)', 'number'],
			];
			for (const [key, label, type] of fields) {
				const grp = form.createEl('div', { cls: 'form-group' });
				grp.createEl('label', { text: label });
				const input = grp.createEl('input', { type, attr: { placeholder: label } });
				input.value = (this as any)[key] || '';
				input.addEventListener('input', () => { (this as any)[key] = input.value; });
			}
			// Applicant type dropdown
			const typeGrp = form.createEl('div', { cls: 'form-group' });
			typeGrp.createEl('label', { text: 'Applicant Type' });
			const select = typeGrp.createEl('select');
			for (const opt of ['strategic', 'financial_investor', 'promoter']) {
				select.createEl('option', { text: opt, value: opt });
			}
			select.value = this.applicantType;
			select.addEventListener('change', () => { this.applicantType = select.value; });

			const setupBtn = form.createEl('button', { text: 'Register & Continue', cls: 'verify-btn primary' });
			setupBtn.addEventListener('click', async () => {
				if (!this.company) { new Notice('Company name is required'); return; }
				this.loading = true; await this.render();
				try {
					const resp = await api(`${this.plugin.settings.lightragUrl}/matter/setup`, {
						company: this.company, source: this.slug, applicant: this.applicant || undefined,
						applicant_type: this.applicantType, nclt_bench: this.ncltBench || undefined,
						case_number: this.caseNumber || undefined,
						consideration_crore: this.considerationCrore ? parseFloat(this.considerationCrore) : undefined,
						upfront_crore: this.upfrontCrore ? parseFloat(this.upfrontCrore) : undefined,
					});
					this.planId = resp.plan_id;
					this.step = 2;
				} catch (e: any) { new Notice(`Error: ${e.message}`); }
				finally { this.loading = false; await this.render(); }
			});
		}

		// Step 2: Index
		else if (this.step === 2) {
			const content = container.createEl('div', { cls: 'verify-step' });
			content.createEl('h3', { text: 'Index Plan Sections' });
			content.createEl('p', { text: `Plan ID: ${this.planId}`, cls: 'mono' });
			content.createEl('p', { text: 'Embedding plan sections via InLegal-SBERT for deterministic vector matching.' });
			const indexBtn = content.createEl('button', { text: 'Index Plan Sections', cls: 'verify-btn' });
			indexBtn.addEventListener('click', async () => {
				this.loading = true; await this.render();
				try {
					// Read chunks from vault and send to LightRAG for indexing
					const chunks = await api(`${this.plugin.settings.vaultPipelineUrl}/vault/chunks/${this.slug}`);
					await api(`${this.plugin.settings.lightragUrl}/matter/plan/index`, {
						plan_id: this.planId,
						chunks: chunks.chunks,
					});
					this.step = 3;
				} catch (e: any) { new Notice(`Error: ${e.message}`); }
				finally { this.loading = false; await this.render(); }
			});
		}

		// Step 3: Verify
		else if (this.step === 3) {
			const content = container.createEl('div', { cls: 'verify-step' });
			content.createEl('h3', { text: 'Verify Compliance' });
			const verifyBtn = content.createEl('button', { text: 'Run Verification', cls: 'verify-btn success' });
			verifyBtn.addEventListener('click', async () => {
				this.loading = true; await this.render();
				try {
					this.result = await api(`${this.plugin.settings.lightragUrl}/matter/plan/verify?plan_id=${this.planId}`, undefined);
				} catch (e: any) { new Notice(`Error: ${e.message}`); }
				finally { this.loading = false; await this.render(); }
			});

			if (this.result) {
				this.renderResults(content);
			}
		}
	}

	renderResults(container: HTMLElement) {
		const compliance = this.result.compliance || [];
		const summary = this.result;
		const statusColors: Record<string, string> = { compliant: '#22c55e', partial: '#f59e0b', non_compliant: '#ef4444', not_found: '#6b7280' };

		// Summary
		const summaryBar = container.createEl('div', { cls: 'verify-summary' });
		const overall = summaryBar.createEl('div', { text: (summary.overall_status || '').replace(/_/g, ' ').toUpperCase(), cls: 'overall' });
		const counts = summaryBar.createEl('div', { cls: 'verify-counts' });
		counts.createEl('span', { text: `✓ ${summary.compliant || 0}`, cls: 'count compliant' });
		counts.createEl('span', { text: `⚠ ${summary.partial || 0}`, cls: 'count partial' });
		counts.createEl('span', { text: `✗ ${summary.non_compliant || 0}`, cls: 'count non-compliant' });
		counts.createEl('span', { text: `— ${summary.not_found || 0}`, cls: 'count not-found' });

		// Table
		const table = container.createEl('table');
		const thead = table.createEl('thead');
		const headerRow = thead.createEl('tr');
		headerRow.createEl('th', { text: 'ID' });
		headerRow.createEl('th', { text: 'Requirement' });
		headerRow.createEl('th', { text: 'Match' });
		headerRow.createEl('th', { text: 'Status' });
		headerRow.createEl('th', { text: 'Actions' });

		const tbody = table.createEl('tbody');
		for (const item of compliance) {
			const row = tbody.createEl('tr');
			row.createEl('td', { text: item.id, cls: 'req-id' });
			row.createEl('td', { text: item.requirement });

			const matchTd = row.createEl('td');
			if (item.matched_heading) {
				matchTd.createEl('div', { text: item.matched_heading, cls: 'match-text' });
				const conf = Number(item.confidence || 0);
				const bar = matchTd.createEl('div', { cls: 'conf-bar' });
				bar.style.width = `${conf * 100}%`;
				bar.style.background = conf >= 0.72 ? '#22c55e' : conf >= 0.55 ? '#f59e0b' : '#6b7280';
				matchTd.createEl('span', { text: `${Math.round(conf * 100)}%`, cls: 'conf-pct' });
			}

			const statusTd = row.createEl('td');
			const statusBadge = statusTd.createEl('span', { text: item.status, cls: 'status-badge' });
			statusBadge.style.background = statusColors[item.status] || '#6b7280';

			// Human verification buttons
			const actionsTd = row.createEl('td', { cls: 'actions' });
			if (this.humanOverrides[item.id]) {
				actionsTd.createEl('span', { text: `✓ ${this.humanOverrides[item.id]}`, cls: 'overridden' });
			} else {
				for (const [label, status, cls] of [['✓', 'compliant', 'v-yes'], ['⚠', 'partial', 'v-part'], ['✗', 'non_compliant', 'v-no']] as [string, string, string][]) {
					const btn = actionsTd.createEl('button', { text: label, cls: `v-btn ${cls}` });
					btn.addEventListener('click', async () => {
						try {
							await api(`${this.plugin.settings.lightragUrl}/matter/compliance/human`, {
								plan_id: this.planId, req_id: item.id, status, verified_by: 'obsidian-ui',
							});
							this.humanOverrides[item.id] = status;
							this.humanOverrides = { ...this.humanOverrides }; // trigger reactivity
							await this.render();
						} catch (e: any) { new Notice(`Error: ${e.message}`); }
					});
				}
			}
		}
	}
}

export default class RAG2IBCVerifyPlugin extends Plugin {
	settings: RAG2Settings = { ...DEFAULT_SETTINGS };

	async onload() {
		await this.loadSettings();
		this.registerView(VERIFY_VIEW_TYPE, (leaf) => new IBCVerifyView(leaf, this));
		this.addCommand({ id: 'open-ibc-verify', name: 'Open IBC Verify', callback: () => this.activateView('') });
		this.addSettingTab(new RAG2SettingTab(this.app, this));
	}

	async onunload() { this.app.workspace.detachLeavesOfType(VERIFY_VIEW_TYPE); }
	async loadSettings() { this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData()); }
	async saveSettings() { await this.saveData(this.settings); }

	async activateView(slug?: string) {
		let leaf = this.app.workspace.getLeavesOfType(VERIFY_VIEW_TYPE)[0];
		if (!leaf) { leaf = this.app.workspace.getRightLeaf(false); if (leaf) await leaf.setViewState({ type: VERIFY_VIEW_TYPE, active: true }); }
		if (leaf && slug) (leaf.view as IBCVerifyView).setSlug(slug);
		if (leaf) this.app.workspace.revealLeaf(leaf);
	}
}