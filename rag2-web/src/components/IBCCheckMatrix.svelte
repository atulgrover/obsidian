<script lang="ts">
  import { lightrag, vault } from '../api/vault';
  import type { ComplianceResult, ComplianceCheckResponse } from '../api/vault';

  export let slug = '';

  let checking = false;
  let error = '';
  let result: ComplianceCheckResponse | null = null;
  let expandedRows = new Set<string>();

  const categories: Record<string, string> = {
    A: 'Corporate Debtor',
    B: 'Resolution Applicant',
    C: 'Resolution Plan Content',
    D: 'Feasibility & Viability',
    E: 'Compliance with Law',
    F: 'Additional Requirements',
  };

  $: grouped = groupByCategory(result?.results || []);

  function groupByCategory(results: ComplianceResult[]): Record<string, ComplianceResult[]> {
    const groups: Record<string, ComplianceResult[]> = {};
    for (const r of results) {
      const cat = r.id.charAt(0);
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(r);
    }
    return groups;
  }

  async function runCheck() {
    checking = true;
    error = '';
    try {
      result = await lightrag.complianceCheck(slug);
    } catch (e: any) {
      error = e.message;
    } finally {
      checking = false;
    }
  }

  function statusColor(status: string): string {
    const map: Record<string, string> = {
      compliant: '#22c55e', partial: '#f59e0b', non_compliant: '#ef4444', not_found: '#6b7280',
    };
    return map[status] || '#6b7280';
  }

  function statusLabel(status: string): string {
    const map: Record<string, string> = {
      compliant: '✓ Compliant', partial: '⚠ Partial', non_compliant: '✗ Non-Compliant', not_found: '— Not Found',
    };
    return map[status] || status;
  }

  function toggleRow(id: string) {
    if (expandedRows.has(id)) expandedRows.delete(id);
    else expandedRows.add(id);
    expandedRows = expandedRows;
  }

  function overallBadge(status: string): string {
    const map: Record<string, string> = {
      compliant: '#22c55e', partial: '#f59e0b', non_compliant: '#ef4444',
    };
    return map[status] || '#6b7280';
  }
</script>

<div class="ibc-check">
  <div class="header">
    <h2>IBC Compliance Check: {slug}</h2>
    <button on:click={runCheck} disabled={checking}>
      {checking ? 'Analysing with Sarvam AI...' : 'Run Compliance Check'}
    </button>
  </div>

  {#if error}
    <div class="error">{error}</div>
  {/if}

  {#if result}
    <!-- Summary bar -->
    <div class="summary-bar" style="border-left: 4px solid {overallBadge(result.overall_status)}">
      <div class="overall-status" style="color:{overallBadge(result.overall_status)}">
        {result.overall_status.replace('_', ' ').toUpperCase()}
      </div>
      <div class="counts">
        <span class="count compliant">✓ {result.compliant}</span>
        <span class="count partial">⚠ {result.partial}</span>
        <span class="count non-compliant">✗ {result.non_compliant}</span>
        <span class="count not-found">— {result.not_found}</span>
      </div>
      <div class="meta">{result.chunks_analyzed} chunks analysed · {result.duration_ms.toLocaleString()}ms · {result.checked_at}</div>
    </div>

    <!-- Category-grouped tables -->
    {#each Object.entries(grouped) as [cat, items]}
      <div class="category">
        <h3>{cat}. {categories[cat] || cat}</h3>
        <table>
          <thead><tr><th>ID</th><th>Requirement</th><th>Section</th><th>Status</th></tr></thead>
          <tbody>
            {#each items as item}
              <tr on:click={() => toggleRow(item.id)} class="clickable">
                <td class="req-id">{item.id}</td>
                <td>{item.requirement}</td>
                <td class="section">{item.section}</td>
                <td><span class="status" style="background:{statusColor(item.status)}">{statusLabel(item.status)}</span></td>
              </tr>
              {#if expandedRows.has(item.id)}
                <tr class="evidence-row"><td colspan="4">
                  {#if item.evidence}<details><summary>Evidence</summary><p>{item.evidence}</p></details>{/if}
                  {#if item.notes}<details><summary>Notes</summary><p>{item.notes}</p></details>{/if}
                </td></tr>
              {/if}
            {/each}
          </tbody>
        </table>
      </div>
    {/each}
  {:else if !checking}
    <div class="empty">
      <p>Click "Run Compliance Check" to evaluate this document against 20 mandatory IBC requirements.</p>
      <p class="sub">The document must be chunked and ingested first.</p>
    </div>
  {/if}
</div>

<style>
  .ibc-check { font-family: system-ui, sans-serif; }
  .header { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; background: linear-gradient(135deg, #1e3a5f, #1e1b4b); border-radius: 8px 8px 0 0; }
  .header h2 { margin: 0; color: #e0e7ff; font-size: 16px; }
  .header button { padding: 8px 20px; background: #4f46e5; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }
  .header button:disabled { opacity: 0.5; }
  .summary-bar { padding: 16px 20px; background: #1e1b4b; }
  .overall-status { font-size: 20px; font-weight: 700; text-transform: uppercase; }
  .counts { display: flex; gap: 16px; margin-top: 8px; }
  .count { font-size: 14px; }
  .count.compliant { color: #22c55e; } .count.partial { color: #f59e0b; }
  .count.non-compliant { color: #ef4444; } .count.not-found { color: #6b7280; }
  .meta { color: #6b7280; font-size: 12px; margin-top: 4px; }
  .category { margin: 16px 0; }
  .category h3 { color: #a78bfa; font-size: 14px; margin: 0 0 8px; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; padding: 8px 12px; background: #1e1b4b; color: #a78bfa; font-size: 12px; text-transform: uppercase; }
  td { padding: 8px 12px; border-bottom: 1px solid #312e81; color: #e0e7ff; font-size: 13px; }
  tr.clickable { cursor: pointer; }
  tr.clickable:hover { background: rgba(79, 70, 229, 0.1); }
  .req-id { font-family: monospace; color: #818cf8; }
  .section { color: #6b7280; font-size: 12px; }
  .status { padding: 2px 10px; border-radius: 10px; font-size: 12px; color: white; }
  .evidence-row td { background: #0f0d2e; }
  .evidence-row details { margin: 4px 0; }
  .evidence-row p { font-size: 13px; color: #c4b5fd; line-height: 1.5; }
  .empty { text-align: center; padding: 40px; color: #6b7280; }
  .sub { font-size: 13px; }
  .error { color: #f87171; padding: 16px; }
</style>