<?php
/**
 * DokuWiki Plugin json (Helper Component)
 *
 * @license GPL 2 http://www.gnu.org/licenses/gpl-2.0.html
 * @author  Janez Paternoster <janez.paternoster@siol.net>
 */

// must be run within Dokuwiki
if (!defined('DOKU_INC')) {
    die();
}


/**
 * Resolving relative IDs to absolute ones
 *
 * Class is necessary, because dokuwiki\File\PageResolver is not able not to cleanID().
 *
 * see https://www.dokuwiki.org/devel:releases:refactor2021#refactoring_of_id_resolving
 */
class CustomResolver extends dokuwiki\File\Resolver
{
    /**
     * Resolves a given ID to be absolute
     */
    public function resolveId($id, $rev = '', $isDateAt = false)
    {
        $id = (string) $id;

        if ($id !== '') {
            $id = parent::resolveId($id, $rev, $isDateAt);
        } else {
            $id = $this->contextID;
        }

        return $id;
    }
}


class helper_plugin_json extends DokuWiki_Plugin {
    /**
     * Array with json data objects
     */
    public static $json = null;


    /**
     * Array with replacement macros for preprocess
     */
    private static $macros = null;


    /**
     * Preprocess matched string
     *
     * If textinsert Plugin is installed, use it's macros. (see https://www.dokuwiki.org/plugin:textinsert)
     * Replace #@macro_name@# patterns with strings defined by textinsert Plugin.
     *
     * @param string $match input string
     *
     * @return string
     */
    public function preprocess($str) {
        $macros = &helper_plugin_json::$macros;

        //first time load macros or set it to false
        if(is_null($macros)) {
            $macros_file = DOKU_INC . 'data/meta/macros/macros.ser';
            if(file_exists($macros_file)) {
                $macros = unserialize(file_get_contents($macros_file));
            }
            else {
                $macros = false;
            }
        }

        //replace macros
        if($macros !== false && is_string($str)) {
            $str = preg_replace_callback(
                '/#@(.+?)@#/',
                function ($matches) use ($macros_file, &$macros) {
                    $replacement = $macros[$matches[1]];
                    return is_string($replacement) ? $replacement : $matches[0];
                },
                $str
            );
        }

        return $str;
    }


    /**
     * Evaluate src attribute (filename and full path or JSON string)
     *
     * @param string $path local filename or url
     *
     * @return false on error or
     *         string with json data or
     *         array['link' => absolute path to file or multiple files, if wildcards are used,
     *               'fragment' => fragment part of the url (to match specific ID on the page)
     *               'serverpath' => set to server path if exsits,
     *               'internal_link' => set if dokuwiki internal link]
     */
    public function parse_src($src) {
        $ret = false;
        $src = strtolower($src);

        if(preg_match('/^\s*[%\{\[].*[%\}\]]\s*$/s', $src)) {
            //json object{...} or array[...] or extractor %$...%
            $ret = $src;
        }
        else if(preg_match('#^([a-z0-9\-\.+]+?)://#i', $src)) {
            //external link (accepts all protocols)
            $ret = array('link' => $src);
        }
        else if(preg_match('/^[\w\/:.#\!\*\?\[\^\-\]\{\,\}]+$/', $src)) {
            global $conf;

            //DokuWiki internal link with optional wildcards
            list($base, $fragment) = array_pad(explode('#', $src), 2, '');

            //Resolve to absolute page ID
            $resolver = new CustomResolver(getID());
            $base = $resolver->resolveId($base);

            if(strlen($base) > 0) {
                $ret = array('serverpath' => $conf['datadir']);

                if($base === cleanID($base)) {
                    $ret['internal_link'] = $base;
                }
                if($base[0] !== ':') {
                    $base = ':'.$base;
                }
                $base = str_replace(':', '/', $base);

                $ret['link'] = $ret['serverpath'].$base.'.txt';
                $ret['fragment'] = $fragment;
            }
        }

        return $ret;
    }


