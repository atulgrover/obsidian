<?php
/**
 * Slovenian language file for json plugin
 *
 * @author Janez Paternoster <janez.paternoster@siol.net>
 */

// json tabs
$lang['save'] = 'Shrani';

$lang['json_original'] = 'JSON originalni';
$lang['json_inline'] = 'JSON znotraj';
$lang['json_combined'] = 'JSON kombiniran';
$lang['log'] = 'Dnevnik';
$lang['error'] = 'Napake';

// Ajax save inline or archive or remote
$lang['permision_denied_read'] = 'Ni dovoljenj za branje iz %s.';
$lang['permision_denied_write'] = 'Ni dovoljenj za pisanje v %s.';
$lang['wrong_pageId'] = 'Argument %s ni pravilen ID za wiki stran.';
$lang['missing_id'] = 'Manjkajoč id v json elementu ali druga napaka v jsonu v datoteki %s.';
$lang['json_error'] = 'Argument \'data\' ni niti pravilen Json niti prazen niz.';
$lang['file_locked'] = 'Datoteka %s je trenutno zaklenjena za pisanje.';
$lang['file_not_found'] = 'Datoteka ni najdena: %s.';
$lang['file_exists'] = 'Datoteka že obstaja: %s.';
$lang['element_not_found'] = 'Json element id=\'%s\' ni najden.';
$lang['duplicated_id'] = 'Atribut id=\'%s\' na json elementih ni unikaten.';
$lang['not_empty'] = 'Pisanje znotraj json id=\'%s\' elementa ni dovoljeno ker že vsebuje podatke.';
$lang['not_array'] = 'Json element id=\'%s\' ni tipa seznam.';
$lang['not_array_file'] = 'Datoteka %s ni tipa Json seznam.';
$lang['hash_not_equal'] = 'Pisanje v json id=\'%s\' element ni dovoljeno. Nekdo drug je spremenil podatke odkar je bila stran nazadnje osvežena.';
$lang['json_updated_ajax'] = 'Json id=\'%s\' spremenjen - ajax klic.';
$lang['json_updated_remote'] = 'Json id=\'%s\' spremenjen - oddaljen dostop.';
$lang['internal_error'] = 'Notranja napaka v modulu %s.';

// Ajax archive
$lang['archived'] = 'JSON baza podatkov je arhivirana znotraj strani.';
$lang['file_changed'] = 'Datoteka %s je bila spremenjena odkar je bila nazadnje naložena. Najprej ponovno naložite stran.';

// JavaScript
$lang['js']['archive_button'] = 'Arhiviraj JSON bazo podatkov';
$lang['js']['archive_move'] = 'Premakni wiki stran na podmapo (pusti prazno za ne):';
