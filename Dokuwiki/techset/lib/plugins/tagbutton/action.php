<?php

use dokuwiki\Extension\ActionPlugin;
use dokuwiki\Extension\EventHandler;
use dokuwiki\Extension\Event;

/**
 * DokuWiki Plugin tagbutton (Action Component)
 *
 * @license GPL 2 http://www.gnu.org/licenses/gpl-2.0.html
 * @author Louis Ouellet <louis_ouellet@hotmail.com>
 */
class action_plugin_tagbutton extends ActionPlugin
{
    /** @inheritDoc */
    public function register(EventHandler $controller)
    {
        $controller->register_hook('AJAX_CALL_UNKNOWN', 'BEFORE', $this, 'handle_ajax');
    }

    /**
     * Event handler for EXAMPLE_EVENT
     *
     * @see https://www.dokuwiki.org/devel:events:EXAMPLE_EVENT
     * @param Event $event Event object
     * @param mixed $param optional parameter passed when event was registered
     * @return void
     */
    public function handle_ajax(Event $event, $param)
    {
        if($event->data !== 'tagbutton_add') return;

        global $INPUT, $ID, $TEXT;
        $event->preventDefault();
        $event->stopPropagation();

        // Get the tag and page ID from the AJAX request
        $tag = $INPUT->str('tag');
        $id = $INPUT->str('id');

        if($tag && $id) {
            $pageContent = rawWiki($id);

            // Check if {{tag>}} already exists
            if (preg_match('/\{\{tag>(.*?)\}\}/', $pageContent, $matches)) {
                $existingTags = explode(' ', trim($matches[1]));

                // If tag already exists and the configuration is set to hide the button, return
                if (in_array($tag, $existingTags) && $this->getConf('hide_if_exists')) {
                    echo json_encode(array('status' => 'exists'));
                    exit;
                }

                // Add the tag if it doesn't already exist
                if (!in_array($tag, $existingTags)) {
                    $existingTags[] = $tag;
                    $newTagBlock = '{{tag>' . implode(' ', $existingTags) . '}}';
                    $pageContent = str_replace($matches[0], $newTagBlock, $pageContent);
                }
            } else {
                // If no {{tag>}} block exists, add one
                $newTagBlock = '{{tag>' . $tag . '}}';
                $pageContent .= "\n\n" . $newTagBlock;
            }

            // Save the updated content
            saveWikiText($id, $pageContent, 'Added tag: ' . $tag);
            echo json_encode(array('status' => 'success'));
        } else {
            echo json_encode(array('status' => 'error'));
        }
        exit;
    }
}