    /**
     * Parse a string into key - value pairs.
     *
     * Single or double quotes can be used for key or value. Single quotes
     * can be nested inside double and vice versa. Empty value can be set
     * with empty quotes.
     * Spaces, newlines, etc. are completely ignored, except inside quotes.
     * There can be multiple quotes for one argument, for example
     * key = car.'Alfa Romeo'
     *          .'155 GTA'
     * will give: ["key"] => "car.Alfa Romeo.155 GTA"
     *
     * @param string $str string to parse
     * @param string $key_delim_val delimiter character between the key and value, space is not allowed
     * @param string $key_val_delim delimiter character after the key and value pair, space is allowed
     *
     * @return array with all options or integer with location of error
     */
    public function parse_key_val($str, $key_delim_val = '=', $key_val_delim = ' ') {
        $options = array();     //return value
        $quote = false;         //is inside quote " or '
        $quote_closed = false;  //quote was closed - in use when we want to pass empty value ""
        $key = $val = '';       //contents of current key and value
        $arg = &$key;           //reference to key or to value
        $arg_is_key = true;     //to which is arg the reference
        $error = false;         //error indication

        $len = strlen($str);
        for($i = 0; $i < $len; $i++) {
            $c = $str[$i];
            if(!$quote && ($c === '"' || $c === '\'')) {
                $quote = $c;
            }
            else if($c === $quote) {
                $quote = false;
                $quote_closed = true;
            }
            else if($quote !== false) {
                //inside quote add all
                $arg .= $c;
            }
            else if($c === $key_delim_val) {
                if($arg_is_key && strlen($key) > 0) {
                    $arg = &$val;
                    $arg_is_key = false;
                    $quote_closed = false;
                }
                else {
                    $error = true;
                    break;
                }
            }
            else if($c === $key_val_delim) {
                if(!$arg_is_key && (strlen($val) > 0 || $quote_closed)) {
                    $options[$key] = $val;
                    $key = $val = '';
                    $arg = &$key;
                    $arg_is_key = true;
                    $quote_closed = false;
                }
                else if(!ctype_space($c)) {
                    $error = true;
                    break;
                }
            }
            else if(!ctype_space($c)) { //just ignore spaces which are not inside quotes or are delimitters
                $arg .= $c;
            }
        }

        //write last pair
        if(!$error && strlen($key) > 0) {
            if(!$arg_is_key && (strlen($val) > 0 || $quote_closed)) {
                $options[$key] = $val;
            }
            else {
                $error = true;
            }
        }

        return $error ? $i : $options;
    }


    /**
     * Parse tokens from string (variable chain)
     *
     * @param string $str "per. pets. 0 . main color"
     *
     * @return array of tokens: ["per", "pets", "0", "main color"]
     */
    public function parse_tokens($str) {
        if(is_string($str)) {
            //remove extra spaces
            $str = trim(preg_replace('/\s*\.\s*/', '.', $str), ". \t\n\r\0\x0B");
            return $str==="" ? array() : explode('.', $str);
        }
        else {
            return array();
        }
    }


    /**
     * Parse key=>tokenized_link pairs.
     *
     * @param string $str '"Name":name, "Main color" : color .main'
     *
     * @return array of tokenized links or "" on empty string or false on syntax error
     *          ["Name" => [name], "Main color" => [color, main]]
     */
    public function parse_links($str) {
        $str = trim($str);
        if($str) {
            $pairs = helper_plugin_json::parse_key_val($str, ':', ',');
            if(is_array($pairs)) {
                foreach ($pairs as &$val) {
                    $val = helper_plugin_json::parse_tokens($val);
                }
                return $pairs;
            }
            else {
                return false;
            }
        }
        else {
            return "";
        }
    }


    /**
     * Parse filter expression for table
     *
     * @param string $str 'path.to.var >= some_value and path.2 < other_value'
     *
     * @return array of logical expressions object:
     *          ["and" => boolean, "tokens" => array, "operator" => string, "value" => string]
     */
    public function parse_filter($str) {
        $filter = array();
        if($str) {
            $exp = preg_split('/\b(and|or)\b/i' , $str , -1 , PREG_SPLIT_DELIM_CAPTURE);
            array_unshift($exp, 'or');

            while(count($exp) >= 2) {
                $and = (strtolower(array_shift($exp)) === 'and') ? true : false;
                list($tokens, $op, $val) = array_pad(preg_split('/(<=|>=|!=|=+|<|>)/',
                                array_shift($exp), -1 , PREG_SPLIT_DELIM_CAPTURE), 3, '');
                if($op === '') {
                    $op = '!=';
                }
                else if ($op[0] === '=') {
                    //operators '=', '==' and '===' are the same.
                    $op = '==';
                }

                $filter[] = array(
                    'and' => $and,
                    'tokens' => helper_plugin_json::parse_tokens($tokens),
                    'operator' => $op,
                    'value' => strtolower(trim($val))
                );
            }
        }
        return $filter;
    }


