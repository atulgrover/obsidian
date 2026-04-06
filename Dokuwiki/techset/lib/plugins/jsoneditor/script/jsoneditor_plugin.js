jQuery(function() {
    //Verify, if json-plugin is installed. Initialize it, if necessary.
    if(typeof json_plugin !== 'object') {
        return;
    }
    if(!json_plugin.initialized) {
        json_plugin.init();
    }

    var JSONEditor_configured = false;

    jQuery('.jsoneditor-plugin').each(function() {

        var $tabs = jQuery(this),
            $editor_error = $tabs.find('.json-editor-error'),
            $editor = $tabs.find('.json-editor'),
            options = $tabs.data('options'),
            schema = $tabs.data('schema'),
            saveall = $tabs.data('saveall'),
            errors = [],
            dataChanged = false,
            o = $tabs.data('o'),    //object with interface, which was prepared by json_plugin
            json_editor,
            dataOriginal;

        //configure JSONEditor library globally on the first pass
        if (!JSONEditor_configured) {
            JSONEditor_configured = true;
            // add language to the jsoneditor.js library
            if (LANG.plugins.jsoneditor.language.length > 0 && LANG.plugins.jsoneditor.language !== 'en') {
                JSONEditor.defaults.language = LANG.plugins.jsoneditor.language;
                JSONEditor.defaults.languages[LANG.plugins.jsoneditor.language] = {
                    error_notset: LANG.plugins.jsoneditor.error_notset,
                    error_notempty: LANG.plugins.jsoneditor.error_notempty,
                    error_enum: LANG.plugins.jsoneditor.error_enum,
                    error_const: LANG.plugins.jsoneditor.error_const,
                    error_anyOf: LANG.plugins.jsoneditor.error_anyOf,
                    error_oneOf: LANG.plugins.jsoneditor.error_oneOf,
                    error_not: LANG.plugins.jsoneditor.error_not,
                    error_type_union: LANG.plugins.jsoneditor.error_type_union,
                    error_type: LANG.plugins.jsoneditor.error_type,
                    error_disallow_union: LANG.plugins.jsoneditor.error_disallow_union,
                    error_disallow: LANG.plugins.jsoneditor.error_disallow,
                    error_multipleOf: LANG.plugins.jsoneditor.error_multipleOf,
                    error_maximum_excl: LANG.plugins.jsoneditor.error_maximum_excl,
                    error_maximum_incl: LANG.plugins.jsoneditor.error_maximum_incl,
                    error_minimum_excl: LANG.plugins.jsoneditor.error_minimum_excl,
                    error_minimum_incl: LANG.plugins.jsoneditor.error_minimum_incl,
                    error_maxLength: LANG.plugins.jsoneditor.error_maxLength,
                    error_minLength: LANG.plugins.jsoneditor.error_minLength,
                    error_pattern: LANG.plugins.jsoneditor.error_pattern,
                    error_additionalItems: LANG.plugins.jsoneditor.error_additionalItems,
                    error_maxItems: LANG.plugins.jsoneditor.error_maxItems,
                    error_minItems: LANG.plugins.jsoneditor.error_minItems,
                    error_uniqueItems: LANG.plugins.jsoneditor.error_uniqueItems,
                    error_maxProperties: LANG.plugins.jsoneditor.error_maxProperties,
                    error_minProperties: LANG.plugins.jsoneditor.error_minProperties,
                    error_required: LANG.plugins.jsoneditor.error_required,
                    error_additional_properties: LANG.plugins.jsoneditor.error_additional_properties,
                    error_property_names_exceeds_maxlength: LANG.plugins.jsoneditor.error_property_names_exceeds_maxlength,
                    error_property_names_enum_mismatch: LANG.plugins.jsoneditor.error_property_names_enum_mismatch,
                    error_property_names_const_mismatch: LANG.plugins.jsoneditor.error_property_names_const_mismatch,
                    error_property_names_pattern_mismatch: LANG.plugins.jsoneditor.error_property_names_pattern_mismatch,
                    error_property_names_false: LANG.plugins.jsoneditor.error_property_names_false,
                    error_property_names_maxlength: LANG.plugins.jsoneditor.error_property_names_maxlength,
                    error_property_names_enum: LANG.plugins.jsoneditor.error_property_names_enum,
                    error_property_names_pattern: LANG.plugins.jsoneditor.error_property_names_pattern,
                    error_property_names_unsupported: LANG.plugins.jsoneditor.error_property_names_unsupported,
                    error_dependency: LANG.plugins.jsoneditor.error_dependency,
                    error_date: LANG.plugins.jsoneditor.error_date,
                    error_time: LANG.plugins.jsoneditor.error_time,
                    error_datetime_local: LANG.plugins.jsoneditor.error_datetime_local,
                    error_invalid_epoch: LANG.plugins.jsoneditor.error_invalid_epoch,
                    error_ipv4: LANG.plugins.jsoneditor.error_ipv4,
                    error_ipv6: LANG.plugins.jsoneditor.error_ipv6,
                    error_hostname: LANG.plugins.jsoneditor.error_hostname,
                    button_save: LANG.plugins.jsoneditor.button_save,
                    button_copy: LANG.plugins.jsoneditor.button_copy,
                    button_cancel: LANG.plugins.jsoneditor.button_cancel,
                    button_add: LANG.plugins.jsoneditor.button_add,
                    button_delete_all: LANG.plugins.jsoneditor.button_delete_all,
                    button_delete_all_title: LANG.plugins.jsoneditor.button_delete_all_title,
                    button_delete_last: LANG.plugins.jsoneditor.button_delete_last,
                    button_delete_last_title: LANG.plugins.jsoneditor.button_delete_last_title,
                    button_add_row_title: LANG.plugins.jsoneditor.button_add_row_title,
                    button_move_down_title: LANG.plugins.jsoneditor.button_move_down_title,
                    button_move_up_title: LANG.plugins.jsoneditor.button_move_up_title,
                    button_properties: LANG.plugins.jsoneditor.button_properties,
                    button_object_properties: LANG.plugins.jsoneditor.button_object_properties,
                    button_copy_row_title: LANG.plugins.jsoneditor.button_copy_row_title,
                    button_delete_row_title: LANG.plugins.jsoneditor.button_delete_row_title,
                    button_delete_row_title_short: LANG.plugins.jsoneditor.button_delete_row_title_short,
                    button_copy_row_title_short: LANG.plugins.jsoneditor.button_copy_row_title_short,
                    button_collapse: LANG.plugins.jsoneditor.button_collapse,
                    button_expand: LANG.plugins.jsoneditor.button_expand,
                    button_edit_json: LANG.plugins.jsoneditor.button_edit_json,
                    button_upload: LANG.plugins.jsoneditor.button_upload,
                    flatpickr_toggle_button: LANG.plugins.jsoneditor.flatpickr_toggle_button,
                    flatpickr_clear_button: LANG.plugins.jsoneditor.flatpickr_clear_button,
                    choices_placeholder_text: LANG.plugins.jsoneditor.choices_placeholder_text,
                    default_array_item_title: LANG.plugins.jsoneditor.default_array_item_title,
                    button_delete_node_warning: LANG.plugins.jsoneditor.button_delete_node_warning
                };
            }

            // set EJS template engine, if enabled by json plugin.
            if(JSINFO.enable_ejs) {
                //JSONEditor.defaults.options.template = 'ejs'; doesn't work, bug in JSONEditor? Workaround below:
                const myEJS = {
                    compile: function (template) {
                        // Compile returns a render function
                        return function(vars) {
                            return ejs.render(template, vars);
                        }
                    }
                };
                JSONEditor.defaults.options.template = myEJS;
            }
        }


        //prepare options, schema and data for jsoneditor
        if(typeof options !== 'object') {
            try {
                options = JSON.parse(options);
            }
            catch(e) {
                errors.push("'options' attribute: " + String(e));
                options = {};
            }
        }
        else if (options === null) {
            options = {};
        }
        if(typeof schema !== 'object') {
            try {
                schema = JSON.parse(schema);
            }
            catch(e) {
                errors.push("'schema' attribute: " + String(e));
                schema = {};
            }
        }
        else if (schema === null) {
            schema = {};
        }

        options.schema = schema;
        options.startval = JSON.parse(o.data_combined);


        //display errors
        if(errors.length) {
            $editor_error.append(errors.join('<br/>'));
        }


        //initialize jsoneditor
        json_editor = new JSONEditor($editor[0], options);

        //add validate button to the header of the json_editor
        var $button = jQuery('<button style="font-weight: bold;" class="json-editor-btn-collapse json-editor-btntype-toggle">'+LANG.plugins.jsoneditor.button_validate+'</button>');

        json_editor.on('ready', function (event) {
            var $header = $editor.find('> div > h3');
            $header.append($button);
        });

        $button.on('click', function (event) {
            var err_validator = json_editor.validate();
            if(err_validator.length) {
                if(errors.length) {
                    $editor_error.append('<br/>');
                }
                errors = [];
                for(var i = 0; i < err_validator.length; i++) {
                    var e = err_validator[i];
                    errors.push('Validation error in ' + e.path + ' - ' + e.property + ' - ' + e.message);
                }
                $editor_error.append(errors.join('<br/>'));
            }
            else {
                //get data from editor
                var value = json_editor.getValue(),
                    dataToSave;

                //write all or partial data into JSON data_inline (textarea)
                if(saveall) {
                    dataToSave = value;
                }
                else {
                    if(dataOriginal === undefined) {
                        dataOriginal = JSON.parse(o.data_original);
                    }
                    dataToSave = json_plugin.diff(dataOriginal, value);
                }

                //stringify JSON
                if(Array.isArray(dataToSave) && typeof dataToSave === "object") {
                    //if we have an array of objects on the first level, make output a little less compact
                    o.data_inline = "[\n"
                        + dataToSave.map(x => "  " + JSON.stringify(x)).join(",\n")
                        + "\n]";
                }
                else {
                    o.data_inline = JSON.stringify(dataToSave);
                }

                //show JSON save button
                o.showButton();
            }
        });

        //warn if browser window unloads and data has been changed
        var ignoreFirstSignal = true;
        json_editor.on('change', function() {
            if (ignoreFirstSignal) {
                ignoreFirstSignal = false;
            }
            else {
                window.onbeforeunload = function(e) {
                    e.preventDefault();
                    e.returnValue = '';
                };
            }
        });
    });

});
