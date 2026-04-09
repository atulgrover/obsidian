/**
 * Shared plugin settings for RAG2 Obsidian plugins.
 * All 5 plugins share the same service URL configuration.
 */

import { PluginSettingTab, App, Setting } from 'obsidian';

export interface RAG2Settings {
	vaultPipelineUrl: string;  // e.g. http://localhost:5004
	lightragUrl: string;       // e.g. http://localhost:8020
	sbertUrl: string;          // e.g. http://localhost:8021
}

export const DEFAULT_SETTINGS: RAG2Settings = {
	vaultPipelineUrl: 'http://localhost:5004',
	lightragUrl: 'http://localhost:8020',
	sbertUrl: 'http://localhost:8021',
};

export class RAG2SettingTab extends PluginSettingTab {
	plugin: { settings: RAG2Settings; saveSettings: () => Promise<void> };

	constructor(app: App, plugin: { settings: RAG2Settings; saveSettings: () => Promise<void> }) {
		super(app, plugin as any);
		this.plugin = plugin;
	}

	display(): void {
		const { containerEl } = this;
		containerEl.empty();

		containerEl.createEl('h2', { text: 'RAG2 Service URLs' });

		new Setting(containerEl)
			.setName('Vault Pipeline URL')
			.setDesc('vault-pipeline service (port 5004)')
			.addText(text => text
				.setValue(this.plugin.settings.vaultPipelineUrl)
				.onChange(async (value) => {
					this.plugin.settings.vaultPipelineUrl = value;
					await this.plugin.saveSettings();
				}));

		new Setting(containerEl)
			.setName('LightRAG URL')
			.setDesc('LightRAG service (port 8020)')
			.addText(text => text
				.setValue(this.plugin.settings.lightragUrl)
				.onChange(async (value) => {
					this.plugin.settings.lightragUrl = value;
					await this.plugin.saveSettings();
				}));

		new Setting(containerEl)
			.setName('SBERT URL')
			.setDesc('InLegal-SBERT embedding service (port 8021)')
			.addText(text => text
				.setValue(this.plugin.settings.sbertUrl)
				.onChange(async (value) => {
					this.plugin.settings.sbertUrl = value;
					await this.plugin.saveSettings();
				}));
	}
}

/**
 * Generic API helper — POST JSON and return parsed response.
 */
export async function api<T>(url: string, body?: unknown): Promise<T> {
	const resp = await fetch(url, {
		method: body ? 'POST' : 'GET',
		headers: body ? { 'Content-Type': 'application/json' } : {},
		body: body ? JSON.stringify(body) : undefined,
	});
	if (!resp.ok) {
		const detail = await resp.json().catch(() => resp.statusText);
		throw new Error(detail?.detail || detail?.message || `HTTP ${resp.status}`);
	}
	return resp.json();
}

/**
 * Upload a file (PDF) to vault-pipeline.
 */
export async function uploadFile(url: string, file: File, fields?: Record<string, string>): Promise<any> {
	const form = new FormData();
	form.append('file', file);
	if (fields) {
		for (const [k, v] of Object.entries(fields)) form.append(k, v);
	}
	const resp = await fetch(url, { method: 'POST', body: form });
	if (!resp.ok) {
		const detail = await resp.json().catch(() => resp.statusText);
		throw new Error(detail?.detail || `HTTP ${resp.status}`);
	}
	return resp.json();
}

/**
 * Read vault note frontmatter via app.vault.
 */
export async function readFrontmatter(app: App, path: string): Promise<Record<string, any> | null> {
	const file = app.vault.getFileByPath(path);
	if (!file) return null;
	const content = await app.vault.read(file);
	const match = content.match(/^---\n([\s\S]*?)\n---/);
	if (!match) return null;
	// Simple YAML parser for frontmatter (handles basic types)
	const meta: Record<string, any> = {};
	for (const line of match[1].split('\n')) {
		const colonIdx = line.indexOf(':');
		if (colonIdx === -1) continue;
		const key = line.slice(0, colonIdx).trim();
		let val: any = line.slice(colonIdx + 1).trim();
		// Parse basic types
		if (val.startsWith('[')) {
			try { val = JSON.parse(val.replace(/'/g, '"')); } catch { /* keep as string */ }
		} else if (val === 'true') { val = true; }
		else if (val === 'false') { val = false; }
		else if (val === 'null') { val = null; }
		else if (/^\d+$/.test(val)) { val = parseInt(val); }
		else if (/^\d+\.\d+$/.test(val)) { val = parseFloat(val); }
		else if (val.startsWith('"') && val.endsWith('"')) { val = val.slice(1, -1); }
		meta[key] = val;
	}
	return meta;
}

/**
 * Update vault note frontmatter (preserves body).
 */
export async function updateFrontmatter(
	app: App,
	path: string,
	updates: Record<string, any>,
): Promise<void> {
	const file = app.vault.getFileByPath(path);
	if (!file) return;
	const content = await app.vault.read(file);
	const match = content.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
	if (!match) return;

	// Build new frontmatter
	let fm = match[1];
	for (const [key, value] of Object.entries(updates)) {
		const regex = new RegExp(`^${key}:.*$`, 'm');
		const line = `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`;
		if (regex.test(fm)) {
			fm = fm.replace(regex, line);
		} else {
			fm += `\n${line}`;
		}
	}
	const newContent = `---\n${fm}\n---\n${match[2]}`;
	await app.vault.modify(file, newContent);
}