<?php
/**
 * English language file for json plugin
 *
 * @author Janez Paternoster <janez.paternoster@siol.net>
 */

// keys need to match the config setting name

$lang['ignore_if_no_plugin'] = 'If tag name is other than &lt;json&gt; and corresponding plugin is not found, ignore the element.';
$lang['null_str'] = 'String to show in table cell, if data is not defined.';
$lang['array_str'] = 'String to show in table cell, if data array with no printable members.';
$lang['true_str'] = 'String to show in table cell on boolean variable set to true.';
$lang['false_str'] = 'String to show in table cell on boolean variable set to false.';
$lang['src_recursive'] = 'Maximum depth for recursive loading JSON data from &lt;json src=...&gt; elements. (0 ... 99)';
$lang['json_display'] = 'Default type of display for &ltjson&gt element. May be empty or "all" or comma separated list from: '
                        .'original, inline, combined, log, error. Asterrisk (*) after token will activate corresponding field.';
$lang['enable_ejs'] = 'Enable EJS template engine. See https://ejs.co/ and https://github.com/json-editor/json-editor#templates';
