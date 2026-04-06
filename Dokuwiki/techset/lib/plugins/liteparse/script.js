jQuery(function() {
    jQuery('#liteparse_btn').on('click', function() {
        var $btn = jQuery(this);
        var $status = jQuery('#liteparse_status');
        var url = $btn.data('url');
        var pageId = $btn.data('id');

        $status.text('Processing...');
        $btn.prop('disabled', true);

        jQuery.post(DOKU_BASE + 'lib/exe/ajax.php', {
            call: 'liteparse_import',
            url: url,
            id: pageId
        }, function(data) {
            $status.text(data);
            if (data.includes('Success')) {
                // Reload page to see the newly saved Markdown content
                location.reload();
            } else {
                $btn.prop('disabled', false);
            }
        });
    });
});