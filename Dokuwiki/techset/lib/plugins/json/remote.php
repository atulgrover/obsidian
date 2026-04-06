<?php
/**
 * DokuWiki Plugin json (Remote Component)
 *
 * @license GPL 2 http://www.gnu.org/licenses/gpl-2.0.html
 * @author  Janez Paternoster <janez.paternoster@siol.net>
 */

class remote_plugin_json extends DokuWiki_Remote_Plugin {
    public function _getMethods() {
        return [
            'get' => [
                'args' => array('string', 'string', 'boolean'),
                'return' => '[status, JSONdata, log]',
                'name' => 'get',
                'doc' => 'Get JSON data from page from data path.'
            ],
            'set' => [
                'args' => array('string', 'string', 'string|array', 'boolean'),
                'return' => 'OK on success or error description',
                'name' => 'set',
                'doc' => 'Set JSON data inside the <json> element inside the wiki page.'
            ],
            'append' => [
                'args' => array('string', 'string', 'string|array'),
                'return' => 'OK on success or error description',
                'name' => 'append',
                'doc' => 'Append JSON data into array inside page inside <json id=xxx> element.'
            ]
        ];
    }

    /**
     * Generate JSON database on page and return data from the JSON_path.
     *
     * @param string    $page_id Absolute id of the wiki page.
     * @param string    $path    Path on the JSON database.
     * @param boolean   $addLog  If true, the additional info will be returned too.
     *
     * @return array  status => string  'OK' on success or error description
     *                data => string    JSON data from database
     *                log => array      Only if $addLog is true. JSON string with
     *                                  description of database generation.
     */
    public function get($page_id, $path = '', $addLog = false) {
        $json_o = $this->loadHelper('json');
        $response = ['status' => 'OK'];

        $src = $json_o->parse_src($page_id);
        if (!is_array($src)) {
            $response['status'] = sprintf($this->getLang('wrong_pageId'), $page_id);
        }
        else if (!page_exists($page_id)) {
            $response['status'] = sprintf($this->getLang('file_not_found'), $page_id);
        }
        //verify file read rights
        else if(auth_quickaclcheck($page_id) < AUTH_READ) {
            $response['status'] = sprintf($this->getLang('permision_denied_read'), $page_id);
        }
        else {
            $json = [];
            $data_parameter = [
                'json_inline_raw' => '',
                'src' => $src,
                'path' => [
                    'clear' => false,
                    'array' => false,
                    'tokens' => []
                ]
            ];
            $log = ['tag' => 'remote', 'path' => $path];

            // generate complete JSON database from wikipage
            $json_o->add_json($json,
                              $data_parameter,
                              $this->getConf('src_recursive'),
                              $log);

            // get part of JSON data specified by path
            $response['data'] = $json_o->get($json_o->parse_tokens($path),
                                             $json);

            // add information about JSON data loading
            if ($addLog) {
                $response['log'] = $log;
            }
        }

        return $response;
    }

    /**
     * Find <json id=… element inside page and set its inline data.
     *
     * @param string    $page_id    Absolute id of the wiki page.
     * @param string    $json_id    'id' attribute of the <json> element on the wiki page.
     * @param string    $data       JSON data to be put inside <json></json>.
     * @param boolean   $overwrite  If false, error will be reported if <json> element already contains data.
     *
     * @return string   'OK' on success or error description
     */
    public function set($page_id, $json_id, $data, $overwrite = false) {
        $err = '';

        if(!page_exists($page_id)) {
            $err = sprintf($this->getLang('file_not_found'), $page_id);
        }
        //verify file write rights
        else if(auth_quickaclcheck($page_id) < AUTH_EDIT) {
            $err = sprintf($this->getLang('permision_denied_write'), $page_id);
        }

        //verify JSON data (must be an array, empty string or valid JSON string)
        if($err === '') {
            if (is_array($data)) {
                $data = json_encode($data);
            }
            else {
                $json_data = json_decode($data, true);
                if (!(trim($data) === '' || isset($json_data))) {
                    $err = $this->getLang('json_error');
                }
                unset($json_data);
            }
        }

        //verify lock
        $locked = false;
        if($err === '') {
            if(checklock($page_id)) {
                $err = sprintf($this->getLang('file_locked'), $page_id);
            }
            else {
                lock($page_id);
                $locked = true;
            }
        }

        //read the file
        if($err === '') {
            $file = rawWiki($page_id);
            if(!$file) {
                $err = sprintf($this->getLang('file_not_found'), $page_id);
            }
        }

        //replace json data; must be one match
        if($err === '') {
            $file_updated = preg_replace_callback(
                '/(<(json[a-z0-9]*)\b[^>]*?id\s*=[\s"\']*'.$json_id.'\b.*?>)(.*?)(<\/\2>)/s',
                function($matches) use(&$err, $data, $overwrite) {
                    // replace only if forced or empty data
                    if($overwrite || !trim($matches[3])) {
                        $replacement = $matches[1].$data.$matches[4];
                        return $replacement;
                    }
                    else {
                        //set error and keep the original data
                        $err = 'e';
                        return $matches[0];
                    }
                },
                $file,
                -1,
                $count
            );
            if($file_updated) {
                if($count === 0) {
                    $err = sprintf($this->getLang('element_not_found'), $json_id);
                }
                else if($count !== 1) {
                    $err = sprintf($this->getLang('duplicated_id'), $json_id);
                }
                else if($err === 'e') {
                    $err = sprintf($this->getLang('not_empty'), $json_id);
                }
            }
            else {
                $err = sprintf($this->getLang('internal_error'), 'plugin/json/remote/set');
            }
        }

        //write file
        if($err === '') {
            saveWikiText($page_id, $file_updated, sprintf($this->getLang('json_updated_remote'), $json_id), true);
            $err = 'OK';
        }

        //unlock for editing
        if($locked) {
            unlock($page_id);
        }

        return $err;
    }


