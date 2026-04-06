<?php
/**
 * English language file for json plugin
 *
 * @author Janez Paternoster <janez.paternoster@siol.net>
 */

// json tabs
$lang['save'] = 'Save';

$lang['json_original'] = 'JSON original';
$lang['json_inline'] = 'JSON inline';
$lang['json_combined'] = 'JSON combined';
$lang['log'] = 'Log';
$lang['error'] = 'Errors';

// Ajax save inline or archive or remote
$lang['permision_denied_read'] = 'Permission Denied for read from %s.';
$lang['permision_denied_write'] = 'Permission Denied for write into %s.';
$lang['wrong_pageId'] = 'Argument %s is not ID of a wiki page.';
$lang['missing_id'] = 'Json missing id or other error in file %s.';
$lang['json_error'] = 'Argument \'data\' is not valid Json nor empty string.';
$lang['file_locked'] = 'File %s is currently locked for editing.';
$lang['file_not_found'] = 'File not found: %s.';
$lang['file_exists'] = 'File already exists: %s.';
$lang['element_not_found'] = 'Json element id=\'%s\' not found.';
$lang['duplicated_id'] = 'Non unique id=\'%s\' attribute on json elements.';
$lang['not_empty'] = 'Writing inside json id=\'%s\' element is not allowed as it already contains data.';
$lang['not_array'] = 'Json element id=\'%s\' is not an array.';
$lang['not_array_file'] = 'File %s is not a Json array.';
$lang['hash_not_equal'] = 'Writing into json id=\'%s\' element is not allowed. Someone else changed the data since last page reload.';
$lang['json_updated_ajax'] = 'Json id=\'%s\' changed by ajax call.';
$lang['json_updated_remote'] = 'Json id=\'%s\' changed by remote command.';
$lang['internal_error'] = 'Internal error in module %s.';

// Ajax archive
$lang['archived'] = 'JSON database is archived into page.';
$lang['file_changed'] = 'File %s has changed since last page load. Please reload the file first.';

// JavaScript
$lang['js']['archive_button'] = 'Archive JSON database';
$lang['js']['archive_move'] = 'Move wiki page to sub-directory (leave empty for no):';
