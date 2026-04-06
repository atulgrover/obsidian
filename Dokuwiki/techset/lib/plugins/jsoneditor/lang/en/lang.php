<?php
/**
 * English language file for jsoneditor plugin
 *
 * @author Janez Paternoster <janez.paternoster@siol.net>
 */

// json tabs
$lang['json_editor'] = 'JSON Editor';
$lang['json_schema'] = 'JSON Schema';

// javascript
$lang['js']['button_validate'] = 'Validate';


/*
 * Translation for jsoneditor.js library (JavaScript).
 * see https://github.com/json-editor/json-editor/blob/master/src/defaults.js
 *
 * Note that english language is already included in jsoneditor.js, so
 * definitions below are ignored.
 */
$lang['js']['language'] = 'en';
  /*
   * When a property is not set
   */
$lang['js']['error_notset'] = 'Property must be set';
  /*
  * When a string must not be empty
  */
$lang['js']['error_notempty'] = 'Value required';
  /*
  * When a value is not one of the enumerated values
  */
$lang['js']['error_enum'] = 'Value must be one of the enumerated values';
  /*
  * When a value is not equal to the constant
  */
$lang['js']['error_const'] = 'Value must be the constant value';
  /*
  * When a value doesn't validate any schema of a 'anyOf' combination
  */
$lang['js']['error_anyOf'] = 'Value must validate against at least one of the provided schemas';
  /*
  * When a value doesn't validate
  * @variables This key takes one variable: The number of schemas the value does not validate
  */
$lang['js']['error_oneOf'] = 'Value must validate against exactly one of the provided schemas. It currently validates against {{0}} of the schemas.';
  /*
  * When a value does not validate a 'not' schema
  */
$lang['js']['error_not'] = 'Value must not validate against the provided schema';
  /*
  * When a value does not match any of the provided types
  */
$lang['js']['error_type_union'] = 'Value must be one of the provided types';
  /*
  * When a value does not match the given type
  * @variables This key takes one variable: The type the value should be of
  */
$lang['js']['error_type'] = 'Value must be of type {{0}}';
  /*
  *  When the value validates one of the disallowed types
  */
$lang['js']['error_disallow_union'] = 'Value must not be one of the provided disallowed types';
  /*
  *  When the value validates a disallowed type
  * @variables This key takes one variable: The type the value should not be of
  */
$lang['js']['error_disallow'] = 'Value must not be of type {{0}}';
  /*
  * When a value is not a multiple of or divisible by a given number
  * @variables This key takes one variable: The number mentioned above
  */
$lang['js']['error_multipleOf'] = 'Value must be a multiple of {{0}}';
  /*
  * When a value is greater than it's supposed to be (exclusive)
  * @variables This key takes one variable: The maximum
  */
$lang['js']['error_maximum_excl'] = 'Value must be less than {{0}}';
  /*
  * When a value is greater than it's supposed to be (inclusive
  * @variables This key takes one variable: The maximum
  */
$lang['js']['error_maximum_incl'] = 'Value must be at most {{0}}';
  /*
  * When a value is lesser than it's supposed to be (exclusive)
  * @variables This key takes one variable: The minimum
  */
$lang['js']['error_minimum_excl'] = 'Value must be greater than {{0}}';
  /*
  * When a value is lesser than it's supposed to be (inclusive)
  * @variables This key takes one variable: The minimum
  */
$lang['js']['error_minimum_incl'] = 'Value must be at least {{0}}';
  /*
  * When a value have too many characters
  * @variables This key takes one variable: The maximum character count
  */
$lang['js']['error_maxLength'] = 'Value must be at most {{0}} characters long';
  /*
  * When a value does not have enough characters
  * @variables This key takes one variable: The minimum character count
  */
$lang['js']['error_minLength'] = 'Value must be at least {{0}} characters long';
  /*
  * When a value does not match a given pattern
  */
$lang['js']['error_pattern'] = 'Value must match the pattern {{0}}';
  /*
  * When an array has additional items whereas it is not supposed to
  */
