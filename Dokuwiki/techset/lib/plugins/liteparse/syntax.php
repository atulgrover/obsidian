<?php
if(!defined('DOKU_INC')) die();

class syntax_plugin_liteparse extends DokuWiki_Syntax_Plugin {

    public function getType() {
        return 'substition';
    }

    public function getSort() {
        return 299;
    }

    public function connectTo($mode) {
        // Match {{liteparse>url}} (for new imports)
        $this->Lexer->addSpecialPattern('\{\{liteparse>[^\}]+\}\}', $mode, 'plugin_liteparse');
        // Match cached JSON blocks
        $this->Lexer->addSpecialPattern('<liteparse-json[^>]*>.*?</liteparse-json>', $mode, 'plugin_liteparse');
    }

    public function handle($match, $state, $pos, Doku_Handler $handler) {
        // Check if this is a cached JSON block
        if (strpos($match, '<liteparse-json') === 0) {
            if (preg_match('/<liteparse-json hash="([^"]+)">\s*(\{.*?\})\s*<\/liteparse-json>/s', $match, $m)) {
                $json = json_decode($m[2], true);
                return array('cached' => true, 'data' => $json, 'hash' => $m[1]);
            }
        }

        // Extract URL from {{liteparse>url}}
        $url = substr($match, 12, -2);
        return array('url' => $url, 'cached' => false);
    }

