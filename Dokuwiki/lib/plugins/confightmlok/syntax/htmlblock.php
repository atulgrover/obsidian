<?php
if(!defined('DOKU_INC')) define('DOKU_INC',realpath(dirname(__FILE__).'/../../').'/');
if(!defined('DOKU_PLUGIN')) define('DOKU_PLUGIN',DOKU_INC.'lib/plugins/');
require_once(DOKU_PLUGIN.'syntax.php');
require_once(__DIR__. '/../common.php');

class syntax_plugin_confightmlok_htmlblock extends HtmlOK_addendum {

    //function getType() { return 'disabled'; }
    //function getPType() { return 'normal'; }
    //function getAllowedTypes() { return array('disabled'); }   

	function connectTo ($mode) {
		$this->Lexer->addEntryPattern('<HTML>(?=.*</HTML>)', $mode, 'plugin_confightmlok_htmlblock');
	}

	function postConnect () {
		$this->Lexer->addExitPattern('</HTML>', 'plugin_confightmlok_htmlblock');
	}

	function render($mode, Doku_Renderer $renderer, $data) {
		list ($state, $match) = $data;
		$wrapper= 'pre';
		switch ($state) {
			case DOKU_LEXER_ENTER :
			break;

			//case DOKU_LEXER_UNMATCHED :
			case DOKU_LEXER_UNMATCHED :
			if ($this->htmlok_but_truly_ok()) {
				$renderer->doc .= '<div>'. $match. '</div>';
			} else {
				// should be html2text($match)
				$renderer->doc .= p_xhtml_cached_geshi($match, 'html4strict', $wrapper);
			}
			break;
			
			case DOKU_LEXER_EXIT:
			//$renderer->doc.= "~3$match~";
			break;

		}
        return true;
    }
}
