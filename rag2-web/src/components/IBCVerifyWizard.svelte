<script lang="ts">
  import { lightrag } from '../api/vault';

  export let slug = '';

  let step = 1; // 1=setup, 2=index, 3=verify
  let loading = false;
  let error = '';
  let planId = '';
  let result: Record<string, unknown> | null = null;

  // Setup form fields
  let company = '';
  let applicant = '';
  let applicantType = 'strategic';
  let considerationCrore = '';
  let upfrontCrore = '';
  let ncltBench = '';
  let caseNumber = '';

  // Human verification
  let humanOverrides: Record<string, string> = {};

  async function setupMatter() {
    loading = true;
    error = '';
    try {
      const resp = await lightrag.matterSetup({
        company,
        source: slug,
        applicant: applicant || undefined,
        applicant_type: applicantType,
        consideration_crore: considerationCrore ? parseFloat(considerationCrore) : undefined,
        upfront_crore: upfrontCrore ? parseFloat(upfrontCrore) : undefined,
        nclt_bench: ncltBench || undefined,
        case_number: caseNumber || undefined,
      });
      planId = resp.plan_id;
      step = 2;
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function indexPlan() {
    loading = true;
    error = '';
    try {
      await lightrag.matterPlanIndex(planId, slug);
      step = 3;
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function verify() {
    loading = true;
    error = '';
    try {
      result = await lightrag.matterPlanVerify(planId);
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function humanVerify(reqId: string, status: string) {
    try {
      await lightrag.matterComplianceHuman(planId, reqId, status);
      humanOverrides[reqId] = status;
      humanOverrides = humanOverrides;
    } catch (e: any) {
      error = e.message;
    }
  }

  function confidenceColor(conf: number): string {
    if (conf >= 0.72) return '#22c55e';
    if (conf >= 0.55) return '#f59e0b';
    return '#6b7280';
  }

  const reqCategories: Record<string, string> = {
    A: 'Corporate Debtor', B: 'Resolution Applicant', C: 'Resolution Plan Content',
    D: 'Feasibility & Viability', E: 'Compliance with Law', F: 'Additional Requirements',
  };
</script>

<div class="ibc-verify">
  <div class="header">
    <h2>IBC Verification: {slug}</h2>
    <div class="step-indicator">
      <span class:active={step >= 1}>1. Setup</span>
      <span class:active={step >= 2}>2. Index</span>
      <span class:active={step >= 3}>3. Verify</span>
    </div>
  </div>

  {#if error}
    <div class="error">{error}</div>
  {/if}

  <!-- Step 1: Setup -->
  {#if step === 1}
    <div class="step-content">
      <h3>Register Matter & Plan</h3>
      <div class="form-grid">
        <label>Corporate Debtor *<input type="text" bind:value={company} placeholder="Company name" /></label>
        <label>Resolution Applicant<input type="text" bind:value={applicant} /></label>
        <label>Applicant Type
          <select bind:value={applicantType}>
            <option value="strategic">Strategic</option>
            <option value="financial_investor">Financial Investor</option>
            <option value="promoter">Promoter</option>
          </select>
        </label>
        <label>Total Consideration (₹ Cr)<input type="number" bind:value={considerationCrore} /></label>
        <label>Upfront Cash (₹ Cr)<input type="number" bind:value={upfrontCrore} /></label>
        <label>NCLT Bench<input type="text" bind:value={ncltBench} placeholder="e.g. Mumbai" /></label>
        <label>Case Number<input type="text" bind:value={caseNumber} /></label>
      </div>
      <button on:click={setupMatter} disabled={loading || !company}>
        {loading ? 'Registering...' : 'Register & Continue'}
      </button>
    </div>

  <!-- Step 2: Index -->
  {:else if step === 2}
    <div class="step-content">
      <h3>Index Plan Sections</h3>
      <p>Plan ID: <code>{planId}</code></p>
      <p>Embedding plan sections via InLegal-SBERT for deterministic vector matching.</p>
      <button on:click={indexPlan} disabled={loading}>
        {loading ? 'Indexing...' : 'Index Plan Sections'}
      </button>
    </div>

  <!-- Step 3: Verify -->
  {:else if step === 3}
    <div class="step-content">
      <h3>Verify Compliance</h3>
      <button on:click={verify} disabled={loading}>
        {loading ? 'Verifying...' : 'Run Verification'}
      </button>

      {#if result}
        {@const compliance = (result.compliance || []) as Array<Record<string, unknown>>}
        {@const summary = result as Record<string, unknown>}
        <div class="summary-bar" style="border-left:4px solid {summary.overall_status === 'materially_compliant' ? '#22c55e' : '#f59e0b'}">
          <div class="overall">{String(summary.overall_status || '').replace(/_/g, ' ').toUpperCase()}</div>
          <div class="counts">
            <span style="color:#22c55e">✓ {summary.compliant || 0}</span>
            <span style="color:#f59e0b">⚠ {summary.partial || 0}</span>
            <span style="color:#ef4444">✗ {summary.non_compliant || 0}</span>
            <span style="color:#6b7280">— {summary.not_found || 0}</span>
          </div>
        </div>

        <table>
          <thead><tr><th>ID</th><th>Requirement</th><th>Match</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {#each compliance as item}
              {@const conf = Number(item.confidence || 0)}
              {@const reqId = String(item.id || '')}
              <tr>
                <td class="req-id">{reqId}</td>
                <td>{String(item.requirement || '')}</td>
                <td>
                  {#if item.matched_heading}
                    <span class="match">{String(item.matched_heading)}</span>
                    <div class="conf-bar" style="width:{conf * 100}%; background:{confidenceColor(conf)}"></div>
                    <span class="conf-pct">{Math.round(conf * 100)}%</span>
                  {:else}
                    <span class="no-match">No match</span>
                  {/if}
                </td>
                <td><span class="status-badge" style="background:{confidenceColor(conf)}">{String(item.status || '')}</span></td>
                <td class="actions">
                  {#if humanOverrides[reqId]}
                    <span class="overridden">✓ {humanOverrides[reqId]}</span>
                  {:else}
                    <button class="v-btn v-yes" on:click={() => humanVerify(reqId, 'compliant')}>✓</button>
                    <button class="v-btn v-part" on:click={() => humanVerify(reqId, 'partial')}>⚠</button>
                    <button class="v-btn v-no" on:click={() => humanVerify(reqId, 'non_compliant')}>✗</button>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>
  {/if}
</div>

<style>
  .ibc-verify { font-family: system-ui, sans-serif; }
  .header { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; background: linear-gradient(135deg, #1e3a5f, #1e1b4b); border-radius: 8px 8px 0 0; }
  .header h2 { margin: 0; color: #e0e7ff; font-size: 16px; }
  .step-indicator { display: flex; gap: 12px; }
  .step-indicator span { color: #6b7280; font-size: 13px; }
  .step-indicator span.active { color: #a78bfa; font-weight: 600; }
  .step-content { padding: 20px; }
  .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 16px 0; }
  .form-grid label { display: flex; flex-direction: column; gap: 4px; color: #c4b5fd; font-size: 13px; }
  .form-grid input, .form-grid select { padding: 8px 12px; background: #1e1b4b; border: 1px solid #312e81; border-radius: 6px; color: #e0e7ff; font-size: 14px; }
  button { padding: 8px 20px; background: #4f46e5; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }
  button:disabled { opacity: 0.5; }
  .summary-bar { padding: 16px; margin: 16px 0; background: #1e1b4b; border-radius: 6px; }
  .overall { font-size: 20px; font-weight: 700; color: #e0e7ff; }
  .counts { display: flex; gap: 16px; margin-top: 8px; }
  table { width: 100%; border-collapse: collapse; margin-top: 16px; }
  th { text-align: left; padding: 8px; background: #1e1b4b; color: #a78bfa; font-size: 11px; text-transform: uppercase; }
  td { padding: 8px; border-bottom: 1px solid #312e81; color: #e0e7ff; font-size: 13px; }
  .req-id { font-family: monospace; color: #818cf8; }
  .match { color: #c4b5fd; font-size: 13px; }
  .conf-bar { height: 4px; border-radius: 2px; margin-top: 2px; }
  .conf-pct { font-size: 11px; color: #6b7280; }
  .no-match { color: #6b7280; }
  .status-badge { padding: 2px 8px; border-radius: 10px; font-size: 11px; color: white; }
  .actions { display: flex; gap: 4px; }
  .v-btn { padding: 2px 8px; font-size: 12px; border: none; border-radius: 4px; cursor: pointer; }
  .v-yes { background: #22c55e; color: white; } .v-part { background: #f59e0b; color: white; }
  .v-no { background: #ef4444; color: white; }
  .overridden { color: #22c55e; font-size: 12px; }
  .error { color: #f87171; padding: 16px; }
</style>