    /**
     * Verify filter for variable
     *
     * @param array $var json variable
     * @param array $filter as returned from parse_filter
     *
     * @return boolean true, if variable matches the filter
     */
    public function filter($var, $filter) {
        $match = false;
        foreach($filter as $f) {
            $v = $var;
            foreach($f['tokens'] as $tok) {
                if(is_array($v) && isset($v[$tok])) {
                    $v = $v[$tok];
                }
                else {
                    $v = null;
                    break;
                }
            }
            //case insensitive comparission of strings
            if(is_string($v)) {
                $v = strtolower($v);
            }
            switch($f['operator']) {
                case '==': $comp = ($v == $f['value']); break;
                case '!=': $comp = ($v != $f['value']); break;
                case '<':  $comp = ($v <  $f['value']); break;
                case '>':  $comp = ($v >  $f['value']); break;
                case '<=': $comp = ($v <= $f['value']); break;
                case '>=': $comp = ($v >= $f['value']); break;
                default:   $comp = false; break;
            }
            $match = $f['and'] ? ($match && $comp) : ($match || $comp);
        }
        return $match;
    }


    /**
     * Handle extractors inside string
     *
     * @param string $str input string, which contains '%$path[(row_filter){row_inserts}](filter)%' elements inside
     *
     * @return array of extractor data:
     *          ["tokens" => array, "row_filter" => array, "row_inserts" => array, "filter" => array]
     */
    private static $extractor_reg = '/%\$([^[\]\(\)]*?)(?:\[(?:\((.*?)\))?(?:\{(.*?)\})?\])?\s*(?:\((.*?)\))?\s*%/s';
    public function extractors_handle($str) {
        $extractors = array();

        preg_match_all(helper_plugin_json::$extractor_reg, $str, $matches_all, PREG_SET_ORDER);
        foreach ($matches_all as $matches) {
            list(, $tokens, $row_filter, $row_inserts, $filter) = array_pad($matches, 5, '');

            //handle row inserts: {property_path: json_path_1.{reference_path}.json_path_2, ... }
            $row_inserts_array = array();
            $row_inserts = trim($row_inserts);
            if($row_inserts) {
                $row_inserts = helper_plugin_json::parse_key_val($row_inserts, ':', ',');
                if(is_array($row_inserts)) {
                    foreach ($row_inserts as $key => $val) {
                        if(preg_match('/^(.*?)\.\{(.*?)\}(?:\.(.*))?$/', $val, $matches_insert)) {
                            $row_inserts_array[] = array(
                                'property_path'  => helper_plugin_json::parse_tokens(strval($key)),
                                'json_path_1'    => helper_plugin_json::parse_tokens($matches_insert[1]),
                                'reference_path' => helper_plugin_json::parse_tokens($matches_insert[2]),
                                'json_path_2'    => helper_plugin_json::parse_tokens($matches_insert[3])
                            );
                        }
                    }
                }
            }

            $extractors[] = array(
                'tokens' => helper_plugin_json::parse_tokens($tokens),
                'row_filter' => helper_plugin_json::parse_filter($row_filter),
                'row_inserts' => $row_inserts_array,
                'filter' => helper_plugin_json::parse_filter($filter)
            );
        }
        return $extractors;
    }


