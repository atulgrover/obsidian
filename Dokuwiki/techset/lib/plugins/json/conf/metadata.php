<?php
/**
 * Options for the json plugin
 *
 * @author Janez Paternoster <janez.paternoster@siol.net>
 */

$meta['ignore_if_no_plugin'] = array('onoff');
$meta['null_str'] = array('string');
$meta['array_str'] = array('string');
$meta['true_str'] = array('string');
$meta['false_str'] = array('string');
$meta['src_recursive'] = array('numeric', '_min' => 0, '_max'=> 99);
$meta['json_display'] = array('string');
$meta['enable_ejs'] = array('onoff', '_caution' => 'security');
