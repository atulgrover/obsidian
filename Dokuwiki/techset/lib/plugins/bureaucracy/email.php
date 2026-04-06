<?php
use dokuwiki\plugin\bureaucracy\interfaces\bureaucracy_handler_interface;

class helper_plugin_bureaucracy_handler_email implements bureaucracy_handler_interface {

    private $Data = [];
    private $FieldSet = 'classSettings';
    private $Patterns = [
        "__year__" => "@YEAR@",
        "__month__" => "@MONTH@",
        "__monthname__" => "@MONTHNAME@",
        "__day__" => "@DAY@",
        "__time__" => "@TIME@",
        "__timesec__" => "@TIMESEC@",
        "__formpage_id__" => "@FORMPAGE_ID@",
        "__formpage_ns__" => "@FORMPAGE_NS@",
        "__formpage_curns__" => "@FORMPAGE_CURNS@",
        "__formpage_file__" => "@FORMPAGE_FILE@",
        "__formpage_!file__" => "@FORMPAGE_!FILE@",
        "__formpage_!file!__" => "@FORMPAGE_!FILE!@",
        "__formpage_page__" => "@FORMPAGE_PAGE@",
        "__formpage_!page__" => "@FORMPAGE_!PAGE@",
        "__formpage_!!page__" => "@FORMPAGE_!!PAGE@",
        "__formpage_!page!__" => "@FORMPAGE_!PAGE!@",
        "__user__" => "@USER@",
        "__name__" => "@NAME@",
        "__mail__" => "@MAIL@",
        "__date__" => "@DATE@",
    ];
    private $Values = [];
    private $Settings = [
        "to" => "@MAIL@",
        "from" => "@MAIL@",
        "subject" => "@FORMPAGE_!!PAGE@",
        "showFieldSet" => "0",
        "debug" => "0",
    ];
    private $Headers = null;

    /**
    * Send email with the form data as an attachement
    */
    public function handleData($Fields, $Thanks){

        // Check if the request is a POST request
        if ($_SERVER['REQUEST_METHOD'] === 'POST'){

            // Retrieve Values
            foreach($this->Patterns as $name => $pattern){
                $this->Values[$name] = $Fields[0]->values[$name];
            }

            // Create Data Array
            foreach($Fields as $Object){

                // Identify CmdLet
                if(isset($Object->opt['cmd'])){
                    switch($Object->opt['cmd']){
                        case"fieldset":
                            if(isset($Object->opt['label'])){
                                $this->FieldSet = $Object->opt['label'];
                            } else {
                                $this->FieldSet = 'FieldSet-' . count($this->Data);
                            }
                            break;
                        default:
                            if(isset($Object->opt['label'],$Object->opt['value'])){
                                $this->Data[$this->FieldSet][$Object->opt['label']] = $Object->opt['value'];
                            }
                            break;
                    }
                }
            }

            // Replace Patterns
            foreach($this->Data as $FieldSet => $Keys){

                foreach($Keys as $Key => $Value){

                    foreach($this->Patterns as $name => $pattern){

                        $this->Data[$FieldSet][$Key] = str_replace($pattern,$this->Values[$name],$Value);
                    }
                }
            }

            // Set Class Settings
            if(isset($this->Data['classSettings'])){

                foreach($this->Data['classSettings'] as $Key => $Value){

                    if(isset($this->Settings[$Key])){

                        $this->Settings[$Key] = $Value;
                    }
                }

                // Unset classSettings
                unset($this->Data['classSettings']);
            }

            // Process Settings Values
            $this->Settings['showFieldSet'] = boolval($this->Settings['showFieldSet']);
            $this->Settings['debug'] = boolval($this->Settings['debug']);

            // Send the email
            if($this->send()){
                return $Thanks;
            }
        }

        return false;
    }

    private function send(){
        if(mail($this->Settings['to'], $this->Settings['subject'], $this->getBody($this->getMessage(),$this->getAttachement()), $this->getHeaders($this->Settings['from']))){
            return true;
        } else {
            return false;
        }
    }

    private function getHeaders($From = null){

        // Email setup
        $Headers = 'From: ' . $From . "\r\n";
        $Headers .= 'MIME-Version: 1.0' . "\r\n";
        $Headers .= 'Content-Type: multipart/mixed; boundary="boundary-string"' . "\r\n";

        // Return
        return $Headers;
    }

    private function getAttachement(){

        return null;
    }

    private function getBody($Message = null, $Attachment = null){

        // MIME Message
        $Body = "--boundary-string\r\n";
        $Body .= "Content-Type: text/html; charset=UTF-8\r\n";
        $Body .= "Content-Transfer-Encoding: 7bit\r\n\r\n";
        $Body .= $Message . "\r\n";

        // MIME Attachments
        if($Attachment){

            $Body .= "--boundary-string\r\n";
            $Body .= "Content-Type: text/csv; name=\"" . $this->Settings['filename'] . ".csv\"\r\n";
            $Body .= "Content-Transfer-Encoding: base64\r\n";
            $Body .= "Content-Disposition: attachment; filename=\"" . $this->Settings['filename'] . ".csv\"\r\n\r\n";
            $Body .= chunk_split(base64_encode($Attachment)) . "\r\n";
        }

        // MIME Boundary
        $Body .= "--boundary-string--";

        return $Body;
    }

    private function getMessage(){
        // Message setup
        $Message = "";

        // Append Values to Message
        foreach($this->Data as $FieldSet => $Keys){

            if($this->Settings['showFieldSet']){

                // Append FieldSet
                $Message .= "<h3>". $FieldSet . "</h3>" . "<br>";
            }

            // Loop through each keys
            foreach($Keys as $Key => $Value){

                // Append Key
                $Message .= "<strong>". $Key . ": </strong>" . $Value . "<br>";
            }
        }

        // Return
        return $Message;
    }
}