    /**
     * Replace extractors inside string
     *
     * @param string $str input string, which contains '%$ ... %' elements inside
     * @param array $extractors as returned from extractors_handle
     * @param array $json_database If specified, it will be used for source data.
     *              Othervise current JSON database will be used.
     *
     * @return string with extractors replaced by variables from json database.
     */
    public function extractors_replace($str, $extractors, $json_database = NULL) {
        $replaced = preg_replace_callback(
            helper_plugin_json::$extractor_reg,
            function ($matches) use (&$extractors, $json_database) {
                $result = '';
                $ext = array_shift($extractors);
                $json_var = helper_plugin_json::get($ext['tokens'], $json_database);
                if(isset($json_var)) {
                    if(count($ext['filter']) > 0 && !helper_plugin_json::filter($json_var, $ext['filter'])) {
                        unset($json_var);
                    }
                    else if (count($ext['row_filter']) > 0) {
                        //remove all elements from $json_var array, which do not match filter
                        if(is_array($json_var)) {
                            //are keys in sequence: 0, 1, 2, ...
                            $i = 0;
                            $indexed = true;
                            foreach($json_var as $key => $val) {
                                if($key !== $i++) {
                                    $indexed = false;
                                    break;
                                }
                            }
                            //filter out rows
                            $json_var = array_filter($json_var, function ($var) use ($ext) {
                                return helper_plugin_json::filter($var, $ext['row_filter']);
                            });
                            //re-index array
                            if($indexed) {
                                $json_var = array_values($json_var);
                            }
                        }
                        else {
                            unset($json_var);
                        }
                    }
                }
                //add row inserts
                if(is_array($json_var)) foreach($json_var as &$item) {
                    if(is_array($item)) foreach($ext['row_inserts'] as $row_insert) { //if $item is not array, it's no sense to add additional property
                        //get reference string from specified $item property
                        if(count($row_insert['reference_path']) === 0) {
                            $reference = [];
                        }
                        else {
                            $reference = helper_plugin_json::get($row_insert['reference_path'], $item);
                            if(is_string($reference)) {
                                $reference = array($reference);
                            }
                            else {
                                continue;
                            }
                        }
                        //get referenced path and value
                        $val_path = array_merge($row_insert['json_path_1'], $reference, $row_insert['json_path_2']);
                        $val = helper_plugin_json::get($val_path, $json_database);

                        //add new property to specified item path
                        $item_copy = &$item;
                        foreach($row_insert['property_path'] as $tok) {
                            if(!is_array($item_copy)) {
                                $item_copy = array();
                            }
                            $item_copy[$tok] = null;
                            $item_copy = &$item_copy[$tok];
                        }
                        $item_copy = $val;
                        unset($item_copy);
                    }
                }

                return is_string($json_var) ? $json_var : json_encode($json_var);
            },
            $str
        );

        return $replaced;
    }


    /**
     * Handle json description element
     *
     * @param string $element <json_yxz key1=val1 ...>{ json_data }</json>
     * @param string $xml_tag If $element is NULL, then $tag, $attributes and $content are parsed. Othervise ignored.
     * @param string $xml_attributes same as $xml_tag
     * @param string $xml_content same as $xml_tag, may be undefined also if $element is undefined.
     *
     * @return array [  tag => string,          //element tag name ('json_yxz' in above case)
     *                  error => string,        //if set, then element is not valid
     *                  keys => array,          //XML attributes parsed
     *                  id => string,           //id of the element, '' if not set.
     *                  json_inline_raw => string,  //internal JSON data as raw string, unverified.
     *                  json_inline_extractors => array,  //extractors inside json_inline_raw string. Will be replaced by values from json database.
     *                  path => ['clear' => bool, 'array' => bool, tokens => array] //from XML path attribute. It indicates, where and how data will be added to $json
     *                  src => array['link', 'fragment', 'serverpath', 'internal_link'] //filename from XML src attribute
     *                  src_path => array]      //from XML src_path attribute. It indicates, which part of src have to be added to $json.
     */
    public function handle_element($element, $xml_tag=NULL, $xml_attributes=NULL, $xml_content=NULL) {
        //return value
        $data = array();

        if(isset($element)) {
            //Replace #@macro_name@# patterns with strings defined by textinsert Plugin.
            $element = helper_plugin_json::preprocess($element);

            //parse element
            if(preg_match('/^<(json[a-z0-9]*)\b([^>]*)>(.*)<\/\1>$/s', $element, $matches) !== 1) {
                //this is more strict pattern than inside connectTo() function. Just ignore the element.
                return NULL;
            }
            list( , $xml_tag, $xml_attributes, $xml_content) = array_pad($matches, 4, '');
        }
        else {
            //Replace #@macro_name@# patterns with strings defined by textinsert Plugin.
            if($xml_attributes !== '') {
                $xml_attributes = helper_plugin_json::preprocess($xml_attributes);
            }
            if($xml_content !== '') {
                $xml_content = helper_plugin_json::preprocess($xml_content);
            }
        }

        $data['tag'] = $xml_tag;
        if($xml_attributes !== '') {
            $ret = helper_plugin_json::parse_key_val($xml_attributes);
            if(is_array($ret)) {
                $data['keys'] = $ret;
                $data['id'] = $data['keys']['id'] ?? '';
            }
            else {
                $err = "attributes syntax at $ret";
            }
        }
        else if($xml_tag === '') {
            $err = 'element syntax';
        }

        //get internal JSON data if present
        $data['json_inline_raw'] = $xml_content;
        $data['json_inline_extractors'] = helper_plugin_json::extractors_handle($xml_content);

        //parse attribute 'path' and 'src_path' of the JSON object: -path.el2.0.el4[]
        if(!isset($err)) {
            if(isset($data['keys']['path'])) {
                $val = $data['keys']['path'];

                $val_name = array('clear' => false, 'array' => false);
                if(substr($val, 0, 1) === '-') {
                    $val = substr($val, 1);
                    $val_name['clear'] = true;
                }
                if(substr($val, -2) === '[]') {
                    $val = substr($val, 0, -2);
                    $val_name['array'] = true;
                }
                $val_name['tokens'] = helper_plugin_json::parse_tokens($val);
                $data['path'] = $val_name;
            }
            else {
                $data['path'] = array('clear' => false, 'array' => false, 'tokens' => array());
            }
            if(isset($data['keys']['src_path'])) {
                $data['src_path'] = helper_plugin_json::parse_tokens($data['keys']['src_path']);
            }
        }

        //parse attribute 'src' with filepath to the JSON data
        if(!isset($err) && isset($data['keys']['src'])) {
            $val = $data['keys']['src'];

            $data['src'] = helper_plugin_json::parse_src($val);
            if(is_string($data['src'] ?? null)) {
                $data['src_extractors'] = helper_plugin_json::extractors_handle($data['src']);
            }
            else if($data['src'] === false) {
                $err = "'src' attribute syntax";
            }
        }

        //If archive attribute contains json data, then this data will be
        //loaded and src attribute will be ignored
        if(!isset($err) && isset($data['keys']['archive'])) {
            if(strtolower($data['keys']['archive']) === 'make') {
                //data is is not yet archived. User action will write data from
                //html 'json-data-original' into dokuwiki 'archive' attribute.
                $data['make_archive'] = true;
            }
            else if(strtolower($data['keys']['archive']) === 'disable') {
                //data is not yet archived. User action will disable
                //'src', 'scr_ext' and 'archive' attributes
                $data['make_archive'] = true;
            }
            else {
                //get data from archive, not from src
                $src_archive = json_decode($data['keys']['archive'], true);
                if(isset($src_archive)) {
                    $data['src_archive'] = $src_archive;
                }
                else {
                    $err = '\'archive\' attribute syntax, internal JSON '.json_last_error_msg();
                }
            }
        }

        if(isset($err)) {
            $data['error'] = $err;
        }

        return $data;
    }


