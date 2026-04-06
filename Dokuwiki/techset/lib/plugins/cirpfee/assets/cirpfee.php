<?php
if(!defined('DOKU_INC')) die();
?>

<div id="cirpfee-calculator" style="padding:1rem; border:1px solid #ccc; max-width:1000px; overflow-x:auto;">
    <h2>CIRP Fee Calculator</h2>

    <form id="feeForm">
        <table border="1" cellspacing="0" cellpadding="5" style="border-collapse:collapse;width:100%;">
            <thead>
                <tr>
                    <th>Category</th>
                    <th>Sub-Parameter</th>
                    <th>Quantity</th>
                    <th>Base Hours</th>
                    <th>Complexity Factor</th>
                </tr>
            </thead>
            <tbody>
                <?php
                $fields = [
                    ["Corporate Complexity","Stalled Projects","cc_proj",10,1],
                    ["Corporate Complexity","Subsidiaries / SPVs","cc_subs",8,1],
                    ["Legal & Regulatory","Ongoing Litigations","lr_lit",15,1.5],
                    ["Legal & Regulatory","Regulatory Compliance","lr_comp",12,1.2],
                    ["Financial Complexity","Number of Claims","fc_claims",5,1.1],
                    ["Financial Complexity","Resolution Plan Preparation","fc_plan",20,1.3],
                    ["Project Management","Construction / Site Work","pm_site",15,1.2],
                    ["Stakeholder Management","CoC Meetings","sm_coc",10,1.1],
                    ["Ancillary Work","Document Collection","aw_docs",6,1.1],
                    ["Risk & Liability","Personal Liability Factor","risk_liab",20,1.5],
                    ["Timeline & Work Intensity","Expected Duration (Months)","tw_months",160,1]
                ];

                foreach($fields as $f):
                    $id = htmlspecialchars($f[2]);
                ?>
                <tr>
                    <td><?= htmlspecialchars($f[0]) ?></td>
                    <td><?= htmlspecialchars($f[1]) ?></td>
                    <td><input type="number" step="0.1" id="<?= $id ?>" value="<?= $f[3] ?>" style="width:80px"></td>
                    <td><input type="number" step="0.1" id="<?= $id ?>_h" value="<?= $f[3] ?>" style="width:80px"></td>
                    <td><input type="number" step="0.1" id="<?= $id ?>_f" value="<?= $f[4] ?>" style="width:80px"></td>
                </tr>
                <?php endforeach; ?>
            </tbody>
        </table>
        <br>
        <button type="button" onclick="calculateFee()">Calculate Fee</button>
    </form>

    <h3 id="feeResult"></h3>
</div>

<script>
function calculateFee() {
    const fields = [
        "cc_proj","cc_subs","lr_lit","lr_comp","fc_claims","fc_plan",
        "pm_site","sm_coc","aw_docs","risk_liab","tw_months"
    ];

    let total = 0;
    fields.forEach(f => {
        const qty = parseFloat(document.getElementById(f).value) || 0;
        const hours = parseFloat(document.getElementById(f+"_h").value) || 0;
        const factor = parseFloat(document.getElementById(f+"_f").value) || 1;
        total += qty * hours * factor;
    });

    const months = parseFloat(document.getElementById("tw_months").value) || 1;
    const hourly = 3000; // arbitrary hourly rate
    const monthly = (total * hourly) / months;

    document.getElementById("feeResult").innerText = "Estimated Monthly Fee: ₹ " + monthly.toLocaleString();
}
</script>
