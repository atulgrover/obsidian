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


class syntax_plugin_json_define extends DokuWiki_Syntax_Plugin
{
    /**
     * @return string Syntax mode type
     */
    public function getType() {
        return 'protected';
    }


    /**
     * @return string Paragraph type
     */
    public function getPType() {
        return 'block';
    }


    /**
     * @return int Sort order - Low numbers go before high numbers
     */
    public function getSort() {
        return 185;
    }


    /**
     * Connect lookup pattern to lexer.
     *
     * @param string $mode Parser mode
     */
    public function connectTo($mode) {
        $this->Lexer->addSpecialPattern('<json[a-z0-9]*\b.*?>.*?</json[a-z0-9]*>', $mode, 'plugin_json_define');
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
        $json_o = $this->loadHelper('json');
        $data = $json_o->handle_element($match);

        if($data === NULL) {
            return $match;
        }

        //is there a plugin
        if(!isset($data['error']) && $data['tag'] !== 'json') {
            $sub_plugin = $this->loadHelper($data['tag']);
            if(!($sub_plugin && is_a($sub_plugin, 'helper_plugin_json'))) {
                unset($sub_plugin);
                if($this->getConf('ignore_if_no_plugin')) {
                    return $match;
                }
            }
        }

        //get attribute 'display' with display options, separated by commas
        if(isset($data['keys']['display'])) {
            if($data['keys']['display'][0] === ',') {
                //add options to defaults
                $data['display'] =
                    strtolower($this->getConf('json_display')).
                    strtolower($data['keys']['display']);
            }
            else {
                //use only custom display options
                $data['display'] = strtolower($data['keys']['display']);
            }
        }
        else {
            //use default display options
            $data['display'] = strtolower($this->getConf('json_display'));
        }

        //Include data, if archive=make
        if(!isset($data['error']) && isset($data['keys']['archive'])) {
            if(strtolower($data['keys']['archive']) === 'make') {
                $data['display'] .= ',orig-hidden';
            }
        }

        //call a sub-plugin
        if(!isset($data['error']) && isset($sub_plugin)) {
            $data['sub_plugin'] = true;
            $sub_plugin->handle($data);
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

        if($mode === 'metadata') {
            if(!isset($data['error']) && isset($data['src']['internallink'])) {
                $renderer->internallink($data['src']['internallink']);
            }
        }

        else if($mode === 'xhtml') {
            $json_o = $this->loadHelper('json');
            $data_path = isset($data['keys']['path']) ? $data['keys']['path'] : '';

            if(is_string($data)) {
                $renderer->cdata($data);
                return true;
            }

            static $tab_number = 0;
            $tab_number++;

            $log = array('tag' => $data['tag'], 'id' => $data['id'] ?? '', 'path' => $data_path, 'inline' => (strlen(trim($data['json_inline_raw'])) > 0));

            //buld the json database
            if(!isset($data['error'])) {
                if(!isset($data['src_archive'])) {
                    //check, if src to json file is specified in query string
                    if(isset($data['keys']['src_ext'])) {
                        $src = NULL;
                        $src_ext = strtolower($data['keys']['src_ext']);
                        if(preg_match('/^json_\w+$/', $src_ext)) {
                            //scan query string for matching key
                            foreach ($_GET as $q_key => $q_val) {
                                if(strtolower($q_key) == $src_ext) {
                                    $src = $json_o->parse_src($q_val);
                                    break;
                                }
                            }
                        }
                        if(is_string($src)) {
                            $data['src'] = $src;
                            $data['src_extractors'] = $json_o->extractors_handle($src);
                        }
                        else if(is_array($src)) {
                            $data['src'] = $src;
                        }
                        else if(!isset($data['src'])) {
                            $log['error'] = 'query string for src_ext='.$data['keys']['src_ext'].' not defined';
                        }
                    }

                    //check, if src_path to json file is specified in query string
                    if(isset($data['keys']['src_path_ext'])) {
                        $src_path = NULL;
                        $src_path_ext = strtolower($data['keys']['src_path_ext']);
                        if(preg_match('/^json_\w+$/', $src_path_ext)) {
                            //scan query string for matching key
                            foreach ($_GET as $q_key => $q_val) {
                                if(strtolower($q_key) == $src_path_ext) {
                                    $src_path = $json_o->parse_tokens($q_val);
                                    break;
                                }
                            }
                        }
                        if(is_array($src_path)) {
                            $data['src_path'] = $src_path;
                        }
                        else if(!is_array($data['src_path'])) {
                            $log['error'] = 'query string for src_path_ext='.$data['keys']['src_path_ext'].' not defined';
                        }
                    }

                    //disable browser cache, if external files are used for data
                    if(isset($data['src']) && is_array($data['src'])) {
                        $renderer->nocache();
                    }
                }

                //load all json data and put it into the json database
                $json_o->add_json(helper_plugin_json::$json, $data, $this->getConf('src_recursive'), $log);
            }
            else {
                $log['error'] = $data['error'];
            }


            //prapare data for html output (jQuery UI tabs)
            $class = array('json-tabs');
            if(isset($data['make_archive'])) {
                $class[] = 'json-make-archive';
            }
            $data_attr = array(
                'json-id' => $data['id'] ?? '',
                'json-hash' => md5($data['json_inline_raw']),
                'active' => 'false');   //all tabs colapsed or specific tab active
            $tabs = array();
            $body = array();
            $display = $data['display'];
            $all = strpos($display, 'all') !== false;
            $tab_no = 0;

            //json original data (before they are combined with inline data)
            if($all || strpos($display, 'original') !== false) {
                if(strpos($display, 'original*') !== false) { $data_attr['active'] = $tab_no; }
                $tab_no++;
                $tabs[] = '<li><a href="#json-tab-'.$tab_number.'-orig">'.$this->getLang('json_original').'</a></li>';
                $body[] =      '<div id="json-tab-'.$tab_number.'-orig"><pre class="json-data-original lang-json">'
                        .htmlspecialchars(json_encode($data['json_original'], JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE)).'</pre></div>';
            }
            else if(strpos($display, 'orig-hidden') !== false) {
                $body[] = '<div hidden=""><pre class="json-data-original">'
                        .htmlspecialchars(json_encode($data['json_original'])).'</pre></div>';
            }

            //json inline data
            if($all || strpos($display, 'inline') !== false) {
                if(strpos($display, 'inline*') !== false) { $data_attr['active'] = $tab_no; }
                $tab_no++;
                $tabs[] = '<li><a href="#json-tab-'.$tab_number.'-inline">'.$this->getLang('json_inline').'</a></li>';
                $body[] =      '<div id="json-tab-'.$tab_number.'-inline"><textarea wrap="off" class="json-data-inline json-textarea">'
                        .htmlspecialchars($data['json_inline_raw']).'</textarea></div>';
            }
            else if(strpos($display, 'inl-hidden') !== false) {
                $body[] = '<div hidden=""><textarea class="json-data-inline">'
                        .htmlspecialchars($data['json_inline_raw']).'</textarea></div>';
            }

            //json combined data
            if($all || strpos($display, 'combined') !== false) {
                if(strpos($display, 'combined*') !== false || ($all && $data_attr['active'] === 'false')) { $data_attr['active'] = $tab_no; }
                $tab_no++;
                $tabs[] = '<li><a href="#json-tab-'.$tab_number.'-comb">'.$this->getLang('json_combined').'</a></li>';
                $body[] =      '<div id="json-tab-'.$tab_number.'-comb"><pre class="json-data-combined lang-json">'
                        .htmlspecialchars(json_encode($data['json_combined'], JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE)).'</pre></div>';
            }
            else if(strpos($display, 'comb-hidden') !== false) {
                $body[] = '<div hidden=""><pre class="json-data-combined">'
                        .htmlspecialchars(json_encode($data['json_combined'])).'</pre></div>';
            }

            //call a sub-plugin
            if(isset($data['sub_plugin'])) {
                $sub_plugin = $this->loadHelper($data['tag']);
                $sub_plugin->render($renderer, $data, $class, $data_attr, $tabs, $body, $log, $tab_no, $tab_number);
            }

            //display 'error' log when there are errors or display 'log', when there are external source files.
            if(($all || (strpos($display, 'error') !== false) || (strpos($display, 'log') !== false)) && $this->find_key('error', $log)) {
                if(strpos($display, 'error*') !== false || strpos($display, 'log*') !== false) { $data_attr['active'] = $tab_no; }
                $tab_no++;
                $tabs[] = '<li><a href="#json-tab-'.$tab_number.'-err" class="json-error">'.$this->getLang('error').'</a></li>';
                $body[] = '<div id="json-tab-'     .$tab_number.'-err" class="json-log">'.$this->render_log($renderer, array($log)).'</div>';
            }
            else if($all || (strpos($display, 'log') !== false)) {
                if(strpos($display, 'log*') !== false) { $data_attr['active'] = $tab_no; }
                $tab_no++;
                $tabs[] = '<li><a href="#json-tab-'.$tab_number.'-log">'.$this->getLang('log').'</a></li>';
                $body[] =      '<div id="json-tab-'.$tab_number.'-log" class="json-log">'.$this->render_log($renderer, array($log)).'</div>';
            }

            //no tabs, completelly hide the element
            if($tab_no === 0) {
                $class[] = 'json-hidden';
            }
            //if single tab is there and is set to default, then hide tabs menu
            else if($tab_no === 1 && $data_attr['active'] !== 'false') {
                $class[] = 'json-hide-tabs';
            }

            //write html
            if(count($body) > 0) {
                $renderer->doc .= '<div class="'.implode(' ', $class).'" '.$this->implode_data_attr($data_attr).'>'
                                ."\n<ul>\n"
                                ."  <li><a>".$data_path."</a> &nbsp; <button class='json-save-button'>".$this->getLang('save')."</button></li>\n  "
                                .implode("\n  ", $tabs)
                                ."\n</ul>\n"
                                .implode("\n", $body)
                                ."\n</div>";
            }
        }
        return true;
    }


    /**
     * Verify, if key exists in multidimensional array
     */
    private function find_key($keySearch, $array) {
        foreach($array as $key => $item) {
            if($key === $keySearch) {
                return true;
            } elseif (is_array($item) && $this->find_key($keySearch, $item)) {
                return true;
            }
        }
        return false;
    }


    /**
     * return string with html data-... attributes
     */
    private function implode_data_attr($arr) {
        $s = [];
        foreach($arr as $key => $val) {
            $s[] = 'data-'.$key.'="'.$val.'"';
        }
        return implode(' ', $s);
    }


    /**
     * Render json log
     *
     * @param Doku_Renderer $r The renderer
     * @param array $log Log data elements from <json> element
     * @param integer $level list level
     *
     * @return string html list with info about JSON data source
     */
    private function render_log(Doku_Renderer $renderer, $log_elements, $level=1) {
        $doc = '<ul>'.DOKU_LF;

        foreach($log_elements as $el) {

            //listitem with info about <json> element
            $doc .= '<li class="level'.$level.'"><div class="li">';
            $doc .= 'element: '.$el['tag'];
            if ($el['id']) $doc .= ', id: '.$el['id'];
            $doc .= ', path: '.htmlspecialchars($el['path']);
            if(isset($el['error'])) {
                $doc .= ', <span class="json-error">ERROR</span>: '.htmlspecialchars($el['error']);
            }
            if(!empty($el['src_archive'])) {
                $doc .= ', archived src data';
            }
            if($el['inline']) {
                $doc .= ', inline data';
            }
            if(isset($el['src'])) {
                $doc .= ', external data';
                if(isset($el['src_path'])) {
                    $doc .= ' (from path: '.htmlspecialchars($el['src_path']).')';
                }
            }
            $doc .= '</div></li>'.DOKU_LF;

            //list of files with external json data
            if(isset($el['src'])) {
                $doc .= '<ul>'.DOKU_LF;
                foreach($el['src'] as $file) {
                    $doc .= '<li class="level'.($level+1).'"><div class="li">';
                    if($file['filename'] === '***JSON code***') {
                        $doc .= 'JSON code from \'src\' attribute';
                    }
                    else if(isset($file['extenal_link'])) {
                        $doc .= 'external file: '.$renderer->externallink($file['filename'], $file['filename'], true);
                    }
                    else {
                        $doc .= 'internal file: '.$renderer->internallink($file['filename'], $file['filename'], null, true);
                    }
                    if(isset($file['error'])) {
                        $doc .= ', <span class="json-error">ERROR</span>: '.htmlspecialchars($file['error']);
                    }
                    else if(!isset($file['elements']) && $file['filename'] !== '***JSON code***') {
                        $doc .= ', JSON file';
                    }
                    $doc .= '</div></li>'.DOKU_LF;
                    if(isset($file['elements'])) {
                        $doc .= $this->render_log($renderer, $file['elements'], $level+2);
                    }
                }
                $doc .= '</ul>'.DOKU_LF;
            }
        }

        $doc .= '</ul>'.DOKU_LF;

        return $doc;
    }

}
