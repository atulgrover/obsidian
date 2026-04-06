<?php

$pluginsDir = dirname(__DIR__);

return [
    'phpList\plugin\UpdaterPlugin\MD5Exception' => $pluginsDir . '/UpdaterPlugin/Updater.php',
    'phpList\plugin\UpdaterPlugin\TgzExtractor' => $pluginsDir . '/UpdaterPlugin/Updater.php',
    'phpList\plugin\UpdaterPlugin\Updater' => $pluginsDir . '/UpdaterPlugin/Updater.php',
    'phpList\plugin\UpdaterPlugin\ZipExtractor' => $pluginsDir . '/UpdaterPlugin/Updater.php',
];
