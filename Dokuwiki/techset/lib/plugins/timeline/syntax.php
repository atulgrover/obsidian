<?php
if(!defined('DOKU_INC')) die();

class syntax_plugin_timeline extends DokuWiki_Syntax_Plugin {

    function getType() { return 'substition'; }
    function getPType() { return 'block'; }
    function getSort() { return 150; }

    function connectTo($mode) {
        $this->Lexer->addSpecialPattern('{{timeline>}}', $mode, 'plugin_timeline');
    }

    function handle($match, $state, $pos, Doku_Handler $handler) {
        return [];
    }

    function render($mode, Doku_Renderer $renderer, $data) {
        if ($mode != 'xhtml') return false;

        $htmlFile = DOKU_PLUGIN . 'timeline/assets/timeline.php';
        if (file_exists($htmlFile)) {
            ob_start();
            include($htmlFile);
            $renderer->doc .= ob_get_clean();
        } else {
            $renderer->doc .= '<p><b>Error:</b> timeline.php not found in plugin assets.</p>';
        }
        return true;
    }
}
