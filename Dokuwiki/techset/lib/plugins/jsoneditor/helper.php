<?php
/**
 * DokuWiki Plugin jsoneditor (Helper Component)
 *
 * @license GPL 2 http://www.gnu.org/licenses/gpl-2.0.html
 * @author  Janez Paternoster <janez.paternoster@siol.net>
 */

// must be run within Dokuwiki
if (!defined('DOKU_INC')) {
    die();
}

class helper_plugin_jsoneditor extends helper_plugin_json {

    /**
     * Handle extension to syntax_plugin_json_define
     *
     * @param array $data Reference to $data, which can be further manipulated
     */
    public function handle(&$data) {
        $json_o = $this->loadHelper('json');

        //options for the jsoneditor
        $data['options_default'] = $this->getConf('options');
        if(isset($data['keys']['options'])) {
            $data['options'] = $data['keys']['options'];
            //replace %$ ... % snippets with data - prepare
            $data['options_extractors'] = $json_o->extractors_handle($data['keys']['options']);
        }

        //schema for the jsoneditor
        $schema = $data['keys']['schema'] ?? '{}';

        $data['schema'] = $schema;
        //replace %$ ... % snippets with data - prepare
        $data['schema_extractors'] = $json_o->extractors_handle($schema);

        //If 'save' attribute is set to 'all', then complete json object
        //from jsoneditor will be saved into <json> element.
        //Othervise only difference between original data and inline
        //data will be saved (default).
        $save = isset($data['keys']['save']) ? $data['keys']['save'] : '';
        if($save !== '' && strtolower($save) === 'all') {
            $data['saveall'] = 'true';
        }
        else {
            $data['saveall'] = 'false';
            $data['display'] .= ',orig-hidden';
        }

        //make sure, necessary json data will be there
        $data['display'] .= ',inl-hidden,comb-hidden';
    }


    /**
     * Render extension to syntax_plugin_json_define
     *
     * For parameters see render::syntax_plugin_json_define
     *
     * @param array $data from handler
     * @param array $class definitions for parent div
     * @param array $data_attr html data attributes
     * @param array $tabs definitions for jQuery UI tabs widget
     * @param array $body definitions for jQuery UI tabs widget
     * @param array $log for reporting errors
     * @param array $tab_no must incerment for each tab
     * @param array $tab_number for id attribute
     */
    public function render(Doku_Renderer $renderer, &$data, &$class, &$data_attr, &$tabs, &$body, &$log, &$tab_no, $tab_number) {
        //prepare options from default and optional inline options
        $options = $data['options_default'];
        if(isset($data['options'])) {
            $options_inline = $data['options'];
            //replace %$ ... % snippets with data
            if(count($data['options_extractors']) > 0) {
                $json_o = $this->loadHelper('json');
                $options_inline = $json_o->extractors_replace($options_inline, $data['options_extractors']);
            }
            if($options === '{}') {
                $options = $options_inline;
            }
            else {
                //combine default and inline options
                $json_options_default = json_decode($options, true);
                if(!isset($json_options_default)) {
                    $json_options_default = json_decode('{}', true);
                    $log['error'] = 'internal JSON, default options '.json_last_error_msg();
                }
                $json_options_inline = json_decode($options_inline, true);
                if(!isset($json_options_inline)) {
                    $json_options_inline = json_decode('{}', true);
                    $log['error'] = 'internal JSON, inline options '.json_last_error_msg();
                }
                $json_options = array_replace_recursive($json_options_default, $json_options_inline);
                $options = json_encode($json_options);
            }
        }

        if(count($data['schema_extractors']) > 0) {
            $json_o = $this->loadHelper('json');
            $schema = $json_o->extractors_replace($data['schema'], $data['schema_extractors']);
        }
        else {
            $schema = $data['schema'];
        }

        $data_attr['options'] = htmlspecialchars($options);
        $data_attr['schema'] = htmlspecialchars($schema);
        $data_attr['saveall'] = $data['saveall'];

        $class[] = 'jsoneditor-plugin';

        //always display jsoneditor tab, fully shown by default
        if(strpos($data['display'], 'jsoneditor') === false) {
            $data['display'] .= ',jsoneditor*';
        }

        //tab for editor
        if(strpos($data['display'], 'jsoneditor*') !== false) { $data_attr['active'] = $tab_no; }
        $tab_no++;
        $tabs[] = '<li><a href="#json-tab-'.$tab_number.'-editor">'.$this->getLang('json_editor').'</a></li>';
        $body[] =      '<div id="json-tab-'.$tab_number.'-editor"><div class="json-editor-error"></div><div class="json-editor"></div></div>';

        //tab for schema
        if(strpos($data['display'], 'all') !== false || strpos($data['display'], 'schema') !== false) {
            $tab_no++;
            $tabs[] = '<li><a href="#json-tab-'.$tab_number.'-schema">'.$this->getLang('json_schema').'</a></li>';
            $body[] =      '<div id="json-tab-'.$tab_number.'-schema"><pre class="lang-json">'.
            htmlspecialchars(json_encode(json_decode($schema, true), JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE)).'</pre></div>';
        }
    }
}
