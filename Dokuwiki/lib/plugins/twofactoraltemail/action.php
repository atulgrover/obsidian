<?php

use dokuwiki\Form\Form;
use dokuwiki\plugin\twofactor\OtpField;
use dokuwiki\plugin\twofactor\Provider;

/**
 * 2fa provider using an alternative email address
 */
class action_plugin_twofactoraltemail extends Provider
{
    /** @inheritdoc */
    public function getLabel()
    {
        $label = $this->getLang('name');
        $email = $this->settings->get('email');
        if ($email) $label .= ': ' . $email;
        return $label;
    }

    /** @inheritdoc */
    public function isConfigured()
    {
        return $this->settings->get('email') &&
            $this->settings->get('verified');

    }

    /** @inheritdoc */
    public function renderProfileForm(Form $form)
    {
        $email = $this->settings->get('email');

        if (!$email) {
            $form->addHTML('<p>' . $this->getLang('intro') . '</p>');
            $form->addTextInput('newemail', $this->getLang('email'))->attr('autocomplete', 'off');
        } else {
            $form->addHTML('<p>' . $this->getLang('verifynotice') . '</p>');
            $form->addElement(new OtpField('verify'));
        }

        return $form;
    }

    /** @inheritdoc */
    public function handleProfileForm()
    {
        global $INPUT;
        global $USERINFO;

        if ($INPUT->str('verify')) {
            // verification code given, check the code
            if ($this->checkCode($INPUT->str('verify'))) {
                $this->settings->set('verified', true);
            } else {
                $this->settings->delete('email');
            }
        } elseif ($INPUT->str('newemail')) {
            $newmail = $INPUT->str('newemail');
            // check that it differs
            if (strtolower($newmail) == strtolower($USERINFO['mail'])) {
                msg($this->getLang('notsameemail'), -1);
                return;
            }

            // new email has been, set init verification
            $this->settings->set('email', $newmail);

            try {
                $this->initSecret();
                $code = $this->generateCode();
                $info = $this->transmitMessage($code);
                msg(hsc($info), 1);
            } catch (\Exception $e) {
                msg(hsc($e->getMessage()), -1);
                $this->settings->delete('email');
            }
        }
    }

    /** @inheritdoc */
    public function getTolerance()
    {
        return $this->getConf('tolerance');
    }

    /** @inheritdoc */
    public function transmitMessage($code)
    {
        $to = $this->settings->get('email');
        if (!$to) throw new \Exception($this->getLang('codesentfail'));

        // Create the email object.
        $body = io_readFile($this->localFN('mail'));
        $mail = new Mailer();
        $mail->to($to);
        $mail->subject($this->getLang('subject'));
        $mail->setBody($body, ['CODE' => $code]);
        $result = $mail->send();
        if (!$result) throw new \Exception($this->getLang('codesentfail'));

        return $this->getLang('codesent');
    }
}
