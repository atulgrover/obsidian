<?php
/**
 * DokuWiki Plugin json (Syntax Component)
 *
 * @license GPL 2 http://www.gnu.org/licenses/gpl-2.0.html
 * @author  Janez Paternoster <janez.paternoster@siol.net>
 */

// must be run within Dokuwiki
if (!defined('DOKU_INC')) {
    die();
}

class syntax_plugin_json_section extends DokuWiki_Syntax_Plugin
{
    /**
     * @return string Syntax mode type
     */
    public function getType() {
        return 'container';
    }

    /**
     * What kind of syntax do we allow (optional)
     */
    function getAllowedTypes() {
        return array('container', 'formatting', 'substition', 'protected', 'disabled', 'paragraphs');
    }

    /**
     * @return string Paragraph type
     */
    public function getPType() {
        return 'normal';
    }

    /**
     * @return int Sort order - Low numbers go before high numbers
     */
    public function getSort() {
        return 140;
    }

    /**
     * Connect lookup pattern to lexer.
     *
     * @param string $mode Parser mode
     */
    public function connectTo($mode) {
        $this->Lexer->addEntryPattern('\%\$-starti?\s*\([^[\]{}%]*?\)%(?=.*?%\$end\%)', $mode, 'plugin_json_section');
    }

    public function postConnect() {
        $this->Lexer->addExitPattern('%\$end%', 'plugin_json_section');
    }

    /**
     * Handle matches of the json syntax
     *
     * @param string       $match   The match of the syntax
     * @param int          $state   The state of the handler
     * @param int          $pos     The position in the document
     * @param Doku_Handler $handler The handler
     *
     * @return array Data for the renderer
     */
    public function handle($match, $state, $pos, Doku_Handler $handler) {
        $data = ['state' => $state];
        $json_o = $this->loadHelper('json');
        switch ($state) {
            case DOKU_LEXER_ENTER:
                preg_match('/^%\$-start(i)?\s*\((.*)\)%/s', $match, $mt);
                $data['filter'] = $json_o->parse_filter($mt[2]);
                $data['inline'] = $mt[1];
                break;

            case DOKU_LEXER_UNMATCHED:
                $data['match'] = $match;
                break;

            case DOKU_LEXER_EXIT:
                break;
        }

        return $data;
    }

    /**
     * Render xhtml output or metadata
     *
     * @param string        $mode     Renderer mode (supported modes: xhtml)
     * @param Doku_Renderer $renderer The renderer
     * @param array         $data     The data from the handler() function
     *
     * @return bool If rendering was successful.
     */
    public function render($mode, Doku_Renderer $renderer, $data) {
        static $hidden = false;
        static $tag = "div";
        $json_o = $this->loadHelper('json');

        if ($mode === 'xhtml') {
            switch ($data['state']) {
                case DOKU_LEXER_ENTER:
                    $hidden = false;
                    $var = $json_o->get(array());

                    if(!$json_o->filter($var, $data['filter'])) {
                        $display = " style='display:none;'";
                        $hidden = true;
                    }
                    else {
                        $display = '';
                    }

                    $tag = $data['inline'] ? "span" : "div";
                    $renderer->doc .= "<$tag$display>";
                    break;

                case DOKU_LEXER_UNMATCHED:
                    //this part runs for each unmatched line separtelly. Other dokuwiki matches are excluded, except headres.
                    if($hidden === false) {
                        $text = $renderer->_xmlEntities($data['match']);
                        //find headers
                        if(preg_match("/^[ \t]*={2,}[^\n]+={2,}[ \t]*$/", $text, $match)) {
                            $title = trim($match[0]);
                            $level = 7 - strspn($title,'=');
                            if($level < 1) $level = 1;
                            $title = trim($title,'=');
                            $title = trim($title);
                            $renderer->header($title, $level, 0);
                        } else {
                            $renderer->doc .= $text;
                        }
                    }
                    break;

                case DOKU_LEXER_EXIT:
                    $renderer->doc .= "</$tag>";
                    break;
            }
            return true;
        }

        return false;
    }
}
