<?php
/**
 * DokuWiki Plugin json (Action Component)
 *
 * @license GPL 2 http://www.gnu.org/licenses/gpl-2.0.html
 * @author  Janez Paternoster <janez.paternoster@siol.net>
 */

// must be run within Dokuwiki
if (!defined('DOKU_INC')) {
    die();
}

//Resolve to absolute page ID
use dokuwiki\File\PageResolver;

class action_plugin_json extends DokuWiki_Action_Plugin
{

    /**
     * Registers a callback function for a given event
     *
     * @param Doku_Event_Handler $controller DokuWiki's event controller object
     *
     * @return void
     */
    public function register(Doku_Event_Handler $controller) {
        $controller->register_hook('DOKUWIKI_STARTED', 'AFTER',  $this, 'handle_jsinfo');
        $controller->register_hook('AJAX_CALL_UNKNOWN', 'BEFORE', $this, 'handle_ajax_call_unknown');
    }


    /**
     * Handle event DOKUWIKI_STARTED - add data to JSINFO
     *
     * @param Doku_Event $event  event object by reference
     * @param mixed      $param  [the parameters passed as fifth argument to register_hook() when this
     *                           handler was registered]
     */
    public function handle_jsinfo(&$event, $param) {
        global $JSINFO;
        global $ID;

        if(page_exists($ID)) {
            $JSINFO['json_lastmod'] = filemtime(wikiFN($ID));
            $JSINFO['enable_ejs'] = $this->getConf('enable_ejs');
        }
    }


    /**
     * Handle event AJAX_CALL_UNKNOWN for json_plugin_save_inline and
     * json_plugin_archive call
     *
     * @param Doku_Event $event  event object by reference
     * @param mixed      $param  [the parameters passed as fifth argument to register_hook() when this
     *                           handler was registered]
     *
     * @return Ajax response as json
     */
    public function handle_ajax_call_unknown(Doku_Event $event, $param) {
        if ($event->data === 'json_plugin_save_inline') {
            $this->ajax_save_inline($event, $param);
        }
        else if ($event->data === 'json_plugin_archive') {
            $this->ajax_archive($event, $param);
        }
    }

