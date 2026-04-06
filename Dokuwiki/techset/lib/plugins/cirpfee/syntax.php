<?php
if(!defined('DOKU_INC')) die();

class syntax_plugin_cirpfee extends DokuWiki_Syntax_Plugin {

    function getType() { return 'substition'; }
    function getPType() { return 'block'; }
    function getSort() { return 150; }

    function connectTo($mode) {
        // Match {{CIRPFEE}} exactly (no “>”)
        $this->Lexer->addSpecialPattern('{{CIRPFEE}}', $mode, 'plugin_cirpfee');
    }

    function handle($match, $state, $pos, Doku_Handler $handler) {
        return [];
    }

    function render($mode, Doku_Renderer $renderer, $data) {
        if ($mode != 'xhtml') return false;

        $htmlFile = DOKU_PLUGIN . 'cirpfee/assets/cirpfee.php';

        if (file_exists($htmlFile)) {
            ob_start();
            include($htmlFile);
            $renderer->doc .= ob_get_clean();
        } else {
            $renderer->doc .= '<p><b>Error:</b> cirpfee.php not found in plugin assets.</p>';
        }
        return true;
    }
}
