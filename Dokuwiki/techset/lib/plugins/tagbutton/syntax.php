<?php

use dokuwiki\Extension\SyntaxPlugin;

/**
 * DokuWiki Plugin tagbutton (Syntax Component)
 *
 * @license GPL 2 http://www.gnu.org/licenses/gpl-2.0.html
 * @author Louis Ouellet <louis_ouellet@hotmail.com>
 */
class syntax_plugin_tagbutton extends SyntaxPlugin
{
    /** @inheritDoc */
    public function getType()
    {
       return 'substition';
    }

    /** @inheritDoc */
    public function getPType()
    {
        return 'block';
    }

    /** @inheritDoc */
    public function getSort()
    {
        return 20;
    }

    /** @inheritDoc */
    public function connectTo($mode)
    {
        $this->Lexer->addSpecialPattern('\{\{tag-button>.+?\}\}', $mode, 'plugin_tagbutton');
    }

    /** @inheritDoc */
    public function handle($match, $state, $pos, Doku_Handler $handler)
    {
        // Remove the wrapping syntax
        $match = substr($match, 13, -2);

        // Split the tag, parameter, and label
        list($tagParam, $label) = array_pad(explode('|', $match, 2), 2, null);
        list($tag, $param) = array_pad(explode(':', $tagParam, 2), 2, null);

        return array(trim($tag), trim($param), trim($label));
    }

    /** @inheritDoc */
    public function render($mode, Doku_Renderer $renderer, $data)
    {
        if($mode === 'xhtml') {
            global $ID;

            // list($tag, $label) = $data;
            list($tag, $param, $label) = $data;
            $buttonId = 'tagbutton-' . md5($tag);

            // If the label is null or empty, use the tag as the label
            if ($label === null || $label === '') {
                $label = $tag;
            }

            // Generate the button class based on the parameter
            $buttonClass = 'tagbutton';
            if ($param) {
                $buttonClass .= ' tag' . htmlspecialchars($param);
            }

            // Check if the configuration indicates to hide the button if the tag exists
            if ($this->getConf('hide_if_exists')) {
                $pageContent = rawWiki($ID);

                // Check if the tag already exists in the page
                if (preg_match('/\{\{tag>(.*?)\}\}/', $pageContent, $matches)) {
                    $existingTags = explode(' ', strtolower(trim($matches[1])));

                    // If the tag already exists, do not render the button
                    if (in_array(strtolower($tag), $existingTags)) {
                        return true;
                    }
                }
            }

            // Render the button if the tag doesn't exist or the configuration doesn't hide it
            $renderer->doc .= '<button class="' . $buttonClass . '" id="' . $buttonId . '" data-tag="' . htmlspecialchars($tag) . '">'
                              . htmlspecialchars($label) . '</button>';
        }
        return true;
    }
}
