<?php
if(!defined('DOKU_INC')) die();

class action_plugin_liteparse extends DokuWiki_Action_Plugin {

    public function register(Doku_Event_Handler $controller) {
        // Intercept page rendering before content is parsed
        $controller->register_hook('PARSER_WIKITEXT_PREPROCESS', 'BEFORE', $this, 'handle_cached_content');
        $controller->register_hook('AJAX_CALL_UNKNOWN', 'BEFORE', $this, 'handle_ajax');
    }

    public function handle_cached_content(Doku_Event $event, $param) {
        global $ID;

        $content = $event->data;

        // Find all {{liteparse>url}} patterns
        if (preg_match_all('/\{\{liteparse>([^}]+)\}\}/', $content, $matches, PREG_SET_ORDER)) {
            foreach ($matches as $match) {
                $fullMatch = $match[0];
                $url = $match[1];
                $hash = md5($url);

                // Check if cached JSON content already exists for this URL
                $cachedPattern = '/<liteparse-json hash="' . $hash . '">/s';

                if (preg_match($cachedPattern, $content)) {
                    // Cached content exists - remove the {{liteparse>...}} tag
                    // The cached content will remain in the page
                    $content = str_replace($fullMatch, '', $content);
                } else {
                    // No cached content - fetch from LiteParse
                    $result = $this->fetchFromLiteParse($url);

                    if ($result) {
                        // Save as JSON block
                        $jsonContent = json_encode($result, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
                        $cachedBlock = "<liteparse-json hash=\"$hash\">\n" . $jsonContent . "\n</liteparse-json>";
                        $content = str_replace($fullMatch, $cachedBlock, $content);

                        // Save the updated content to the page file
                        $this->savePage($ID, $content);
                    }
                }
            }
        }

        $event->data = $content;
    }

    public function handle_ajax(Doku_Event $event, $param) {
        if ($event->data !== 'liteparse_import') return;
        $event->preventDefault();
        $event->stopPropagation();

        $url = $_POST['url'] ?? '';
        $page_id = $_POST['id'] ?? '';

        if (empty($url)) {
            echo json_encode(['error' => 'No URL provided']);
            return;
        }

        $result = $this->fetchFromLiteParse($url);

        if ($result) {
            if ($page_id) {
                $hash = md5($url);
                // Save as JSON block
                $jsonContent = json_encode($result, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
                $content = "<liteparse-json hash=\"$hash\">\n" . $jsonContent . "\n</liteparse-json>";
                saveWikiText($page_id, $content, "Imported via LiteParse: " . $url);
            }
            echo json_encode(['success' => true, 'data' => $result]);
        } else {
            echo json_encode(['error' => 'Could not parse document']);
        }
    }

    private function fetchFromLiteParse($url) {
        $liteparseUrl = 'http://localhost:5001/parse';

        // Check if url is a local file path
        if (file_exists($url)) {
            return $this->uploadToLiteParse($url);
        }

        // Check if url is a remote URL
        if (preg_match('/^https?:\/\//', $url)) {
            $tempFile = sys_get_temp_dir() . '/liteparse_' . md5($url) . '.pdf';

            $ch = curl_init();
            curl_setopt($ch, CURLOPT_URL, $url);
            curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
            curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
            curl_setopt($ch, CURLOPT_TIMEOUT, 120);
            curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);

            $data = curl_exec($ch);
            $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
            curl_close($ch);

            if ($httpCode !== 200 || empty($data)) {
                return null;
            }

            // Strip HTML prefix if present (some websites wrap PDFs in HTML)
            $data = $this->stripHtmlPrefix($data);

            file_put_contents($tempFile, $data);
            $result = $this->uploadToLiteParse($tempFile);
            @unlink($tempFile);

            return $result;
        }

        return null;
    }

    /**
     * Strip HTML prefix from PDF content
     * Some websites serve PDFs with an HTML wrapper
     */
    private function stripHtmlPrefix($data) {
        // Check if data starts with PDF marker
        if (substr($data, 0, 4) === '%PDF') {
            return $data; // Already clean PDF
        }

        // Look for PDF marker in the data
        $pdfPos = strpos($data, '%PDF');
        if ($pdfPos !== false && $pdfPos < 10000) {
            // Found PDF marker, strip everything before it
            return substr($data, $pdfPos);
        }

        // Check for common HTML wrappers
        if (stripos($data, '<html') !== false || stripos($data, '<!DOCTYPE') !== false) {
            // Try to find PDF marker after HTML
            if (preg_match('/%PDF-\d\.\d/', $data, $matches, PREG_OFFSET_CAPTURE)) {
                $pdfPos = $matches[0][1];
                return substr($data, $pdfPos);
            }
        }

        // Return as-is if no HTML prefix detected
        return $data;
    }

    private function uploadToLiteParse($filePath) {
        $liteparseUrl = 'http://localhost:5001/parse';

        $ch = curl_init();
        curl_setopt($ch, CURLOPT_URL, $liteparseUrl);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);

        $mimeType = mime_content_type($filePath) ?: 'application/octet-stream';
        $cfile = new CURLFile($filePath, $mimeType, basename($filePath));
        curl_setopt($ch, CURLOPT_POSTFIELDS, ['file' => $cfile]);

        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);

        if ($httpCode === 200) {
            return json_decode($response, true);
        }

        return null;
    }

    private function savePage($id, $content) {
        $pageFile = wikiFN($id);
        $dir = dirname($pageFile);

        if (!is_dir($dir)) {
            mkdir($dir, 0755, true);
        }

        file_put_contents($pageFile, $content);

        // Clear the cache for this page
        $cacheFiles = glob(DOKU_INC . 'data/cache/*');
        foreach ($cacheFiles as $file) {
            if (is_file($file)) {
                $cacheContent = @file_get_contents($file);
                if ($cacheContent && strpos($cacheContent, $id) !== false) {
                    @unlink($file);
                }
            }
        }
    }
}