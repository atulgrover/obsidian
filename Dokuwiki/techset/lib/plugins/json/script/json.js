jQuery(function() {
    //another json plugin may have allready initialized this
    if(!json_plugin.initialized) {
        json_plugin.init();
    }
});

//global variable accessible by other json-type plugins
var json_plugin = {
    initialized: false,

    init: function() {
        //if user wants to leave the page and if this variable is not empty,
        //then alert will ask user, if he wants to leave the page or stay on it.
        var leavePageList = {};

        json_plugin.initialized = true;

        //initialize <jsonxxx> elements
        jQuery('.json-tabs').each(function() {

            var $tabs = jQuery(this),
                id = $tabs.data('json-id'),
                hash = $tabs.data('json-hash'),
                active = $tabs.data('active'),
                $button = $tabs.find('.json-save-button'),
                $data_original = $tabs.find('.json-data-original'),
                $textarea = $tabs.find('.json-data-inline'),
                $data_combined = $tabs.find('.json-data-combined'),
                $highlight = $tabs.find('.lang-json');


            //save object with interface to this tabs, so other json plugins can use it
            var o = {
                //json data, before inline data was combined, readonly
                get data_original() {
                    return ($data_original.length === 1) ? $data_original.text() : undefined;
                },

                //inline json data from textarea, writeable
                get data_inline() {
                    return ($textarea.length === 1) ? $textarea.val() : undefined;
                },
                set data_inline(text) {
                    if ($textarea.length === 1) {
                        $textarea.val(text);
                    }
                },

                //complete json data, data_original combined with data_inline
                get data_combined() {
                    return ($data_combined.length === 1) ? $data_combined.text() : undefined;
                },

                //jQuery button element. It triggers 'jsonBeforeSave' and 'jsonAfterSave' events.
                $button: $button,

                //function must be called by other json plugins on change of data
                showButton: function() {
                    if(jQuery.isEmptyObject(leavePageList)) {
                        window.onbeforeunload = function(e) {
                            e.preventDefault();
                            e.returnValue = '';
                        };
                    }
                    leavePageList[id] = true;
                    $button.show('slow');
                }
            };
            $tabs.data('o', o);


            //generate jQuery UI tabs
            $tabs.tabs({
                collapsible: true,
                active: (active === "false") ? false : parseInt(active)
            });


            //button will save data to dokuwiki via ajax call
            $button.on('click', function (event) {
                //other json plugins may prepare data here
                $button.trigger('jsonBeforeSave');

                var text = o.data_inline;

                //validate JSON
                if(text.trim().length > 0) {
                    try {
                        JSON.parse(text.replace(/%\$.*?%/g, 'null'));
                    }
                    catch(e) {
                        alert(e);
                        return;
                    }
                }

                //save data
                jQuery.post(
                    DOKU_BASE + 'lib/exe/ajax.php',
                    {
                        call: 'json_plugin_save_inline',//server function
                        file: JSINFO.id,    //dokuwiki file id
                        id: id,             //id of the <json id=___> element
                        hash: hash,         //MD5 hash of the old_text from <json ...>old_text</json> element
                        text: text          //new text to write into <json ...>text</json> element
                    },
                    function(data) {
                        if(data.response === 'OK') {
                            hash = data.hash;

                            //save successful, prepare event handlers, hide button
                            $textarea.one('keydown change', o.showButton);
                            $button.trigger('jsonAfterSave');
                            $button.hide('slow');

                            delete(leavePageList[id]);
                            if(jQuery.isEmptyObject(leavePageList)) {
                                window.onbeforeunload = null;
                            }
                        }
                        else if(data.response === 'error') {
                            alert(data.error);
                        }
                        else {
                            alert('Internal communication error.');
                        }
                    },
                    'json'
                );
            });


            //show 'save' button once after first key is pressed
            $textarea.one('keydown change', o.showButton);


            //highlight json code
            $highlight.each(function() {
                hljs.highlightBlock(this);
            });
        });

        // Make button, which will trigger ajax call for archiving data
        // When JSON data are archived, then all json-data-original
        // will be stored into <json> element itself. 'src' and 'src_ext'
        // attibutes from the element will then be ignored.
        var archives = jQuery('.json-tabs.json-make-archive');
        if(archives.length > 0) {
            var $archive_button = jQuery('<button class="json-archive-button">'+LANG.plugins.json.archive_button+'</button>');

            jQuery('#dokuwiki__header').append($archive_button);

            $archive_button.on('click', function (event) {
                var json_data_original = [],
                    subdir = prompt(LANG.plugins.json.archive_move);

                if (typeof subdir != 'string') {
                    return;
                }

                archives.each(function() {
                    json_data_original.push(jQuery(this).find('.json-data-original').text());
                });

                //save data
                jQuery.post(
                    DOKU_BASE + 'lib/exe/ajax.php',
                    {
                        call: 'json_plugin_archive',//server function
                        file: JSINFO.id,            //dokuwiki file id
                        lastmod: JSINFO.json_lastmod,//dokuwiki timestamp of the last modification to the current page
                        data: json_data_original,   //array of data
                        subdir: subdir              //move to subdirectory
                    },
                    function(data) {
                        if(data.response === 'OK') {
                            //save successful, hide button
                            $archive_button.hide('slow');
                        }
                        else if(data.response === 'error') {
                            alert(data.error);
                        }
                        else {
                            alert('Internal communication error.');
                        }
                    },
                    'json'
                );
            });
        }


        //initialize some extractors
        //highlight json code
        jQuery('.json-extract-code').each(function() {
            hljs.highlightBlock(this);
        });

        //ejs template
        if(JSINFO.enable_ejs) {
            jQuery('.json-extract-ejs').each(function() {
                var $span = jQuery(this),
                    data = JSON.parse($span.find('#data').text()),
                    template = $span.find('#template').text(),
                    result = '';
                try {
                    result = ejs.render(template, {d : data});
                }
                catch (e) {
                    console.log(e);
                }
                $span.text(result);
            });
        }
    },


    //helper function: get diff of two objects (data_original, data_combined)
    //https://stackoverflow.com/questions/8431651/getting-a-diff-of-two-json-objects
    diff: function (obj1, obj2) {
        if(!obj1 || typeof obj1 !== 'object' || !obj2 || typeof obj2 !== 'object') {
            return obj2;
        }
        const result = {};
        Object.keys(obj2).forEach(key => {
            if(typeof obj2[key] === 'object' && typeof obj1[key] === 'object') {
                const value = this.diff(obj1[key], obj2[key]);
                if (Object.keys(value).length !== 0) {
                    result[key] = value;
                }
            }
            else if(obj2[key] !== obj1[key] && !Object.is(obj1[key], obj2[key])) {
                result[key] = obj2[key];
            }
        });
        return result;
    }
};
