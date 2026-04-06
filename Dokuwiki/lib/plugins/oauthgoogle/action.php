<?php

use dokuwiki\plugin\oauthgoogle\Google;

/**
 * Service Implementation for oAuth Google authentication
 */
class action_plugin_oauthgoogle extends \dokuwiki\plugin\oauth\Adapter
{
    /**
     * We use our own, modified version of the Google service
     * @inheritdoc
     */
    public function registerServiceClass()
    {
        return Google::class;
    }

    /** * @inheritDoc */
    public function getUser()
    {
        $oauth = $this->getOAuthService();
        $data = array();

        $result = json_decode($oauth->request('https://www.googleapis.com/oauth2/v1/userinfo'), true);

        $data['user'] = $result['name'];
        $data['name'] = $result['name'];
        $data['mail'] = $result['email'];

        return $data;
    }

    /** @inheritDoc */
    public function getScopes()
    {
        return [Google::SCOPE_USERINFO_EMAIL, Google::SCOPE_USERINFO_PROFILE];
    }

    /** @inheritDoc */
    public function getLabel()
    {
        return 'Google';
    }

    /** @inheritDoc */
    public function getColor()
    {
        return '#4285F4';
    }

}
