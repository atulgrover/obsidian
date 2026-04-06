jQuery(document).ready(function() {
    jQuery('.tagbutton').click(function() {
        var tag = jQuery(this).data('tag');
        var id = JSINFO.id; // Current page ID

        jQuery.ajax({
            url: DOKU_BASE + 'lib/exe/ajax.php',
            type: 'POST',
            data: {
                call: 'tagbutton_add',
                tag: tag,
                id: id
            },
            success: function(response) {
                var result = JSON.parse(response);
                if (result.status === 'success') {
                    // Refresh the page if the tag is successfully added
                    location.reload();
                }
            }
        });
    });
});
