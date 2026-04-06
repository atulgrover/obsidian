<?php if(!defined('DOKU_INC')) die(); ?>
<div id="timeline-app" style="font-family:Arial, sans-serif; background:#fff; padding:20px; border-radius:10px; box-shadow:0 2px 5px rgba(0,0,0,0.1);">
  <h2 style="font-size:20px; font-weight:bold; margin-bottom:10px;">Insolvency Process Timeline Generator</h2>

  <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px,1fr)); gap:10px; margin-bottom:20px;">
    <div>
      <label>Process Type:</label>
      <select id="processType" style="width:100%; padding:6px;">
        <option value="resolution">Resolution Process</option>
        <option value="liquidation">Liquidation Process</option>
      </select>
    </div>
    <div>
      <label>Start Date (T):</label>
      <input type="date" id="startDate" style="width:100%; padding:6px;">
    </div>
    <div>
      <label>Insolvency Professional:</label>
      <input type="text" id="ipName" placeholder="e.g., Atul Grover" style="width:100%; padding:6px;">
    </div>
    <div>
      <label>Assignment Title:</label>
      <input type="text" id="assignmentTitle" placeholder="e.g., XYZ Steels CIRP" style="width:100%; padding:6px;">
    </div>
  </div>

  <div id="timeline-table"></div>
  <button id="downloadBtn" style="margin-top:15px; padding:10px 15px; background:#2563eb; color:#fff; border:none; border-radius:6px; cursor:pointer;">Download .ICS File</button>
</div>

<script>
(function() {
  const processTypeEl = document.getElementById('processType');
  const startDateEl = document.getElementById('startDate');
  const ipNameEl = document.getElementById('ipName');
  const assignmentEl = document.getElementById('assignmentTitle');
  const tableEl = document.getElementById('timeline-table');
  const downloadBtn = document.getElementById('downloadBtn');

  const resolutionEvents = [
    { label: "Commencement of CIRP (T)", days: 0 },
    { label: "Public announcement inviting claims", days: 3 },
    { label: "Submission of claims (initial window)", days: 14 },
    { label: "Verification of claims under reg 12(1)", days: 21 },
    { label: "Application for AR / CoC constitution", days: 23 },
    { label: "1st CoC meeting / RP appointment", days: 30 },
    { label: "RP appointment (if later)", days: 40 },
    { label: "Appointment of valuer", days: 47 },
    { label: "Publish Form G / Invite EoI", days: 60 },
    { label: "Submission of EoI", days: 75 },
    { label: "Provisional list of RAs", days: 85 },
    { label: "Final list of RAs", days: 100 },
    { label: "Issue of RFRP, IM & Evaluation Matrix", days: 105 },
    { label: "Receipt of Resolution Plans", days: 135 },
    { label: "Submission to Adjudicating Authority", days: 165 },
    { label: "Approval by Adjudicating Authority", days: 180 },
  ];

  const liquidationEvents = [
    { label: "Commencement of Liquidation (T)", days: 0 },
    { label: "Public Announcement", days: 5 },
    { label: "Submission of Claims", days: 30 },
    { label: "Verification of Claims", days: 60 },
    { label: "Constitution of SCC", days: 60 },
    { label: "Preliminary Report", days: 75 },
    { label: "Asset Memorandum", days: 75 },
    { label: "Valuation (if required)", days: 90 },
    { label: "Quarterly Progress Report", days: 90 },
    { label: "Distribution of Proceeds", days: 180 },
    { label: "Final Report & Dissolution Application", days: 365 },
  ];

  function addDays(dateStr, days) {
    const d = new Date(dateStr);
    d.setDate(d.getDate() + days);
    return d.toISOString().slice(0, 10);
  }

  function renderTable() {
    const start = startDateEl.value;
    const type = processTypeEl.value;
    const events = (type === 'resolution') ? resolutionEvents : liquidationEvents;
    if (!start) { tableEl.innerHTML = '<p style="color:#555;">Select start date to view timeline.</p>'; return; }

    const rows = events.map((e, i) => {
      const date = addDays(start, e.days);
      return `<tr>
        <td style="padding:6px;">${i+1}</td>
        <td style="padding:6px;">${e.label}</td>
        <td style="padding:6px;">T+${e.days}</td>
        <td style="padding:6px; font-family:monospace;">${date}</td>
      </tr>`;
    }).join('');

    tableEl.innerHTML = `
      <table style="width:100%; border-collapse:collapse; font-size:14px;">
        <thead style="background:#f3f4f6;">
          <tr><th style="padding:6px;text-align:left;">#</th><th style="padding:6px;text-align:left;">Event</th><th style="padding:6px;text-align:left;">Offset</th><th style="padding:6px;text-align:left;">Date</th></tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  }

  function generateICS(events, title, ip, type) {
    const header = "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Timeline Generator//EN";
    const footer = "END:VCALENDAR";
    const body = events.map((ev, i) => {
      const start = ev.date.replace(/-/g,"");
      return [
        "BEGIN:VEVENT",
        "UID:" + i + "@timeline",
        "DTSTAMP:" + start + "T090000Z",
        "DTSTART;VALUE=DATE:" + start,
        "SUMMARY:" + title + " (" + type + ") — " + ev.label,
        "DESCRIPTION:Insolvency Professional: " + ip,
        "END:VEVENT"
      ].join("\n");
    }).join("\n");
    return header + "\n" + body + "\n" + footer;
  }

  function downloadICS() {
    const start = startDateEl.value, ip = ipNameEl.value || "N/A", title = assignmentEl.value || "Assignment", type = processTypeEl.value;
    if (!start) { alert("Please select Start Date."); return; }
    const events = (type === 'resolution' ? resolutionEvents : liquidationEvents).map(e => ({...e, date:addDays(start,e.days)}));
    const data = generateICS(events, title, ip, type);
    const blob = new Blob([data], {type:'text/calendar'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${title.replace(/\s+/g,'_')}_${type}_timeline.ics`;
    a.click();
    URL.revokeObjectURL(url);
  }

  startDateEl.addEventListener('change', renderTable);
  processTypeEl.addEventListener('change', renderTable);
  downloadBtn.addEventListener('click', downloadICS);
})();
</script>
