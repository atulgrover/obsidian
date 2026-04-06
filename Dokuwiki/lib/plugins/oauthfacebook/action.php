<?php

use OAuth\OAuth2\Service\Facebook;

/**
 * Service Implementation for oAuth Facebook authentication
 */
class action_plugin_oauthfacebook extends \dokuwiki\plugin\oauth\Adapter
{

    /** * @inheritDoc */
    public function getUser()
    {
        $oauth = $this->getOAuthService();
        $data = array();

        $result = json_decode($oauth->request('/me?fields=name,email'), true);

        if (!empty($result['username'])) {
            $data['user'] = $result['username'];
        } else {
            $data['user'] = $result['name'];
        }
        $data['name'] = $result['name'];
        $data['mail'] = $result['email'];

        return $data;
    }

    /** @inheritDoc */
    public function getScopes()
    {
        return [Facebook::SCOPE_EMAIL];
    }

    /** @inheritDoc */
    public function getLabel()
    {
        return 'Facebook';
    }

    /** @inheritDoc */
    public function getColor()
    {
        return '#3b5998';
    }

}
