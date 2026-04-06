<?php
if(!defined('DOKU_INC')) define('DOKU_INC',realpath(dirname(__FILE__).'/../../').'/');
if(!defined('DOKU_PLUGIN')) define('DOKU_PLUGIN',DOKU_INC.'lib/plugins/');
require_once(DOKU_PLUGIN.'syntax.php');
require_once(__DIR__. '/../common.php');

class syntax_plugin_confightmlok_html extends HtmlOK_addendum {

    //function getType() { return 'disabled'; }
    //function getPType() { return 'normal'; }
    //function getAllowedTypes() { return array('disabled'); }   

	function connectTo ($mode) {
		$this->Lexer->addEntryPattern('<html>(?=.*</html>)', $mode, 'plugin_confightmlok_html');
	}

	function postConnect () {
		$this->Lexer->addExitPattern('</html>', 'plugin_confightmlok_html');
	}

	function render ($mode, Doku_Renderer $renderer, $data) {
		list ($state, $match) = $data;
		switch ($state) {
			case DOKU_LEXER_ENTER :
			break;

			case DOKU_LEXER_UNMATCHED :
			if ($this->htmlok_but_truly_ok()) {
			//if(in_array($mode, ['xhtml', 's5'], true)) {
				$renderer->doc .= $match;
			} else {
				// should be html2text($match)?
				$renderer->doc .= p_xhtml_cached_geshi($match, 'html4strict', 'code');
			}
			break;
			
			case DOKU_LEXER_EXIT:
			break;

		}
        return true;
    }
}