    /**
     * Find <json id=… element inside page and append data to its inline database.
     *
     * Inline JSON data must be an array or empty. If empty, new array will be initialized.
     *
     * @param string    $page_id    Absolute id of the wiki page.
     * @param string    $json_id    'id' attribute of the <json> element. If empty, complete page will be
     *                              treated as JSON database (page must be a JSON array, empty or non-existent).
     * @param string    $data       JSON data to be appended inside <json>[]</json>. Must be an array or valid JSON string.
     *
     * @return string   'OK' on success or error description
     */
    public function append($page_id, $json_id, $data) {
        $err = '';

        if(!page_exists($page_id) && $json_id) {
            $err = sprintf($this->getLang('file_not_found'), $page_id);
        }
        //verify file write rights
        else if(auth_quickaclcheck($page_id) < AUTH_EDIT) {
            $err = sprintf($this->getLang('permision_denied_write'), $page_id);
        }

        //verify JSON data (must be an array or valid JSON string)
        if($err === '') {
            if (is_array($data)) {
                $data = json_encode($data);
            }
            else {
                $json_data = json_decode($data, true);
                if (isset($json_data)) {
                    $data = json_encode($json_data); //make string in one line
                }
                else {
                    $err = $this->getLang('json_error');
                }
                unset($json_data);
            }
        }

        //verify lock
        $locked = false;
        if($err === '') {
            if(checklock($page_id)) {
                $err = sprintf($this->getLang('file_locked'), $page_id);
            }
            else {
                lock($page_id);
                $locked = true;
            }
        }

        //read the file
        if($err === '') {
            $file = rawWiki($page_id);
            if(!$file) {
                if ($json_id) {
                    $err = sprintf($this->getLang('file_not_found'), $page_id);
                }
                else {
                    $file = '[]';
                }
            }
        }

        if($err === '') {
            // pattern "[", "current_data", "]", ignore spaces
            $json_array_pattern = '/^(\s*\[\s*)(.*?)\s*\]\s*$/s';
            //a classic dokuwiki page with <json> elements inside
            if($json_id) {
                //replace json data; must be one match
                $file_updated = preg_replace_callback(
                    '/(<(json[a-z0-9]*)\b[^>]*?id\s*=[\s"\']*'.$json_id.'\b.*?>)(.*?)(<\/\2>)/s',
                    function($matches) use(&$err, $data, $json_array_pattern) {
                        $inlineJSON = trim($matches[3]) ? $matches[3] : '[]';

                        if (preg_match($json_array_pattern, $inlineJSON, $matchesJSON)) {
                            if ($matchesJSON[2]) {
                                $inlineJSON = $matchesJSON[1].$matchesJSON[2].",\n  ".$data."\n]";
                            } else {
                                $inlineJSON = "[\n  ".$data."\n]";
                            }

                            return $matches[1].$inlineJSON.$matches[4];
                        }
                        else {
                            //set error and keep original data
                            $err = 'e';
                            return $matches[0];
                        }
                    },
                    $file,
                    -1,
                    $count
                );
                if($file_updated) {
                    if($count === 0) {
                        $err = sprintf($this->getLang('element_not_found'), $json_id);
                    }
                    else if($count !== 1) {
                        $err = sprintf($this->getLang('duplicated_id'), $json_id);
                    }
                    else if($err === 'e') {
                        $err = sprintf($this->getLang('not_array'), $json_id);
                    }
                }
                else {
                    $err = sprintf($this->getLang('internal_error'), 'plugin/json/remote/append');
                }
            }
            //a pure JSON file
            else {
                if (preg_match($json_array_pattern, $file, $matchesJSON)) {
                    if ($matchesJSON[2]) {
                        $file_updated = $matchesJSON[1].$matchesJSON[2].",\n  ".$data."\n]";
                    } else {
                        $file_updated = "[\n  ".$data."\n]";
                    }
                }
                else {
                    $err = sprintf($this->getLang('not_array_file'), $page_id);
                }
            }
        }

        //write file
        if($err === '') {
            saveWikiText($page_id, $file_updated, sprintf($this->getLang('json_added_remote'), $json_id), true);
            $err = 'OK';
        }

        //unlock for editing
        if($locked) {
            unlock($page_id);
        }

        return $err;
    }
}