    public function render($mode, Doku_Renderer $renderer, $data) {
        if ($mode !== 'xhtml') return false;

        // Add CSS for JSON viewer
        $this->addStyles($renderer);

        if (!empty($data['cached']) && !empty($data['data'])) {
            $json = $data['data'];
            $hash = $data['hash'];

            $renderer->doc .= '<div class="liteparse-container" id="liteparse-' . htmlspecialchars($hash) . '">' . "\n";

            // Header with metadata
            $renderer->doc .= '<div class="liteparse-header">' . "\n";
            $renderer->doc .= '<div class="liteparse-title">📄 ' . htmlspecialchars($json['filename'] ?? 'Document') . '</div>' . "\n";
            $renderer->doc .= '<div class="liteparse-meta-bar">' . "\n";
            $renderer->doc .= '<span class="liteparse-badge">Pages: ' . ($json['metadata']['totalPages'] ?? 0) . '</span>' . "\n";
            $renderer->doc .= '<span class="liteparse-badge">Characters: ' . number_format($json['metadata']['characterCount'] ?? 0) . '</span>' . "\n";
            $renderer->doc .= '<button class="liteparse-toggle" onclick="liteparseToggleAll(this)">Expand All</button>' . "\n";
            $renderer->doc .= '</div>' . "\n";
            $renderer->doc .= '</div>' . "\n";

            // Tab navigation
            $renderer->doc .= '<div class="liteparse-tabs">' . "\n";
            $renderer->doc .= '<button class="liteparse-tab active" onclick="liteparseShowTab(this, \'text\')">Text</button>' . "\n";
            $renderer->doc .= '<button class="liteparse-tab" onclick="liteparseShowTab(this, \'pages\')">Pages</button>' . "\n";
            $renderer->doc .= '<button class="liteparse-tab" onclick="liteparseShowTab(this, \'json\')">Raw JSON</button>' . "\n";
            $renderer->doc .= '</div>' . "\n";

            // Text content tab
            $renderer->doc .= '<div class="liteparse-tab-content active" id="liteparse-tab-text">' . "\n";
            $renderer->doc .= '<div class="liteparse-text">' . "\n";
            $renderer->doc .= $this->renderText($json['text'] ?? '');
            $renderer->doc .= '</div>' . "\n";
            $renderer->doc .= '</div>' . "\n";

            // Pages structure tab
            $renderer->doc .= '<div class="liteparse-tab-content" id="liteparse-tab-pages">' . "\n";
            $renderer->doc .= '<div class="liteparse-tree">' . "\n";
            if (!empty($json['pages'])) {
                foreach ($json['pages'] as $pageIndex => $page) {
                    $pageId = 'page-' . $pageIndex;
                    $paragraphCount = count($page['paragraphs'] ?? []);

                    $renderer->doc .= '<div class="liteparse-node">' . "\n";
                    $renderer->doc .= '<div class="liteparse-node-header" onclick="liteparseToggle(\'' . $pageId . '\')">' . "\n";
                    $renderer->doc .= '<span class="liteparse-icon">▶</span>' . "\n";
                    $renderer->doc .= '<span class="liteparse-label">Page ' . ($page['pageNum'] ?? $pageIndex + 1) . '</span>' . "\n";
                    $renderer->doc .= '<span class="liteparse-count">' . $paragraphCount . ' paragraphs</span>' . "\n";
                    $renderer->doc .= '</div>' . "\n";

                    $renderer->doc .= '<div class="liteparse-node-children" id="' . $pageId . '" style="display:none;">' . "\n";
                    if (!empty($page['paragraphs'])) {
                        foreach ($page['paragraphs'] as $paraIndex => $para) {
                            $paraId = $pageId . '-para-' . $paraIndex;
                            $text = htmlspecialchars($para['text'] ?? '');
                            $isHeading = $para['isHeading'] ?? false;
                            $headingLevel = $para['headingLevel'] ?? 0;
                            $lineCount = $para['lineCount'] ?? 1;

                            $renderer->doc .= '<div class="liteparse-item">' . "\n";
                            $renderer->doc .= '<div class="liteparse-item-header" onclick="liteparseToggle(\'' . $paraId . '\')">' . "\n";
                            $renderer->doc .= '<span class="liteparse-icon">▶</span>' . "\n";

                            // Show heading badge or paragraph indicator
                            if ($isHeading) {
                                $renderer->doc .= '<span class="liteparse-badge-heading">H' . $headingLevel . '</span>' . "\n";
                            }
                            $renderer->doc .= '<span class="liteparse-text-preview">' . $this->truncate($text, 80) . '</span>' . "\n";
                            $renderer->doc .= '<span class="liteparse-font-badge">' . round($para['avgFontSize'] ?? 12, 1) . 'pt, ' . $lineCount . ' line(s)</span>' . "\n";
                            $renderer->doc .= '</div>' . "\n";

                            $renderer->doc .= '<div class="liteparse-item-details" id="' . $paraId . '" style="display:none;">' . "\n";
                            $renderer->doc .= '<div class="liteparse-para-text">' . $text . '</div>' . "\n";
                            $renderer->doc .= '<table class="liteparse-table">' . "\n";
                            $renderer->doc .= '<tr><th>Type</th><td>' . ($isHeading ? 'Heading (H' . $headingLevel . ')' : 'Paragraph') . '</td></tr>' . "\n";
                            $renderer->doc .= '<tr><th>Lines</th><td>' . $lineCount . '</td></tr>' . "\n";
                            $renderer->doc .= '<tr><th>Font Size</th><td>' . round($para['avgFontSize'] ?? 12, 1) . 'pt (avg)</td></tr>' . "\n";
                            $renderer->doc .= '<tr><th>Position</th><td>x: ' . round($para['x'] ?? 0, 1) . ', y: ' . round($para['y'] ?? 0, 1) . '</td></tr>' . "\n";
                            $renderer->doc .= '<tr><th>Size</th><td>' . round($para['width'] ?? 0, 1) . ' × ' . round($para['height'] ?? 0, 1) . '</td></tr>' . "\n";
                            $renderer->doc .= '</table>' . "\n";
                            $renderer->doc .= '</div>' . "\n";
                            $renderer->doc .= '</div>' . "\n";
                        }
                    }
                    $renderer->doc .= '</div>' . "\n";
                    $renderer->doc .= '</div>' . "\n";
                }
            }
            $renderer->doc .= '</div>' . "\n";
            $renderer->doc .= '</div>' . "\n";

            // Raw JSON tab
            $renderer->doc .= '<div class="liteparse-tab-content" id="liteparse-tab-json">' . "\n";
            $renderer->doc .= '<pre class="liteparse-json-raw">' . htmlspecialchars(json_encode($json, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE)) . '</pre>' . "\n";
            $renderer->doc .= '</div>' . "\n";

            $renderer->doc .= '</div>' . "\n";
        } else {
            // Show import button for uncached content
            $url = $data['url'] ?? '';
            global $ID;

            $renderer->doc .= '<div class="liteparse-import-box">' . "\n";
            $renderer->doc .= '<div class="liteparse-import-icon">📄</div>' . "\n";
            $renderer->doc .= '<div class="liteparse-import-content">' . "\n";
            $renderer->doc .= '<strong>LiteParse Import</strong><br>' . "\n";
            $renderer->doc .= '<code>' . htmlspecialchars($this->truncate($url, 60)) . '</code><br><br>' . "\n";
            $renderer->doc .= '<button class="liteparse-btn" data-url="' . htmlspecialchars($url) . '" data-id="' . $ID . '">' . "\n";
            $renderer->doc .= '⬇️ Import Document</button>' . "\n";
            $renderer->doc .= '<span class="liteparse-status"></span>' . "\n";
            $renderer->doc .= '</div>' . "\n";
            $renderer->doc .= '</div>' . "\n";
        }

        return true;
    }