    private function ajax_save_inline(Doku_Event $event, $param) {
        //no other ajax call handlers needed
        $event->stopPropagation();
        $event->preventDefault();

        //access additional request variables
        global $INPUT;
        $page_to_modify = $INPUT->str('file');
        $json_id = $INPUT->str('id');
        $hash_received = $INPUT->str('hash');
        $text_received = $INPUT->str('text');

        $resolver = new PageResolver('');
        $page_to_modify = $resolver->resolveId($page_to_modify);

        $err = '';
        $hash_new = '';

        if(!page_exists($page_to_modify)) {
            $err = sprintf($this->getLang('file_not_found'), $page_to_modify);
        }
        //verify file write rights
        else if(auth_quickaclcheck($page_to_modify) < AUTH_EDIT) {
            $err = sprintf($this->getLang('permision_denied_write'), $page_to_modify);
        }
        //verify id
        else if(!$json_id) {
            $err = sprintf($this->getLang('missing_id'), $page_to_modify);
        }

        //verify lock
        $locked = false;
        if($err === '') {
            if(checklock($page_to_modify)) {
                $err = sprintf($this->getLang('file_locked'), $page_to_modify);
            }
            else {
                lock($page_to_modify);
                $locked = true;
            }
        }

        //read the file
        if($err === '') {
            $file = rawWiki($page_to_modify);
            if(!$file) {
                $err = sprintf($this->getLang('file_not_found'), $page_to_modify);
            }
        }

        //replace json data; must be one match
        if($err === '') {
            $file_updated = preg_replace_callback(
                '/(<(json[a-z0-9]*)\b[^>]*?id\s*=[\s"\']*'.$json_id.'\b.*?>)(.*?)(<\/\2>)/s',
                function($matches) use(&$err, $hash_received, $text_received, &$hash_new) {
                    //Make sure, no one changed the original data. Ajax call must know the md5 hash
                    //of the actual data saved inside the file. If someone changed the data between
                    //page reload (or previous ajax call) and last ajax call, then last ajax call
                    //will fail with error message.
                    $hash_original = md5($matches[3]);
                    if($hash_original === $hash_received) {
                        $replacement = $matches[1].$text_received.$matches[4];
                        $hash_new = md5($text_received);
                        return $replacement;
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
                    $err = sprintf($this->getLang('hash_not_equal'), $json_id);
                }
            }
            else {
                $err = sprintf($this->getLang('internal_error'), 'plugin/json/action');
            }
        }

        //write file
        if($err === '') {
            saveWikiText($page_to_modify, $file_updated, sprintf($this->getLang('json_updated_ajax'), $json_id), true);
            $response = array('response' => 'OK', 'hash' => $hash_new);
        }
        else {
            $response = array('response' => 'error', 'error' => $err);
        }

        //unlock for editing
        if($locked === true) {
            unlock($page_to_modify);
        }

        //send response
        header('Content-Type: application/json');
        echo json_encode($response);
    }

    private function ajax_archive(Doku_Event $event, $param) {
        //no other ajax call handlers needed
        $event->stopPropagation();
        $event->preventDefault();

        //access additional request variables
        global $INPUT;
        $page_to_modify = $INPUT->str('file');
        $resolver = new PageResolver('');
        $page_to_modify = $resolver->resolveId($page_to_modify);

        $lastmod_current = filemtime(wikiFN($page_to_modify));
        $lastmod_call = $INPUT->str('lastmod');
        $data_original = $INPUT->arr('data');
        $subdir = $INPUT->str('subdir');
        $err = '';

        if(!page_exists($page_to_modify)) {
            $err = sprintf($this->getLang('file_not_found'), $page_to_modify);
        }
        //verify file write rights
        else if(auth_quickaclcheck($page_to_modify) < AUTH_EDIT) {
            $err = sprintf($this->getLang('permision_denied_write'), $page_to_modify);
        }
        //verify if page was not modified
        else if($lastmod_call != $lastmod_current) {
            $err = sprintf($this->getLang('file_changed'), $page_to_modify);
        }

        //verify lock
        $locked = false;
        if($err === '') {
            if(checklock($page_to_modify)) {
                $err = sprintf($this->getLang('file_locked'), $page_to_modify);
            }
            else {
                lock($page_to_modify);
                $locked = true;
            }
        }

        //read the file
        if($err === '') {
            $file = rawWiki($page_to_modify);
            if(!$file) {
                $err = sprintf($this->getLang('file_not_found'), $page_to_modify);
            }
        }

        //replace json data
        if($err === '') {
            $counter = 0;
            $file_updated = preg_replace_callback(
                '/(<(json[a-z0-9]*)\b[^>]*?)(archive\s*=\s*(["\']?)(make|disable)\4)(.*?>)(.*?<\/\2>)/is',
                function($matches) use($data_original, &$counter) {
                    //el_1='<jsonxx ...', el_2='achive=make', el_3=' ...>', rest='... </jsonxxx>'
                    list(, $el_1, ,$el_2, ,$make_disable, $el_3, $rest) = $matches;
                    if($make_disable === 'make') {
                        $data = $data_original[$counter];
                        $data = str_replace('\'', '&#39;', $data);
                        $data = str_replace('<', '&lt;', $data);
                        $data = str_replace('>', '&gt;', $data);
                        $element =  $el_1."archive=\n'$data'\n".$el_3;
                    }
                    else {
                        $element = $el_1.'archive_disabled=disable'.$el_3;
                        $element = preg_replace('/\bsrc\s*=/', 'src_disabled=', $element);
                        $element = preg_replace('/\bsrc_ext\s*=/', 'src_ext_disabled=', $element);
                    }
                    $counter++;
                    return $element.$rest;
                },
                $file
            );
            if($counter === 0 || $counter !== count($data_original)) {
                $err = 'Internal error - number of <json archive=make ...>('.$counter
                    .') is zero or not equal to number of requests('.count($data_original).')';
            }
        }

        if($err === '') {
            //move the file to the sub directory
            if ($subdir) {
                if (str_contains($page_to_modify, ':')) {
                    $newId = preg_replace('/^(.*:)([^:]+)$/',
                                          '${1}'.$subdir.':${2}',
                                          $page_to_modify);
                }
                else {
                    $newId = $subdir.':'.$page_to_modify;
                }

                if(page_exists($newId)) {
                    $err = sprintf($this->getLang('file_exists'), $newId);
                }
                //verify file write rights
                else if(auth_quickaclcheck($newId) < AUTH_EDIT) {
                    $err = sprintf($this->getLang('permision_denied_write'), $page_to_modify);
                }
                //save to the new location and delete the old file
                else {
                    saveWikiText($newId, $file_updated, $this->getLang('archived'));
                    if(page_exists($newId)) {
                        saveWikiText($page_to_modify, null, $this->getLang('archived'));
                    }
                }
            }
            //only write the file to the current location
            else {
                saveWikiText($page_to_modify, $file_updated, $this->getLang('archived'));
            }
        }

        if($err === '') {
            $response = array('response' => 'OK');
        }
        else {
            $response = array('response' => 'error', 'error' => $err);
        }

        //unlock for editing
        if($locked === true) {
            unlock($page_to_modify);
        }

        //send response
        header('Content-Type: application/json');
        echo json_encode($response);
    }
}
