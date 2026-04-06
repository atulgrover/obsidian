# LiteParse Server

A Node.js service for parsing PDF documents using LiteParse, with intelligent paragraph reconstruction and structure detection.

## Overview

This service extracts text from PDFs and returns structured data including:
- Full text content
- Markdown output
- Page-by-page paragraphs with bounding boxes
- Structure detection (headings, lists, footers, tables)

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   DokuWiki      │────▶│  LiteParse      │────▶│   PDF File      │
│   Plugin        │     │  Server         │     │   (upload)      │
│   (action.php) │     │  (Node.js)      │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │
        │                       ▼
        │              ┌─────────────────┐
        │              │  LiteParse      │
        │              │  (npm package) │
        │              └─────────────────┘
        │
        ▼
┌─────────────────┐
│   Wiki Page     │
│   (JSON cached) │
└─────────────────┘
```

## What We've Done

### 1. LiteParse Server (`server.js`)

**Core Features:**
- Express.js server running on port 5001
- Multer for file upload handling
- LiteParse integration for PDF parsing

**Paragraph Reconstruction:**
- Groups word-level text items into lines based on Y-position proximity
- Groups lines into paragraphs based on Y-gap threshold
- Column detection via X-position clustering
- Sorts content by column, then by Y position

**Structure Detection:**
- `detectHeader()` - Detects headers via:
  - ALL CAPS text (length 3-80)
  - Large font (>14pt)
  - Numbered sections (e.g., "1. Introduction")

- `detectList()` - Detects list items via:
  - Numbered lists: `1.`, `2.`, `a)`, `b)`
  - Bullet points: `•`, `-`, `*`, `○`, `●`

- `detectFooter()` - Detects footers via:
  - Page numbers: "Page X of Y", standalone numbers
  - Keywords: "confidential", "copyright", "©"

- `detectTables()` - Detects tables via:
  - Aligned text blocks across multiple rows

**Text Cleaning:**
- Removes internal line breaks within paragraphs
- Collapses multiple spaces to single space
- Filters out page numbers

**Response Format:**
```json
{
  "success": true,
  "filename": "document.pdf",
  "text": "Full text content...",
  "markdown": "# Heading\n\nParagraph text...",
  "pages": [
    {
      "pageNum": 1,
      "paragraphs": [
        {
          "text": "Paragraph text",
          "x": 72, "y": 34, "width": 468, "height": 12,
          "avgFontSize": 12, "lineCount": 1,
          "isHeading": true, "headingLevel": 2,
          "isList": false, "isFooter": false, "isTable": false
        }
      ],
      "textItems": [...]
    }
  ],
  "metadata": {
    "totalPages": 38,
    "characterCount": 94641
  }
}
```

### 2. DokuWiki Plugin (`action.php`)

**Features:**
- Intercepts `{{liteparse>url}}` syntax in wiki pages
- Downloads PDFs from URLs or uses local files
- Strips HTML wrapper from PDFs (some websites wrap PDFs in HTML)
- Caches parsed JSON in wiki page using `<liteparse-json>` tags
- Subsequent page loads use cache (no re-parsing)

**HTML Prefix Stripping:**
Some websites (like IBBI) serve PDFs with an HTML wrapper:
```php
private function stripHtmlPrefix($data) {
    if (substr($data, 0, 4) === '%PDF') return $data;
    $pdfPos = strpos($data, '%PDF');
    if ($pdfPos !== false && $pdfPos < 10000) {
        return substr($data, $pdfPos);
    }
    // ... additional checks
}
```

### 3. DokuWiki Plugin (`syntax.php`)

**Features:**
- Custom JSON viewer with tabs:
  - **Text tab**: Full text content
  - **Pages tab**: Expandable tree of paragraphs with metadata
  - **Raw JSON tab**: Full JSON response
- Shows paragraph metadata: font size, line count, position, heading level
- Color-coded badges for headings (H1, H2, H3)
- Import button for uncached URLs

### 4. Start Script (`start-all.sh`)

Starts all services:
- DokuWiki PHP server (port 8080)
- Header Backend (port 4000)
- Header Frontend (port 5173)

### 5. Docker Container

```bash
# Build and run
docker build -t rag-liteparse-service:latest .
docker run -d --name liteparse-service -p 5001:5001 rag-liteparse-service:latest
```

## Known Issues

### 1. Concatenated Words
PDFs often have words positioned close together without proper spacing detection:
- "matterof" instead of "matter of"
- "CompanyLawTribunal" instead of "Company Law Tribunal"
- "on19.01.2025under" instead of "on 19.01.2025 under"

**Status:** Attempted word-spacing heuristics but they broke legitimate words like "NATIONAL" into "N ATI ON AL". Needs more sophisticated approach.

### 2. Table Detection
Current table detection looks for aligned X-positions but doesn't reliably identify tables in legal documents.

### 3. Multi-column Layouts
Column detection works but may not handle complex layouts perfectly.

## What We're Planning to Do Next

### Priority 1: Word Spacing (Better Approach)
Instead of regex-based heuristics, consider:
- Use LiteParse's character/word position data to detect actual spacing
- Calculate gaps between words and insert space when gap exceeds threshold
- Consider using font metrics (character widths) for more accurate detection

### Priority 2: Better Table Detection
- Look for grid lines or borders
- Detect repeated patterns across rows
- Use column alignment more aggressively
- Consider using the raw PDF's line drawing commands

### Priority 3: Enhanced Structure Detection
- Detect numbered sections hierarchy (1, 1.1, 1.1.1)
- Detect TOC (Table of Contents)
- Detect footnotes/endnotes
- Better handling of headers/footers on each page

### Priority 4: OCR Support
- Enable OCR for scanned PDFs
- Configure OCR language settings
- Handle mixed text/image documents

### Priority 5: Performance Optimization
- Stream large PDFs instead of loading entirely in memory
- Add caching layer for repeated requests
- Parallel page processing

### Priority 6: API Enhancements
- Add batch processing endpoint
- Add progress callback for large files
- Support additional formats (DOCX, images)

## File Structure

```
liteparse-server/
├── server.js          # Main Express server with parsing logic
├── package.json       # Dependencies
├── Dockerfile         # Docker configuration
├── README.md          # This file
└── uploads/           # Temporary upload directory

Dokuwiki/techset/lib/plugins/liteparse/
├── action.php         # Plugin hooks for caching
├── syntax.php         # Rendering and display
└── plugin.info.txt    # Plugin metadata
```

## Testing

```bash
# Test with IBBI PDF
curl -sL "https://ibbi.gov.in/uploads/order/5eacaf24e135ff9d244933aac64dab6b.pdf" -o test.pdf

# Strip HTML wrapper if present, then parse
curl -X POST -F "file=@test.pdf" http://localhost:5001/parse | jq '.pages[0].paragraphs[0:5]'
```

## Dependencies

- `express` - Web framework
- `multer` - File upload handling
- `@llamaindex/liteparse` - PDF parsing library

## Configuration

Environment variables:
- `PORT` - Server port (default: 5001)

LiteParse options:
```javascript
const parser = new LiteParse({
  ocrEnabled: true,
  ocrLanguage: 'en',
  preciseBoundingBox: true
});
```

## Changelog

### 2025-04-06
- Initial paragraph reconstruction implementation
- Added structure detection (headers, lists, footers, tables)
- Added line break removal within paragraphs
- Attempted and reverted word spacing heuristics
- Added HTML prefix stripping for wrapped PDFs

---

*Last updated: April 6, 2025*