    /**
     * Add json data to database
     *
     * @param array $json_database External array, where data will be added (database).
     * @param array $data Data from handle_element(). Two elements will be added:
     *              'json_original' and 'json_combined'.
     * @param integer $recursion_depth If greater than zero, then this function
     *      will recursively decode <json>, if it has src attribute.
     * @param array $log database with info about data sources for the element
     *  [
     *      'tag' => string,    //element tag name
     *      'error' => string,  //error string or unset
     *      'path' => string,   //data path
     *      'inline' => bool,   //is inline data present
     *      'src_archive' => bool,   //is src_archive data present
     *      'src_path' => array,//path on src or unset
     *      'src' => array [    //log about external files or unset
     *          0 => [
     *              'filename' => string,     //name of the internal or external link
     *              'extenal_link' => bool,   //is 'filename' external link
     *              'error' => string,        //error string or unset
     *              'elements' => array [
     *                  [                    //first element inside file
     *                      recursive data (tag, error, path, etc.)
     *                  ],
     *                  [...], ...          //next elements
     *              ]
     *          ],
     *          1 => [...], ...                 //next files
     *      ]
     *  ]
     */
    public function add_json(&$json_database, &$data, $recursion_depth, &$log) {
        $path = $data['path'];
        $src = isset($data['src']) ? $data['src'] : null;
        $src_path = isset($data['src_path']) ? $data['src_path'] : null;

        //set $json to specified path
        $json = &$json_database;
        foreach($path['tokens'] as $tok) {
            $json_parent = &$json;
            $json_parent_tok = $tok;
            if(!is_array($json)) {
                $json = array($tok => null);
            }
            $json = &$json[$tok];
        }


        //clear previous data, if necessary
        if($path['clear']) {
            $json = null;
        }
        else {
            //don't remove the variable, if it is null on the end
            unset($json_parent);
            unset($json_parent_tok);
        }


        //load archived data
        if(isset($data['src_archive'])) {
            $json = $data['src_archive'];
            $log['src_archive'] = true;
        }
        //or load JSON string from src attribute
        else if(is_string($src)) {
            //log, return value
            $log['src'] = array();

            $log['src_path'] = is_array($src_path) ? implode('.', $src_path) : '';
            $log_file = array('filename' => '***JSON code***');

            //replace extractors (%$path.to.var%) with data from json database
            if(count($data['src_extractors']) > 0) {
                $src = helper_plugin_json::extractors_replace(trim($src), $data['src_extractors'], $json_database);
            }

            $json_src = json_decode($src, true);
            if(isset($json_src)) {
                helper_plugin_json::add_data($json, $path['array'], $json_src, $src_path, $log_file);
            }
            else {
                $log_file['error'] = 'JSON '.json_last_error_msg();
            }
            $log['src'][] = $log_file;
        }
        //or load data from external file(s), recursively if necessary
        else if(is_array($src) && $recursion_depth > 0) {
            //log, return value
            $log['src'] = array();
            $log['src_path'] = is_array($src_path) ? implode('.', $src_path) : '';

            //prepare id for regular expression
            $fragment_reg = (is_string($src['fragment'] ?? null) && $src['fragment'] !== '') ? 'id\s*=\s*'.$src['fragment'].'\b' : "";

            //get file names
            if(is_string($src['serverpath'] ?? null)) {
                //internal link
                $files = array();
                foreach (glob($src['link'], GLOB_BRACE) as $filename) {
                    if(is_file($filename)) {
                        $files[] = $filename;
                    }
                }
                if(count($files) === 0) {
                    $filename_log = str_replace($src['serverpath'].'/', '', $src['link']);
                    $filename_log = preg_replace('/\.txt$/', '', $filename_log);
                    $filename_log = str_replace('/', ':', $filename_log);
                    $log['src'][] = array('filename' => $filename_log, 'error' => 'file not found');
                }
            }
            else {
                //external link
                $files = array($src['link']);
            }

            foreach ($files as $filename) {
                $file_found = true;
                $json_src = array();
                $extenal_link = false;

                //filename for write into log, file_id for authentication check
                if(is_string($src['serverpath'] ?? null)) {
                    //internal link
                    $filename_log = str_replace($src['serverpath'].'/', '', $filename);
                    $filename_log = preg_replace('/\.txt$/', '', $filename_log);
                    $filename_log = str_replace('/', ':', $filename_log);
                    $auth = (auth_quickaclcheck($filename_log) >= AUTH_READ);
                    $log_file = array('filename' => $filename_log);
                }
                else {
                    //external link (https://xxxx)
                    $log_file = array('filename' => $filename, 'extenal_link' => true);
                    $extenal_link = true;
                    $auth = true;
                }
                if(is_string($src['fragment'] ?? null) && $src['fragment'] !== '') {
                    $log_file['filename'] .= '#'.$src['fragment'];
                }

                //verify if user is authorized to read the file
                if($auth === true) {
                    if($extenal_link) {
                        $curl = curl_init();
                        curl_setopt($curl, CURLOPT_URL, $filename);
                        curl_setopt($curl, CURLOPT_RETURNTRANSFER, true);
                        curl_setopt($curl, CURLOPT_HEADER, false);
                        $text = curl_exec($curl);
                        curl_close($curl);
                    }
                    else {
                        $text = file_get_contents($filename);
                    }

                    if($text) {
                        $json_src = json_decode($text, true);
                        if(isset($json_src)) {
                            //file with pure JSON data
                            helper_plugin_json::add_data($json, $path['array'], $json_src, $src_path, $log_file);
                        }
                        else if(preg_match_all('/<(json[a-z0-9]*)\b([^>]*?'.$fragment_reg.'[^>]*?)>(.*?)<\/\1>/is',
                                                $text, $matches_all, PREG_SET_ORDER)) {
                            //find json data inside <json> element(s)
                            $json_src = null;
                            foreach ($matches_all as $matches) {
                                $data_elem = helper_plugin_json::handle_element(NULL, $matches[1], $matches[2], $matches[3]);

                                if($data_elem === NULL) {
                                    continue;
                                }

                                $log_elem = array('tag' => $matches[1], 'id' => $data_elem['id'] ?? '', 'path' => $data_elem['keys']['path'] ?? null,
                                                'inline' => (strlen(trim($data_elem['json_inline_raw'])) > 0));

                                if(!isset($data_elem['error'])) {
                                    //add json data into empty database
                                    if(strlen($fragment_reg) > 0) {
                                        //just pick one specific json data, don't buld database from whole file
                                        $data_elem['path']['tokens'] = array();
                                        $data_elem['path']['array'] = false;
                                    }
                                    helper_plugin_json::add_json($json_src, $data_elem, $recursion_depth-1, $log_elem);
                                }
                                else {
                                    $log_elem['error'] = $data_elem['error'];
                                }
                                $log_file['elements'][] = $log_elem;
                                if(strlen($fragment_reg) > 0) {
                                    break;
                                }
                            }
                            helper_plugin_json::add_data($json, $path['array'], $json_src, $src_path, $log_file);
                        }
                        else {
                            $log_file['error'] = 'no JSON data, '.json_last_error_msg();
                        }
                    }
                    else {
                        $log_file['error'] = 'empty file';
                    }
                }
                else {
                    $log_file['error'] = 'file access denied';
                }
                $log['src'][] = $log_file;
            }
        }
        else if(is_array($src)) {
            //Error, recursion limit reached
            if(is_string($src['serverpath'] ?? null)) {
                //internal link
                $filename_log = str_replace($src['serverpath'].'/', '', $src['link']);
                $filename_log = preg_replace('/\.txt$/', '', $filename_log);
                $filename_log = str_replace('/', ':', $filename_log);
                $log['src'][] = array('filename' => $filename_log, 'error' => 'recursion limit reached');
            }
            else {
                //external link (https://xxxx)
                $log['src'][] = array('filename' => $src['link'], 'extenal_link' => true, 'error' => 'recursion limit reached');
            }
        }

        //save original JSON data
        $data['json_original'] = $json;


        //load internal json data
        $json_inline_raw = trim($data['json_inline_raw']);
        if(strlen($json_inline_raw) > 0) {
            //replace extractors (%$path.to.var%) with data from json database
            if(count($data['json_inline_extractors']) > 0) {
                $json_inline_raw = helper_plugin_json::extractors_replace($json_inline_raw, $data['json_inline_extractors'], $json_database);
            }

            $json_inline = json_decode($json_inline_raw, true);
            if(isset($json_inline)) {
                helper_plugin_json::add_data($json, $path['array'], $json_inline);
            }
            else {
                $log['error'] = 'internal JSON '.json_last_error_msg();
            }
        }


        //if element is empty, remove it from the database
        if(!isset($json) && isset($json_parent)) {
            unset($json_parent[$json_parent_tok]);
        }

        //save combined JSON data
        $data['json_combined'] = $json;
    }


