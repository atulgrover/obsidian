<?php
/**
 * Slovenian language file for jsoneditor plugin
 *
 * @author Janez Paternoster <janez.paternoster@siol.net>
 */

// json tabs
$lang['json_editor'] = 'JSON urejevalnik';
$lang['json_schema'] = 'JSON shema';

// javascript
$lang['js']['button_validate'] = 'Preveri';

// Prevod za jsoneditor.js knjižnico (JavaScript).
$lang['js']['language'] = 'sl';
$lang['js']['error_notset'] = 'Lastnost mora biti nastavljena';
$lang['js']['error_notempty'] = 'Vrednost je obvezna';
$lang['js']['error_enum'] = 'Vrednost mora biti ena izmed seznama';
$lang['js']['error_const'] = 'Vrednost mora biti konstantna';
$lang['js']['error_anyOf'] = 'Vrednost mora ustrezati vsaj eni podani shemi';
$lang['js']['error_oneOf'] = 'Vrednost mora ustrezati natančno eni podani shemi. Trenutno ustreza {{0}} shemam.';
$lang['js']['error_not'] = 'Vrednost ne sme ustrezati podani shemi';
$lang['js']['error_type_union'] = 'Vrednost mora biti enega izmed predvidenih tipov';
$lang['js']['error_type'] = 'Vrednost mora biti tipa {{0}}';
$lang['js']['error_disallow_union'] = 'Vrednost ne sme biti enega izmed nedovoljenih tipov';
$lang['js']['error_disallow'] = 'Vrednost ne sme biti tipa {{0}}';
$lang['js']['error_multipleOf'] = 'Vrednost mora biti večkratnik od {{0}}';
$lang['js']['error_maximum_excl'] = 'Vrednost mora biti manj kot {{0}}';
$lang['js']['error_maximum_incl'] = 'Vrednost mora biti največ {{0}}';
$lang['js']['error_minimum_excl'] = 'Vrednost mora biti več kot {{0}}';
$lang['js']['error_minimum_incl'] = 'Vrednost mora biti vsaj {{0}}';
$lang['js']['error_maxLength'] = 'Vrednost mora biti dolga največ {{0}} znakov';
$lang['js']['error_minLength'] = 'Vrednost mora biti dolga vsaj {{0}} znakov';
$lang['js']['error_pattern'] = 'Vrednost se mora ujemati z vzorcem {{0}}';
$lang['js']['error_additionalItems'] = 'V tem seznamu ni dovoljenih dodatnih postavk';
$lang['js']['error_maxItems'] = 'Vrednost mora imeti največ {{0}} postavk';
$lang['js']['error_minItems'] = 'Vrednost mora imeti vsaj {{0}} postavk';
$lang['js']['error_uniqueItems'] = 'Seznam mora imeti unikatne postavke';
$lang['js']['error_maxProperties'] = 'Predmet mora imeti največ {{0}} lastnosti';
$lang['js']['error_minProperties'] = 'Predmet mora imeti vsaj {{0}} lastnosti';
$lang['js']['error_required'] = 'Pri predmetu manjka zahtevana lastnost \'{{0}}\'';
$lang['js']['error_additional_properties'] = 'Dodatne lastnosti niso dovoljene, toda lastnost {{0}} prisotna';
$lang['js']['error_property_names_exceeds_maxlength'] = 'Lastnost z imenom {{0}} presega največjo dolžino';
$lang['js']['error_property_names_enum_mismatch'] = 'Lastnost z imenom {{0}} se ne ujema z nobeno izmed izbir';
$lang['js']['error_property_names_const_mismatch'] = 'Lastnost z imenom {{0}} se ne ujema s konstantno vrednostjo';
$lang['js']['error_property_names_pattern_mismatch'] = 'Lastnost z imenom {{0}} se ne ujema z vzorcem';
$lang['js']['error_property_names_false'] = 'Lastnost z imenom {{0}} je napačna, when propertyName is false';
$lang['js']['error_property_names_maxlength'] = 'Lastnost z imenom {{0}} se ne more ujemati z napačno maksimalno dolžino';
$lang['js']['error_property_names_enum'] = 'Lastnost z imenom  {{0}} se ne more ujemati z napačnimi izbirami';
$lang['js']['error_property_names_pattern'] = 'Lastnost z imenom {{0}} ne more ustrezati napačnemu vzorcu';
$lang['js']['error_property_names_unsupported'] = 'Nepodprto ime lastnosti {{0}}';
$lang['js']['error_dependency'] = 'Mora imeti lastnost {{0}}';
$lang['js']['error_date'] = 'Datum mra biti v formatu {{0}}';
$lang['js']['error_time'] = 'Čas mora biti v formatu {{0}}';
$lang['js']['error_datetime_local'] = 'Datum-čas mora biti v formatu {{0}}';
$lang['js']['error_invalid_epoch'] = 'Datum mora biti več kot 1 Januar 1970';
$lang['js']['error_ipv4'] = 'Vrednost mora biti pravilen IPv4 naslov v obliki štirih številk od 0 do 255, ločene z vejicami';
$lang['js']['error_ipv6'] = 'Vrednost mora biti pravilen IPv6 naslov';
$lang['js']['error_hostname'] = '\'hostname\' ima napačen format';
$lang['js']['button_save'] = 'Shrani';
$lang['js']['button_copy'] = 'Kopiraj';
$lang['js']['button_cancel'] = 'Prekliči';
$lang['js']['button_add'] = 'Dodaj';
$lang['js']['button_delete_all'] = 'Vse';
$lang['js']['button_delete_all_title'] = 'Izbriši vse';
$lang['js']['button_delete_last'] = 'Zadnji {{0}}';
$lang['js']['button_delete_last_title'] = 'Izbriši zadnji {{0}}';
$lang['js']['button_add_row_title'] = 'Dodaj {{0}}';
$lang['js']['button_move_down_title'] = 'Premakni dol';
$lang['js']['button_move_up_title'] = 'Premakni gor';
$lang['js']['button_properties'] = 'Lastnosti';
$lang['js']['button_object_properties'] = 'Lastnosti predmeta';
$lang['js']['button_copy_row_title'] = 'Kopiraj {{0}}';
$lang['js']['button_delete_row_title'] = 'Izbriši {{0}}';
$lang['js']['button_delete_row_title_short'] = 'Izbriši';
$lang['js']['button_copy_row_title_short'] = 'Kopiraj';
$lang['js']['button_collapse'] = 'Strni';
$lang['js']['button_expand'] = 'Razširi';
$lang['js']['button_edit_json'] = 'Uredi JSON';
$lang['js']['button_upload'] = 'Naloži';
$lang['js']['flatpickr_toggle_button'] = 'Preklopi';
$lang['js']['flatpickr_clear_button'] = 'Počisti';
$lang['js']['choices_placeholder_text'] = 'Začni tipkati za dodajanje vrednosti';
$lang['js']['default_array_item_title'] = 'postavka';
$lang['js']['button_delete_node_warning'] = 'Ali si prepričan, da želiš odstraniti ta predmet?';
