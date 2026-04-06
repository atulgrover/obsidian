<?php
if(!defined('DOKU_INC')) die();

class syntax_plugin_kanbantasks extends DokuWiki_Syntax_Plugin {

    function getType() { return 'substition'; }
    function getPType() { return 'block'; }
    function getSort() { return 150; }

    function connectTo($mode) {
        $this->Lexer->addSpecialPattern('{{kanbantasks>}}', $mode, 'plugin_kanbantasks');
    }

    function handle($match, $state, $pos, Doku_Handler $handler) {
        return [];
    }

    function render($mode, Doku_Renderer $renderer, $data) {
        if ($mode != 'xhtml') return false;

        $assetsDir = DOKU_PLUGIN . 'kanbantasks/assets/';
        if (!is_dir($assetsDir)) {
            $renderer->doc .= '<p><b>Error:</b> assets folder not found.</p>';
            return true;
        }

        $files = glob($assetsDir . '*.csv');
        if (!$files) {
            $renderer->doc .= '<p><b>No CSV files found in assets folder.</b></p>';
            return true;
        }

        $fileOptions = [];
        foreach ($files as $file) {
            $basename = basename($file);
            $name = ucwords(str_replace(['_', '-', '.csv'], [' ', ' ', ''], $basename));
            $fileOptions[] = ['file' => $basename, 'name' => $name];
        }

        ob_start();
        ?>
        <div id="kanban-tasks" style="font-family:Arial, sans-serif; background:#fff; padding:20px; border-radius:10px; box-shadow:0 2px 5px rgba(0,0,0,0.1);">
          <h2 style="margin-bottom:15px;">Kanban Task Lists</h2>

          <label><b>Select Task File:</b></label>
          <select id="fileSelect" style="margin-left:10px; padding:6px;">
            <option value="">-- Select a CSV file --</option>
            <?php foreach($fileOptions as $opt): ?>
              <option value="<?php echo hsc($opt['file']); ?>"><?php echo hsc($opt['name']); ?></option>
            <?php endforeach; ?>
          </select>

          <div id="searchBar" style="margin-top:15px; display:none;">
            <input type="text" id="searchInput" placeholder="Search by subject or swimlane..." style="width:100%; padding:8px; border:1px solid #ccc; border-radius:5px;">
          </div>

          <div id="taskTable" style="margin-top:20px;"></div>
          <button id="downloadBtn" style="margin-top:15px; padding:10px 15px; background:#2563eb; color:#fff; border:none; border-radius:6px; cursor:pointer; display:none;">Download Selected CSV</button>
        </div>

        <script>
        (function(){
            const selectEl = document.getElementById('fileSelect');
            const tableEl = document.getElementById('taskTable');
            const downloadBtn = document.getElementById('downloadBtn');
            const searchBar = document.getElementById('searchBar');
            const searchInput = document.getElementById('searchInput');
            const baseURL = '<?php echo DOKU_BASE . "lib/plugins/kanbantasks/assets/"; ?>';

            let allData = [];

            // Universal CSV parser
            function parseCSV(text) {
                const rows = [];
                let lines = text.trim().split(/\r?\n/);
                if (!lines.length) return [];
                const sep = (text.includes(';') && !text.includes(',')) ? ';' : ',';
                const headers = lines.shift().split(sep).map(h => h.trim().replace(/^"|"$/g, ''));
                for (let line of lines) {
                    if (!line.trim()) continue;
                    const cols = line.split(sep).map(c => c.trim().replace(/^"|"$/g, ''));
                    const obj = {};
                    headers.forEach((h,i)=> obj[h.toLowerCase()] = cols[i] || '');
                    rows.push(obj);
                }
                return rows;
            }

            async function loadCSV(file) {
                try {
                    const response = await fetch(baseURL + file);
                    if (!response.ok) throw new Error('HTTP ' + response.status);
                    const text = await response.text();
                    return parseCSV(text);
                } catch (err) {
                    console.error('Error reading CSV:', err);
                    return [];
                }
            }

            function renderTable(data) {
                if (!data || !data.length) {
                    tableEl.innerHTML = '<p style="color:#666;">No tasks available or invalid CSV structure.</p>';
                    downloadBtn.style.display = 'none';
                    searchBar.style.display = 'none';
                    return;
                }
                const rows = data.map((r,i)=>`
                    <tr>
                      <td style='padding:6px;'>${i+1}</td>
                      <td style='padding:6px;'>${r.subject || ''}</td>
                      <td style='padding:6px;'>${r.swimlane || ''}</td>
                    </tr>`).join('');
                tableEl.innerHTML = `
                    <table style='width:100%; border-collapse:collapse; font-size:14px;'>
                        <thead style='background:#f3f4f6;'>
                            <tr><th style='padding:6px;text-align:left;'>#</th><th style='padding:6px;text-align:left;'>Subject</th><th style='padding:6px;text-align:left;'>Swimlane</th></tr>
                        </thead><tbody>${rows}</tbody>
                    </table>`;
                downloadBtn.style.display = 'inline-block';
                searchBar.style.display = 'block';
            }

            selectEl.addEventListener('change', async ()=>{
                const file = selectEl.value;
                if (!file) { 
                    tableEl.innerHTML = ''; 
                    downloadBtn.style.display='none'; 
                    searchBar.style.display='none';
                    return; 
                }
                allData = await loadCSV(file);
                renderTable(allData);

                downloadBtn.onclick = ()=>{
                    const link = document.createElement('a');
                    link.href = baseURL + file;
                    link.download = file;
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                };
            });

            // Live search filter
            searchInput.addEventListener('input', ()=>{
                const term = searchInput.value.toLowerCase();
                const filtered = allData.filter(r =>
                    (r.subject && r.subject.toLowerCase().includes(term)) ||
                    (r.swimlane && r.swimlane.toLowerCase().includes(term))
                );
                renderTable(filtered);
            });
        })();
        </script>
        <?php
        $renderer->doc .= ob_get_clean();
        return true;
    }
}