    /**
     * Put data into database (array).
     *
     * @param array $path array of tokens for path in database.
     * @param array $data to put in database.
     * @param bool $clear first clear data from database path
     * @param bool $append if true, append data to database path, othervise
     *        combine data with array_replace_recursive() PHP function.
     *
     * @return data from the path
     */
    public function put($path, $data, $clear = false, $append = false) {
        $json = &helper_plugin_json::$json;
        foreach($path as $tok) {
            $json_parent = &$json;
            $json_parent_tok = $tok;

            if(!(isset($json[$tok]) && is_array($json[$tok]))) {
                $json[$tok] = array();
            }
            $json = &$json[$tok];
        }

        if($clear) {
            $json = array();
        }

        if($append) {
            $json[] = $data;
        }
        else if(is_array($data)) {
            $json = array_replace_recursive($json, $data);
        }

        //if element is empty, remove it from array
        if(count($json) === 0 && isset($json_parent)) {
            unset($json_parent[$json_parent_tok]);
        }

        return $json;
    }


    /**
     * Get data from database (array).
     *
     * @param array $path array of tokens for path in database.
     * @param array $json_database If specified, it will be used for source data.
     *              Othervise current JSON database will be used.
     *
     * @return mixed data
     */
    public function get($path = array(), $json_database = NULL) {
        $var = NULL;
        if(is_array($path)) {
            $var = isset($json_database) ? $json_database : helper_plugin_json::$json;
            foreach($path as $tok) {
                if(!is_array($var)) {
                    $var = NULL;
                    break;
                }
                if ($tok === '_FIRST_') {
                    $var = $var[array_key_first($var)];
                }
                else if ($tok === '_LAST_') {
                    $var = $var[array_key_last($var)];
                }
                else {
                    $var = $var[$tok] ?? null;
                }
            }
        }
        return $var;
    }


