<?php
/**
 * Slovenian language file for json plugin
 *
 * @author Janez Paternoster <janez.paternoster@siol.net>
 */

// keys need to match the config setting name

$lang['ignore_if_no_plugin'] = 'Če je ime elementa drugo kot &lt;json&gt; in ustrezen vtičnik ni najden, ignoriraj element.';
$lang['null_str'] = 'Niz ki se izpiše v celici, če podatek ni definiran.';
$lang['array_str'] = 'Niz ki se izpiše v celici, če je podatek seznam, ki nima izpisljivih vrednosti.';
$lang['true_str'] = 'Niz ki se izpiše v celici pri boolean spremenljivki z vrednostjo true.';
$lang['false_str'] = 'Niz ki se izpiše v celici pri boolean spremenljivki z vrednostjo false.';
$lang['src_recursive'] = 'Največja globina rekurzivnih klicev pri nalaganju JSON podatkov iz &lt;json src=...&gt; elementov. (0 ... 99)';
$lang['json_display'] = 'Privzet tip prikaza za &ltjson&gt element. Lahko je prazen ali "all" ali z vejico ločen seznam iz: '
                        .'original, inline, combined, log, error. Zvezdica (*) za besedo bo aktivirala pripadajoče polje.';
$lang['enable_ejs'] = 'Omogoči EJS template engine. Glej https://ejs.co/ in https://github.com/json-editor/json-editor#templates';
