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

class syntax_plugin_json_extract extends DokuWiki_Syntax_Plugin
{
    /**
     * @return string Syntax mode type
     */
    public function getType() {
        return 'substition';
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
        return 150;
    }

    /**
     * Connect lookup pattern to lexer.
     *
     * @param string $mode Parser mode
     */
    public function connectTo($mode) {
        // %$link.to.0.var{"header 1[ß]":link.to.varx; "header2" : link2}%
        $this->Lexer->addSpecialPattern('\%\$.*?\%', $mode, 'plugin_json_extract');
    }


    /**
     * Handle matches of the json syntax
     *
     * @param string       $match   The match of the syntax
     * @param int          $state   The state of the handler
     * @param int          $pos     The position in the document
     * @param Doku_Handler $handler The handler
     *
     * @return array Data for the renderer - tokens(always), (one or none from) code or list or table.
     *     [[tokens] => [tok1, tok2, ...],
     *      [code] => boolean,
     *      [list] => [
     *          name1 => [tok3, tok4, ...],
     *          name2 => [tok5, tok6, ...],
     *          ...
     *      ]
     *      [table] => [
     *          name1 => [tok3, tok4, ...],
     *          name2 => [tok5, tok6, ...],
     *          ...
     *      ]]
     */
    public function handle($match, $state, $pos, Doku_Handler $handler) {
        $json_o = $this->loadHelper('json');

        //Return value
        $data = array('match' => $match);

        //Replace #@macro_name@# patterns with strings defined by textinsert Plugin.
        $match = $json_o->preprocess($match);

        /* match %$path [(row_filter)] {header} #format# (filter)%
         *
         * path - path.to.variable
         * [] - print table, optionally use (row_filter)
         * {header} - header description for table or links
         * #format# - format specifier for variable
         * (filter) - render variable only, if filter is evaluated to true
         *
         * for help on PCRE see: https://regexr.com/  */
        preg_match('/^%\$([^[\]{}#\(\)]*)(\[(?:\(.*?\))?\s*\])?\s*(\{.*?\})?\s*(#.*?#)?\s*(\(.*?\))?\s*%$/', $match, $mt);
        list(, $path, $table, $header, $format, $filter) = array_pad($mt, 6, '');

        // remove # from format
        if($format) {
            $format = substr($format, 1, -1);
        }

        $data['tokens'] = $json_o->parse_tokens($path);

        if($filter) {
            $data['filter'] = $json_o->parse_filter(substr($filter, 1, -1));
        }


        //table
        if($table) {
            $data['type'] = 'table_without_header';
            $table_filter = trim(substr($table, 1, -1)); //remove []
            if(strlen($table_filter) > 0) {
                $table_filter = substr(trim($table_filter), 1, -1); //remove ()
                $data['table_filter'] = $json_o->parse_filter($table_filter);
            }
            if($header) {
                $table_header = $json_o->parse_links(substr($header, 1, -1));
                if($table_header !== false) {
                    $data['type'] = 'table_with_header';
                    $data['table_header'] = $table_header;
                    $data['format'] = array();
                    if($format) {
                        $format_pairs = $json_o->parse_key_val($format, ':', ',');
                        if(is_array($format_pairs)) {
                            foreach ($format_pairs as &$val) {
                                $val = $this->handle_format($val);
                            }
                            $data['format'] = $format_pairs;
                        }
                    }
                }
            }
        }

        //list
        else if($header) {
            $list_header = $json_o->parse_links(substr($header, 1, -1));
            if($list_header !== false) {
                $data['type'] = 'list';
                $data['list_header'] = $list_header;
                $data['format'] = array();
                if($format) {
                    $format_pairs = $json_o->parse_key_val($format, ':', ',');
                    if(is_array($format_pairs)) {
                        foreach ($format_pairs as &$val) {
                            $val = $this->handle_format($val);
                        }
                        $data['format'] = $format_pairs;
                    }
                }
            }
        }

        //variable
        else {
            $data['type'] = 'variable';
            $data['format'] = $format ? $this->handle_format($format) : '';
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
        if ($mode === 'xhtml') {
            $json_o = $this->loadHelper('json');

            if(isset($data['tokens'])) {
                if(!isset($data['filter']) || $json_o->filter($json_o->get(), $data['filter'])) {
                    $var = $json_o->get($data['tokens']);
                }
                else {
                    $data['type'] = 'filtered';
                }
            }

            switch($data['type']) {
                case 'filtered':
                    break;


                case 'variable':
                    $this->render_var($renderer, $var, $data['format'], 1);
                    break;


                case 'list':
                    $tooltips = array();
                    //get data list
                    if(is_array($data['list_header'])) {
                        $list = array();
                        foreach($data['list_header'] as $key => $tokens) {
                            $v = $var;
                            foreach($tokens as $tok) {
                                if(is_array($v) && isset($v[$tok])) {
                                    $v = $v[$tok];
                                }
                                else {
                                    $v = null;
                                    break;
                                }
                            }
                            //If $name begins with '_tooltip_', it will display only as tooltip
                            if(strpos($key, '_tooltip_') === 0) {
                                $tooltips[substr($key, 9)] = $v;
                            }
                            else {
                                $list[$key] = $v;
                            }
                        }
                    }
                    else {
                        if(is_array($var)) {
                            $list = array();
                            foreach($var as $key => $v) {
                                $list[$key] = $v;
                            }
                        }
                        else {
                            $list = array($this->getConf('null_str') => $var);
                        }
                    }

                    //render data list
                    $renderer->table_open(2);
                    $renderer->tabletbody_open();
                    foreach($list as $name => $value) {
                        if(isset($tooltips[$name])) {
                            $renderer->doc .= DOKU_TAB.'<tr title="'.htmlspecialchars($tooltips[$name]).'">'.DOKU_LF.DOKU_TAB.DOKU_TAB;
                        }
                        else {
                            $renderer->tablerow_open();
                        }
                        $renderer->tableheader_open();
                        $renderer->cdata($name);
                        $renderer->tableheader_close();
                        $renderer->tablecell_open();
                        $this->render_var($renderer, $value, isset($data['format'][$name]) ? $data['format'][$name] : '', 1);
                        $renderer->tablecell_close();
                        $renderer->tablerow_close();
                    }
                    $renderer->tabletbody_close();
                    $renderer->table_close();
                    break;


                case 'table_without_header':
                    if(!is_array($var)) {
                        $var = array($var);
                    }
                    //render table
                    $renderer->table_open();
                    foreach($var as $set) {
                        //apply filter
                        if(isset($data['table_filter']) && !$json_o->filter($set, $data['table_filter'])) {
                            continue;
                        }
                        $renderer->tablerow_open();
                        if(!is_array($set)) {
                            $set = array($set);
                        }
                        foreach($set as $value) {
                            $renderer->tablecell_open();
                            $this->render_var($renderer, $value, null, 1);
                            $renderer->tablecell_close();
                        }
                        $renderer->tablerow_close();
                    }
                    $renderer->tabletbody_close();
                    $renderer->table_close();
                    break;


                case 'table_with_header':
                    if(!is_array($var)) {
                        $var = array($var);
                    }
                    $table = array();
                    //get table rows
                    foreach($var as $set) {
                        //apply filter
                        if(isset($data['table_filter']) && !$json_o->filter($set, $data['table_filter'])) {
                            continue;
                        }

                        //get table header on the first pass
                        if(!isset($header)) {
                            $header = array();
                            // if not specified, generate header automatically
                            if($data['table_header'] === '') {
                                $table_header = array();
                                if(is_array($set)) {
                                    foreach($set as $key => $dummy) {
                                        $table_header[$key] = array($key);
                                    }
                                }
                                $data['table_header'] = $table_header;
                            }
                            foreach($data['table_header'] as $key => $tokens) {
                                if(strpos($key, '_tooltip_') !== 0) {
                                    $header[] = $key;
                                }
                            }
                        }

                        //get cells for one row
                        $row = array();
                        $tooltips = array();
                        foreach($data['table_header'] as $name => $tokens) {
                            $v = $set;
                            //get value of the variable
                            foreach($tokens as $tok) {
                                if(is_array($v) && isset($v[$tok])) {
                                    $v = $v[$tok];
                                }
                                else {
                                    $v = null;
                                    break;
                                }
                            }

                            //If $name begins with '_tooltip_', it will display only as tooltip
                            if(strpos($name, '_tooltip_') === 0) {
                                $tooltips[substr($name, 9)] = $v;
                            }
                            else {
                                $row[$name] = $v;
                            }
                        }
                        $row['_tooltip_'] = $tooltips;
                        $table[] = $row;
                    }

                    //render table
                    $renderer->table_open();

                    $renderer->tablethead_open();
                    $renderer->tablerow_open();
                    foreach($header as $value) {
                        $renderer->tableheader_open();
                        $this->render_var($renderer, $value, null, 1);
                        $renderer->tableheader_close();
                    }
                    $renderer->tablerow_close();
                    $renderer->tablethead_close();

                    $renderer->tabletbody_open();
                    foreach($table as $set) {
                        $tooltips = $set['_tooltip_'];
                        unset($set['_tooltip_']);

                        //open table row, optionally with tooltip
                        if(isset($tooltips[''])) {
                            $renderer->doc .= DOKU_TAB.'<tr title="'.htmlspecialchars($tooltips['']).'">'.DOKU_LF.DOKU_TAB.DOKU_TAB;
                        }
                        else {
                            $renderer->tablerow_open();
                        }

                        //render all cells in row, some may have tooltips, some may have custom format
                        foreach($set as $name => $value) {
                            if(isset($tooltips[$name])) {
                                $renderer->doc .= '<td title="'.htmlspecialchars($tooltips[$name]).'">';
                            }
                            else {
                                $renderer->tablecell_open();
                            }
                            $this->render_var($renderer,
                                              $value,
                                              isset($data['format'][$name]) ? $data['format'][$name] : null,
                                              1);
                            $renderer->tablecell_close();
                        }
                        $renderer->tablerow_close();
                    }
                    $renderer->tabletbody_close();

                    $renderer->table_close();
                    break;


                default:
                    $renderer->cdata($data['match']);
                    break;
            }
            return true;
        }

        return false;
    }


    /**
     * Render the variable
     *
     * @param Doku_Renderer $renderer The renderer
     * @param mixed $var variable to be rendered. If array, then members will be rendered.
     * @param array $format render variable in specific format.
     * @param integer $recursive if >1 and $var is array, then array elements will be rendered
     *
     * @return integer number of elements rendered
     */
    private function render_var(Doku_Renderer $renderer, $var, $format=null, $recursive=0, $print_separator=false) {
        $i = $iprev = 0;
        if(is_array($format) && ($format['func'] === 'format_code' || $format['func'] === 'format_ejs')) {
            call_user_func(array($this, $format['func']), $renderer, $var, $format['param']);
        }
        else if(is_scalar($var)) {
            if($print_separator) {
                $renderer->doc .= ', ';
            }
            if(is_bool($var)) {
                $renderer->cdata($this->getConf($var ? 'true_str' : 'false_str'));
            }
            else if(is_string($var) && is_array($format)) {
                call_user_func(array($this, $format['func']), $renderer, $var, $format['param']);
            }
            else {
                $renderer->cdata($var);
            }
            $i++;
        }
        else if(is_array($var)) {
            if($recursive > 0) {
                foreach($var as $v) {
                    if($i > $iprev) {
                        $print_separator = true;
                        $iprev = $i;
                    }
                    $i += $this->render_var($renderer, $v, $format, $recursive-1, $print_separator);
                }
                if($i === 0 && count($var) > 0) {
                    $renderer->cdata($this->getConf('array_str'));
                }
            }
        }
        else {
            $renderer->cdata($this->getConf('null_str'));
            $i++;
        }

        return $i;
    }


    /**
     * Handle format parameter
     *
     * @param string $format format parameter from json data extractor
     *
     * @return empty string or array with function name and parameter, which
     *                       renders the variable according to format.
     */
    private function handle_format($format) {
        $param = null;

        // Dokuwiki Header
        // #header5#
        if(substr($format, 0, 6) === 'header') {
            //get header level
            $param = intval(substr($format, 6));
            if($param < 1) $param = 1;
            else if($param > 5) $param = 5;
            $format = 'header';
        }

        // Dokuwiki media internal or external link
        // #media?L200x300#
        else if(substr($format, 0, 5) === 'media') {
            list($format, $align_size) = array_pad(explode('?', $format, 2), 2, '');
            if($align_size === '') {
                $param = array(null, null, null, null, null);
            }
            else if($align_size === 'linkonly') {
                $param = array(null, null, null, null, 'linkonly');
            }
            else {
                $align = substr($align_size, 0, 1);
                if     ($align === 'l') $align = 'left';
                else if($align === 'c') $align = 'center';
                else if($align === 'r') $align = 'right';
                else                    $align = null;
                list($width, $height) = array_pad(explode('x', substr($align_size, 1), 2), 2, '');
                $width = intval($width);
                if($width > 0) {
                    $height = intval($height);
                    if($height <= 0) {
                        $height = null;
                    }
                }
                else {
                    $width = $height = null;
                }
                $param = array($align, $width, $height, null, null);
            }
        }

        // RSS
        // #rss?n?nosort?reverse?author?date?details#
        else if(substr($format, 0, 3) === 'rss') {
            $param = array();
            if(preg_match('/\b(\d+)\b/', $format, $match)) {
               $param['max'] = $match[1];
            }
            else {
               $param['max'] = 8;
            }
            $param['reverse'] = preg_match('/\brev/', $format);
            $param['author']  = preg_match('/\b(by|author)/', $format);
            $param['date']    = preg_match('/\bdate/', $format);
            $param['details'] = preg_match('/\b(desc|detail)/', $format);
            $param['nosort']  = preg_match('/\bnosort/', $format);
            $format = 'rss';
        }

        // EJS template
        // %$#ejs?template%
        if(substr($format, 0, 4) === 'ejs?') {

            $patterns = array ('/&percnt;/', '/&num;/', '/&colon;/', '/&comma;/', '/<\$=/', '/\$>/');
            $replace = array ('%', '#', ':', ',', '<%=', '%>');

            //get template and replace some patterns
            $param = preg_replace($patterns, $replace, substr($format, 4));
            $format = 'ejs';
        }

        //other formats don't need special handler

        //get format_function name
        $func = 'format_'.$format;

        return  method_exists($this, $func) ?
                array('func' => $func, 'param' => $param) :
                '';
    }


    /**
     * Renderers for different formats
     *
     * @param Doku_Renderer $renderer The renderer
     * @param string $var variable to render
     * @param mixed $param additional parameter
     */
    // Dokuwiki Title
    private function format_header(Doku_Renderer $renderer, $var, $param) {
        $renderer->header($var, $param, 0);
    }

    // \\server\share|Title
    // https://example.com|Title
    // dokuwiki:link|Title
    private function format_link(Doku_Renderer $renderer, $var, $param) {
        list($id, $title) = array_pad(explode('|', $var, 2), 2, '');
        if(strpos($id, '\\') === 0) {
            $renderer->windowssharelink($id, $title==='' ? $id : $title);
        }
        else if(strpos($id, '://')) {
            $renderer->externallink($id, $title==='' ? $id : $title);
        }
        else if(strlen($id) > 0) {
            if($title === '') {
                $tok = explode(':', $id);
                $last = $tok[count($tok) - 1];
                $title = $last ? $last : $id;
            }
            $renderer->internallink($id, $title);
        }
    }

    // https://example.com/media.png|Title
    // dokuwiki:link.png|Title
    private function format_media(Doku_Renderer $renderer, $var, $param) {
        list($id, $title) = array_pad(explode('|', $var, 2), 2, '');
        if($title === '') {
            $title = $id;
        }
        if(strpos($id, '://')) {
            $renderer->externalmedia($id, $title, $param[0], $param[1], $param[2], $param[3], $param[4]);
        }
        else {
            $renderer->internalmedia($id, $title, $param[0], $param[1], $param[2], $param[3], $param[4]);
        }
    }

    // name@example.com|Title
    private function format_email(Doku_Renderer $renderer, $var, $param) {
        list($id, $title) = array_pad(explode('|', $var, 2), 2, '');
        if($title === '') {
            $title = $id;
        }
        $renderer->emaillink($id, $title);
    }

    // http://slashdot.org/index.rss
    private function format_rss(Doku_Renderer $renderer, $var, $param) {
        $renderer->rss($var, $param);
    }

    // json_encode
    private function format_code(Doku_Renderer $renderer, $var, $param) {
        $renderer->doc .= '<pre class="json-extract-code">'
                       .htmlspecialchars(json_encode($var, JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE))
                       .'</pre>';
    }

    // EJS template https://ejs.co/
    // Javascript will take json data and template from hidden divs, then will generate output
    private function format_ejs(Doku_Renderer $renderer, $var, $param) {
        $renderer->doc .= '<span class="json-extract-ejs"><span id="data">'
                       .htmlspecialchars(json_encode($var))
                       .'</span><span id="template">'
                       .htmlspecialchars($param)
                       .'</span></span>';
    }
}
