<?php
if(!defined('DOKU_INC')) define('DOKU_INC',realpath(dirname(__FILE__).'/../../').'/');
if(!defined('DOKU_PLUGIN')) define('DOKU_PLUGIN',DOKU_INC.'lib/plugins/');
require_once(DOKU_PLUGIN.'syntax.php');

// compare 
// https://github.com/splitbrain/dokuwiki/pull/3798/files#diff-04c8b615576808e5dc67098f688fe22149d1413014752bf15234c0569690e984

function confightmlok_default_sanitizer ($text) {
	return $text;
}

// from Html.php

class HtmlOK_addendum extends DokuWiki_Syntax_Plugin {
	//public $sanitizer= null;

    function getSort() { return 190;  }
    function getType() { return 'disabled';  }
    function getAllowedTypes() { return array(); }
	//! check if we really, REALLY want to enable HTML
	function htmlok_but_truly_ok () {
		// are you sure?
		if (intval($this->getConf('use_sure')) < 1) return false;
		// are you *really* sure?
		if (intval($this->getConf('use_really_sure')) < 1) return false;
		return true;
	}

	function html_sanitize ($html, $mode, $wrapper='code') {
		$select_sanitizer= $this->getConf('sanitizer') ;
		if (function_exists($select_sanitizer)) {
			$r = $select_sanitizer($html);
			if (is_string($r)) {
				$html= $r;
			}
		} else if (!empty($select_sanitizer)) {
			msg('HTML: Invalid sanitizer function: ignored', -1);
		}
		return $html;
	}

    function handle ($match, $state, $pos, Doku_Handler $handler) {
		switch ($state) {
			case DOKU_LEXER_ENTER : {
				return array($state, $match);
			}
			case DOKU_LEXER_UNMATCHED : {
				$match= $this->html_sanitize($match, 'code');
				return array($state, $match);
			}
			case DOKU_LEXER_EXIT : {
				return array($state, $match);
			}
			case DOKU_LEXER_SPECIAL :
				return array($state, $match);
		}
		return array();
    }
    
    function render ($mode, Doku_Renderer $renderer, $data) { }
     
};

?>