    private function addStyles($renderer) {
        static $stylesAdded = false;
        if ($stylesAdded) return;
        $stylesAdded = true;

        $css = '
.liteparse-container {
    border: 1px solid #ddd;
    border-radius: 8px;
    margin: 15px 0;
    background: #fff;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    overflow: hidden;
}
.liteparse-header {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 15px;
}
.liteparse-title {
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 10px;
}
.liteparse-meta-bar {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}
.liteparse-badge {
    background: rgba(255,255,255,0.2);
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 12px;
}
.liteparse-toggle {
    background: rgba(255,255,255,0.2);
    border: 1px solid rgba(255,255,255,0.3);
    color: white;
    padding: 4px 12px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
}
.liteparse-toggle:hover {
    background: rgba(255,255,255,0.3);
}
.liteparse-tabs {
    display: flex;
    background: #f5f5f5;
    border-bottom: 1px solid #ddd;
}
.liteparse-tab {
    padding: 10px 20px;
    border: none;
    background: transparent;
    cursor: pointer;
    font-size: 14px;
    border-bottom: 2px solid transparent;
    color: #666;
}
.liteparse-tab:hover {
    background: #eee;
}
.liteparse-tab.active {
    color: #667eea;
    border-bottom-color: #667eea;
    background: #fff;
}
.liteparse-tab-content {
    display: none;
    padding: 15px;
    max-height: 500px;
    overflow-y: auto;
}
.liteparse-tab-content.active {
    display: block;
}
.liteparse-text {
    white-space: pre-wrap;
    font-size: 13px;
    line-height: 1.6;
    background: #fafafa;
    padding: 15px;
    border-radius: 4px;
}
.liteparse-tree {
    font-size: 13px;
}
.liteparse-node {
    margin: 2px 0;
}
.liteparse-node-header {
    padding: 8px 10px;
    background: #f5f5f5;
    border-radius: 4px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 8px;
}
.liteparse-node-header:hover {
    background: #eee;
}
.liteparse-icon {
    font-size: 10px;
    width: 12px;
    transition: transform 0.2s;
}
.liteparse-node.open > .liteparse-node-header .liteparse-icon {
    transform: rotate(90deg);
}
.liteparse-label {
    font-weight: 500;
}
.liteparse-count {
    color: #888;
    font-size: 12px;
    margin-left: auto;
}
.liteparse-node-children {
    margin-left: 20px;
    padding-left: 10px;
    border-left: 2px solid #ddd;
}
.liteparse-item {
    margin: 3px 0;
}
.liteparse-item-header {
    padding: 6px 10px;
    background: #fff;
    border: 1px solid #eee;
    border-radius: 3px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 8px;
}
.liteparse-item-header:hover {
    border-color: #ccc;
}
.liteparse-text-preview {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.liteparse-large { font-weight: 600; color: #333; }
.liteparse-medium { color: #555; }
.liteparse-small { color: #777; font-size: 11px; }
.liteparse-font-badge {
    background: #e3f2fd;
    color: #1976d2;
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 11px;
}
.liteparse-item-details {
    margin: 5px 0 5px 20px;
    padding: 10px;
    background: #fafafa;
    border-radius: 4px;
    border: 1px solid #eee;
}
.liteparse-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
}
.liteparse-table th {
    text-align: left;
    width: 80px;
    color: #666;
    padding: 4px 0;
}
.liteparse-table td {
    padding: 4px 0;
}
.liteparse-more {
    color: #888;
    font-style: italic;
    padding: 10px;
    text-align: center;
}
.liteparse-badge-heading {
    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
    color: white;
    padding: 2px 8px;
    border-radius: 3px;
    font-size: 11px;
    font-weight: 600;
    margin-right: 8px;
}
.liteparse-para-text {
    background: #f8f9fa;
    padding: 10px;
    border-radius: 4px;
    margin-bottom: 10px;
    white-space: pre-wrap;
    font-size: 13px;
    line-height: 1.5;
    max-height: 150px;
    overflow-y: auto;
}
.liteparse-json-raw {
    background: #1e1e1e;
    color: #d4d4d4;
    padding: 15px;
    border-radius: 4px;
    font-size: 12px;
    overflow-x: auto;
    max-height: 400px;
}
.liteparse-import-box {
    display: flex;
    align-items: center;
    gap: 15px;
    padding: 20px;
    background: linear-gradient(135deg, #f5f7fa 0%, #e4e8ec 100%);
    border: 2px dashed #ccc;
    border-radius: 8px;
    margin: 15px 0;
}
.liteparse-import-icon {
    font-size: 40px;
}
.liteparse-import-content {
    flex: 1;
}
.liteparse-import-content code {
    background: #fff;
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 11px;
    word-break: break-all;
}
.liteparse-btn {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    border: none;
    padding: 10px 20px;
    border-radius: 5px;
    cursor: pointer;
    font-size: 14px;
}
.liteparse-btn:hover {
    opacity: 0.9;
}
.liteparse-status {
    margin-left: 10px;
    font-size: 13px;
}
';

        $renderer->doc .= '<style>' . $css . '</style>';

        // Add JavaScript for interactivity
        $js = '
<script>
function liteparseToggle(id) {
    var el = document.getElementById(id);
    var parent = el.parentElement.parentElement;
    if (el.style.display === "none") {
        el.style.display = "block";
        parent.classList.add("open");
    } else {
        el.style.display = "none";
        parent.classList.remove("open");
    }
}
function liteparseToggleAll(btn) {
    var container = btn.closest(".liteparse-container");
    var children = container.querySelectorAll(".liteparse-node-children");
    var isExpanded = btn.textContent.includes("Collapse");
    children.forEach(function(el) {
        el.style.display = isExpanded ? "none" : "block";
        var parent = el.parentElement;
        if (isExpanded) parent.classList.remove("open");
        else parent.classList.add("open");
    });
    btn.textContent = isExpanded ? "Expand All" : "Collapse All";
}
function liteparseShowTab(btn, tabName) {
    var container = btn.closest(".liteparse-container");
    container.querySelectorAll(".liteparse-tab").forEach(function(t) { t.classList.remove("active"); });
    container.querySelectorAll(".liteparse-tab-content").forEach(function(t) { t.classList.remove("active"); });
    btn.classList.add("active");
    document.getElementById("liteparse-tab-" + tabName).classList.add("active");
}
</script>
';
        $renderer->doc .= $js;
    }

    private function renderText($text) {
        $html = htmlspecialchars($text);
        $html = '<p>' . preg_replace('/\n\n+/', '</p><p>', $html) . '</p>';
        return $html;
    }

    private function truncate($str, $len) {
        if (strlen($str) <= $len) return $str;
        return substr($str, 0, $len) . '...';
    }
}