$lang['js']['error_additionalItems'] = 'No additional items allowed in this array';
  /*
  * When there are to many items in an array
  * @variables This key takes one variable: The maximum item count
  */
$lang['js']['error_maxItems'] = 'Value must have at most {{0}} items';
  /*
  * When there are not enough items in an array
  * @variables This key takes one variable: The minimum item count
  */
$lang['js']['error_minItems'] = 'Value must have at least {{0}} items';
  /*
  * When an array is supposed to have unique items but has duplicates
  */
$lang['js']['error_uniqueItems'] = 'Array must have unique items';
  /*
  * When there are too many properties in an object
  * @variables This key takes one variable: The maximum property count
  */
$lang['js']['error_maxProperties'] = 'Object must have at most {{0}} properties';
  /*
  * When there are not enough properties in an object
  * @variables This key takes one variable: The minimum property count
  */
$lang['js']['error_minProperties'] = 'Object must have at least {{0}} properties';
  /*
  * When a required property is not defined
  * @variables This key takes one variable: The name of the missing property
  */
$lang['js']['error_required'] = 'Object is missing the required property \'{{0}}\'';
  /*
  * When there is an additional property is set whereas there should be none
  * @variables This key takes one variable: The name of the additional property
  */
$lang['js']['error_additional_properties'] = 'No additional properties allowed, but property {{0}} is set';
  /*
  * When there is a propertyName that sets a max length and a property name exceeds the max length
  * @variables This key takes one variable: The name of the invalid property
  */
$lang['js']['error_property_names_exceeds_maxlength'] = 'Property name {{0}} exceeds maxLength';
  /*
  * When there is a propertyName that sets an enum and a property name matches none of the possible enum
  * @variables This key takes one variable: The name of the invalid property
  */
$lang['js']['error_property_names_enum_mismatch'] = 'Property name {{0}} does not match any enum values';
  /*
  * When there is a propertyName that sets a const and a property does not match the const value
  * @variables This key takes one variable: The name of the invalid property
  */
$lang['js']['error_property_names_const_mismatch'] = 'Property name {{0}} does not match the const value';
  /*
  * When there is a propertyName that sets a pattern and a property name does not match the pattern
  * @variables This key takes one variable: The name of the invalid property
  */
$lang['js']['error_property_names_pattern_mismatch'] = 'Property name {{0}} does not match pattern';
  /*
  * When the propertyName is set to false and there is at least one property
  * @variables This key takes one variable: The name of the invalid property
  */
$lang['js']['error_property_names_false'] = 'Property name {{0}} fails when propertyName is false';
  /*
  * When the propertyName specifies a maxLength that is not a number
  * @variables This key takes one variable: The name of the current property
  */
$lang['js']['error_property_names_maxlength'] = 'Property name {{0}} cannot match invalid maxLength';
  /*
  * When the propertyName specifies an enum that is not an array
  * @variables This key takes one variable: The name of the current property
  */
$lang['js']['error_property_names_enum'] = 'Property name {{0}} cannot match invalid enum';
  /*
  * When the propertyName specifies a pattern that is not a string
  * @variables This key takes one variable: The name of the current property
  */
$lang['js']['error_property_names_pattern'] = 'Property name {{0}} cannot match invalid pattern';
  /*
  * When the propertyName is unsupported
  * @variables This key takes one variable: The name of the invalid propertyName
  */
$lang['js']['error_property_names_unsupported'] = 'Unsupported propertyName {{0}}';
  /*
  * When a dependency is not resolved
  * @variables This key takes one variable: The name of the missing property for the dependency
  */
$lang['js']['error_dependency'] = 'Must have property {{0}}';
  /*
  * When a date is in incorrect format
  * @variables This key takes one variable: The valid format
  */
$lang['js']['error_date'] = 'Date must be in the format {{0}}';
  /*
  * When a time is in incorrect format
  * @variables This key takes one variable: The valid format
  */
$lang['js']['error_time'] = 'Time must be in the format {{0}}';
  /*
  * When a datetime-local is in incorrect format
  * @variables This key takes one variable: The valid format
  */