    /**
     * Add data into database
     *
     * @param mixed $json_database - external array, where data will be added (database).
     * @param bool  $append - if true, data will be appended, othervise it will be added or replaced.
     * @param mixed $json_src - data to add.
     * @param array $src_path - if defined, then only specific part of $json_src will be added.
     * @param array $log - if error, it will be indicated here.
     */
    private function add_data(&$json_database, $append, $json_src, $src_path = null, &$log = null) {
        if(is_array($src_path)) {
            foreach($src_path as $tok) {
                if(!isset($json_src[$tok])) {
                    unset($json_src);
                    break;
                }
                $json_src = $json_src[$tok];
            }
        }
        if(isset($json_src)) {
            if($append) {
                if(is_array($json_database)) {
                    $json_database[] = $json_src;
                }
                else {
                    $json_database = array($json_src);
                }
            }
            else {
                if(is_array($json_database) && is_array($json_src)) {
                    $json_database = array_replace_recursive($json_database, $json_src);
                }
                else {
                    $json_database = $json_src;
                }
            }
        }
        else if(isset($log)) {
            $log['error'] = 'no data';
            if(is_array($src_path)) {
                $log['error'] .= ' on src_path: \''.implode('.', $src_path).'\'';
            }
        }
    }


    public function getMethods() {
        $result = array();
        $result[] = array(
            'name' => 'preprocess',
            'desc' => 'Preprocess matched string',
            'params' => array(
                'str' => 'string'
            ),
            'return' => 'string'
        );
        $result[] = array(
            'name' => 'parse_src',
            'desc' => 'Evaluate src attribute',
            'params' => array(
                'src' => 'string'
            ),
            'return' => array('link' => 'string', 'fragment' => 'string', 'serverpath' => 'string', 'internal_link' => 'string')
        );
        $result[] = array(
            'name' => 'parse_key_val',
            'desc' => 'parse a string into key - value pairs',
            'params' => array(
                'str' => 'string',
                'key_delim_val' => 'string',
                'key_val_delim' => 'string'
            ),
            'return' => array('pairs' => 'array', 'error' => 'int')
        );
        $result[] = array(
            'name' => 'parse_tokens',
            'desc' => 'parse tokens from string "tok1[tok2].tok3',
            'params' => array(
                'str' => 'string'
            ),
            'return' => array('tokens' => 'array')
        );
        $result[] = array(
            'name' => 'parse_links',
            'desc' => 'parse key=>tokenized_link pairs',
            'params' => array(
                'str' => 'string'
            ),
            'return' => array('pairs' => 'array', 'error' => 'bool', 'empty' => 'string')
        );
        $result[] = array(
            'name' => 'parse_filter',
            'desc' => 'parse filter expression for table',
            'params' => array(
                'str' => 'string'
            ),
            'return' => array('filter' => 'function', 'links' => 'array')
        );
        $result[] = array(
            'name' => 'filter',
            'desc' => 'verify filter for variable',
            'params' => array(
                'var' => 'array',
                'filter' => 'array'
            ),
            'return' => 'boolean'
        );
        $result[] = array(
            'name' => 'extractors_handle',
            'desc' => 'handle extractors inside string',
            'params' => array(
                'str' => 'string'
            ),
            'return' => array('tokens' => 'array', 'row_filter' => 'array', 'row_inserts' => 'array', 'filter' => 'array')
        );
        $result[] = array(
            'name' => 'extractors_replace',
            'desc' => 'replace extractors inside string',
            'params' => array(
                'str' => 'array',
                'filter' => 'array'
            ),
            'return' => 'string'
        );
        $result[] = array(
            'name' => 'add_json',
            'desc' => 'Add json data to database',
            'params' => array(
                'json_database' => 'array',
                'data' => 'array',
                'recursion_depth' => 'integer',
                'log' => 'array'
            )
        );
        $result[] = array(
            'name' => 'put',
            'desc' => 'put data into database',
            'params' => array(
                'path' => 'array',
                'data' => 'array',
                'clear' => 'bool',
                'append' => 'bool'
            ),
            'return' => array('data' => 'array|NULL')
        );
        $result[] = array(
            'name' => 'get',
            'desc' => 'get data from database',
            'params' => array(
                'path' => 'array',
                'json_database' => 'array'
            ),
            'return' => array('data' => 'mixed|NULL')
        );
        return $result;
    }
}
