<?php

namespace dokuwiki\plugin\oauthgoogle;

/**
 * Modify the default lusitania Google Service
 */
class Google extends \OAuth\OAuth2\Service\Google {

    /**
     * To make sure we get a refresh token, we need consent for an offline
     * application. Thuse we always ask for consent again on login.
     *
     * @link https://stackoverflow.com/a/10857806/172068
     * @inheritdoc
     */
    public function getAuthorizationEndpoint()
    {
        // offline mode provides a refresh token
        $this->setAccessType('offline');

        // always show consent screen again
        $uri = parent::getAuthorizationEndpoint();
        $uri->addToQuery('prompt', 'consent');
        return $uri;
    }

}
