<?php

class campaignslicer extends phplistPlugin {
    public $name = "Send to a subset of the total campaign";
    public $coderoot = '';
    public $version = "0.2";
    public $authors = 'Michiel Dethmers';
    public $enabled = 1;
    public $description = 'Send to a maximum of subscribers in a campaign, instead of all';

    private $actions = array(
        'suspend' => 'Suspend',
        'marksent' => 'Mark as sent',
    );
    private $yesno = array(
        'no' => 'No',
        'yes' => 'Yes',
    );

    public function sendMessageTab($messageId = 0, $messageData = array()) {

        $actionHTML = '<select name="campaignslicer_action">';
        foreach ($this->actions as $key => $val) {
            $actionHTML .= sprintf('<option value="%s" ',$key);
            if (isset($messageData['campaignslicer_action']) && $messageData['campaignslicer_action'] == $key) {
                $actionHTML .= 'selected="selected" ';
            }
            $actionHTML .= '>'.s($val).'</option>';
        }
        $actionHTML .= '</select>';
        $randomHTML = '<select name="campaignslicer_random">';
        foreach ($this->yesno as $key => $val) {
            $randomHTML .= sprintf('<option value="%s" ',$key);
            if (isset($messageData['campaignslicer_random']) && $messageData['campaignslicer_random'] == $key) {
                $randomHTML .= 'selected="selected" ';
            }
            $randomHTML .= '>'.s($val).'</option>';
        }
        $randomHTML .= '</select>';

        $html = sprintf('
            <table>
            <tr>
                <td>'.s('Maximum subscribers to send').'<br/><p class="small">'.s('Use 0 to send to all').'</p></td>
                <td><input type="text" name="%s_max" value="%d" /></td>
            </tr>
            <tr>
                <td>'.s('Action when maximum reached').'</td>

                <td>%s</td>
            </tr>
            <tr>
                <td>'.s('Randomize the subscribers').'<br/><p class="small">'.s('This will slow down the sending process').'</p></td>

                <td>%s</td>
            </tr>
            </table>','campaignslicer',isset($messageData['campaignslicer_max']) ? $messageData['campaignslicer_max']:'',$actionHTML,$randomHTML);

        return $html;
    }

    public function sendMessageTabTitle($messageid = 0)
    {
        return s('Slice');
    }

    public function viewMessage($messageid, array $messagedata) 
    {
        $key = s('Maximum slice').'<br/>'.s('Action when reached');
        $val = $messageData['campaignslicer_max'].'<br/>'.
        $messageData['campaignslicer_action'];
        return array($key,$val);
    }

    public function throttleSend($messageData, $userData)
    {
        $max = (int) $messageData['campaignslicer_max'];
        if ($max <= 0) return false;

        $totalsent = (int) $messageData['astext'] +
            $messageData['ashtml'] +
            $messageData['astextandhtml'] +
            $messageData['aspdf'] +
            $messageData['astextandpdf'] +
            $messageData['counters']['sent_users_for_message '.$messageData['id']];

        if ($totalsent >= $max) {
            switch ($messageData['campaignslicer_action']) {
                case 'marksent':
                    Sql_query(sprintf('update %s set status = "sent" where id = %d',$GLOBALS['tables']['message'], $messageData['id']));
                    logEvent(s('Campaign %d finished by campaign slicer plugin, MAX of %d reached', $messageData['id'],$messageData['campaignslicer_max']));
                    break;
                case 'suspend':
                default:
                    Sql_query(sprintf('update %s set status = "suspended" where id = %d',$GLOBALS['tables']['message'], $messageData['id']));
                    logEvent(s('Campaign %d suspended by campaign slicer plugin, MAX of %d reached', $messageData['id'],$messageData['campaignslicer_max']));
                    break;
            }

            return true;
        }
        if ($messageData['campaignslicer_random'] == 'yes') {
            $segmentSize = (int) ($messageData['counters']['total_users_for_message '.$messageData['id']] / $max);
            if (rand(1,$segmentSize) == 1) {
                return false;
            } else {
                return true;
            }
        }

        return false;
    }

    public function dependencyCheck() {
        global $plugins;
        return array(
            'phpList version 3.3.3 or later' => version_compare(VERSION, '3.3.3') > 0,
        );
    }
}