$lang['js']['error_datetime_local'] = 'Datetime must be in the format {{0}}';
  /*
  * When a integer date is less than 1 January 1970
  */
$lang['js']['error_invalid_epoch'] = 'Date must be greater than 1 January 1970';
  /*
  * When an IPv4 is in incorrect format
  */
$lang['js']['error_ipv4'] = 'Value must be a valid IPv4 address in the form of 4 numbers between 0 and 255, separated by dots';
  /*
  * When an IPv6 is in incorrect format
  */
$lang['js']['error_ipv6'] = 'Value must be a valid IPv6 address';
  /*
  * When a hostname is in incorrect format
  */
$lang['js']['error_hostname'] = 'The hostname has the wrong format';
  /*
  * Text/Title on Save button
  */
$lang['js']['button_save'] = 'Save';
  /*
  * Text/Title on Copy button
  */
$lang['js']['button_copy'] = 'Copy';
  /*
  * Text/Title on Cancel button
  */
$lang['js']['button_cancel'] = 'Cancel';
  /*
  * Text/Title on Add button
  */
$lang['js']['button_add'] = 'Add';
  /*
  * Text on Delete All buttons
  */
$lang['js']['button_delete_all'] = 'All';
  /*
  * Title on Delete All buttons
  */
$lang['js']['button_delete_all_title'] = 'Delete All';
  /*
  * Text on Delete Last buttons
  * @variable This key takes one variable: The title of object to delete
  */
$lang['js']['button_delete_last'] = 'Last {{0}}';
  /*
  * Title on Delete Last buttons
  * @variable This key takes one variable: The title of object to delete
  */
$lang['js']['button_delete_last_title'] = 'Delete Last {{0}}';
  /*
  * Title on Add Row buttons
  * @variable This key takes one variable: The title of object to add
  */
$lang['js']['button_add_row_title'] = 'Add {{0}}';
  /*
  * Title on Move Down buttons
  */
$lang['js']['button_move_down_title'] = 'Move down';
  /*
  * Title on Move Up buttons
  */
$lang['js']['button_move_up_title'] = 'Move up';
  /*
  * Text on Object Properties buttons
  */
$lang['js']['button_properties'] = 'Properties';
  /*
  * Title on Object Properties buttons
  */
$lang['js']['button_object_properties'] = 'Object Properties';
  /*
  * Title on Copy Row button
  * @variable This key takes one variable: The title of object to delete
  */
$lang['js']['button_copy_row_title'] = 'Copy {{0}}';
  /*
  * Title on Delete Row buttons
  * @variable This key takes one variable: The title of object to delete
  */
$lang['js']['button_delete_row_title'] = 'Delete {{0}}';
  /*
  * Title on Delete Row buttons, short version (no parameter with the object title)
  */
$lang['js']['button_delete_row_title_short'] = 'Delete';
  /*
  * Title on Copy Row buttons, short version (no parameter with the object title)
  */
$lang['js']['button_copy_row_title_short'] = 'Copy';
  /*
  * Title on Collapse buttons
  */
$lang['js']['button_collapse'] = 'Collapse';
  /*
  * Title on Expand buttons
  */
$lang['js']['button_expand'] = 'Expand';
  /*
  * Title on Edit JSON buttons
  */
$lang['js']['button_edit_json'] = 'Edit JSON';
  /*
  * Text/Title on Upload buttons
  */
$lang['js']['button_upload'] = 'Upload';
  /*
  * Title on Flatpickr toggle buttons
  */
$lang['js']['flatpickr_toggle_button'] = 'Toggle';
  /*
  * Title on Flatpickr clear buttons
  */
$lang['js']['flatpickr_clear_button'] = 'Clear';
  /*
  * Choices input field placeholder text
  */
$lang['js']['choices_placeholder_text'] = 'Start typing to add value';
  /*
  * Default title for array items
  */
$lang['js']['default_array_item_title'] = 'item';
  /*
  * Warning when deleting a node
  */
$lang['js']['button_delete_node_warning'] = 'Are you sure you want to remove this node?';
