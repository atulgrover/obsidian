<?php
/**
 * UpdaterPlugin for phplist.
 *
 * This file is a part of UpdaterPlugin.
 *
 * This plugin is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 * This plugin is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * @category  phplist
 *
 * @author    Duncan Cameron
 * @copyright 2018 Duncan Cameron
 * @license   http://www.gnu.org/licenses/gpl.html GNU General Public License, Version 3
 */
if (interface_exists('Updater')) {
    class UpdaterPluginBase extends phplistPlugin implements Updater
    {
    }
} else {
    class UpdaterPluginBase extends phplistPlugin
    {
    }
}

class UpdaterPlugin extends UpdaterPluginBase
{
    const VERSION_FILE = 'version.txt';

    public $name = 'Updater Plugin';
    public $authors = 'Duncan Cameron';
    public $description = 'Page to update the phpList code';
    public $documentationUrl = 'https://resources.phplist.com/plugin/updater';

    public function __construct()
    {
        $this->coderoot = dirname(__FILE__) . '/' . __CLASS__ . '/';
        parent::__construct();
        $this->version = file_get_contents($this->coderoot . self::VERSION_FILE);
    }

    public function dependencyCheck()
    {
        return array(
            'phpList version 3.5.4 or greater' => version_compare(VERSION, '3.5.4') >= 0,
            'PHP version 7 or greater' => version_compare(PHP_VERSION, '7') > 0,
            'Common Plugin installed' => phpListPlugin::isEnabled('CommonPlugin'),
        );
    }

    public function activate()
    {
        $this->topMenuLinks['update'] = ['category' => 'system'];
        $this->pageTitles['update'] = 'Update phpList';
        parent::activate();
    }

    public function adminmenu()
    {
        return [];
    }
}
