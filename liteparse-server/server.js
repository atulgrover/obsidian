/**
 * LiteParse Service
 *
 * Node.js service for parsing documents using LiteParse.
 * Returns both text and markdown formats with structure detection.
 */

import express from 'express';
import multer from 'multer';
import { LiteParse } from '@llamaindex/liteparse';
import { writeFileSync, mkdirSync, existsSync, unlinkSync } from 'fs';
import { join } from 'path';
import { fileURLToPath } from 'url';
import path from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const upload = multer({ dest: 'uploads/' });
const PORT = process.env.PORT || 5001;

// Create uploads directory
if (!existsSync('uploads')) {
  mkdirSync('uploads', { recursive: true });
}

// Initialize LiteParse
const parser = new LiteParse({
  ocrEnabled: true,
  ocrLanguage: 'en',
  preciseBoundingBox: true
});

// ========== Helper Functions ==========

/**
 * Detect columns by clustering X positions
 */
function detectColumns(xPositions) {
  if (xPositions.length === 0) return [0];
  const sorted = [...xPositions].sort((a, b) => a - b);
  const columns = [];
  let currentCol = [sorted[0]];

  for (let i = 1; i < sorted.length; i++) {
    if (Math.abs(sorted[i] - sorted[i-1]) > 50) {
      columns.push(currentCol[0]);
      currentCol = [sorted[i]];
    } else {
      currentCol.push(sorted[i]);
    }
  }
  columns.push(currentCol[0]);
  return columns.sort((a, b) => a - b);
}

/**
 * Get column index for an X position
 */
function getColumn(columns, x) {
  for (let i = columns.length - 1; i >= 0; i--) {
    if (x >= columns[i] - 20) return i;
  }
  return 0;
}

/**
 * Detect if a line looks like a postal/office address (not a heading)
 */
function isAddressLine(text) {
  const commaCount = (text.match(/,/g) || []).length;
  const hasAddressKeyword = /\b(floor|bhawan|nagar|road|street|place|colony|sector|block|marg|chowk|new delhi|mumbai|chennai|kolkata|bangalore|hyderabad|pune)\b/i.test(text);
  const hasPinCode = /\b\d{6}\b/.test(text);
  const hasEnDashPin = /–\d{6}/.test(text); // e.g. "New Delhi–110001"
  return (commaCount >= 2 && hasAddressKeyword) || hasPinCode || hasEnDashPin;
}

/**
 * Detect if text is a legal footnote/amendment annotation.
 * These appear in ALL CAPS in Indian legal PDFs but are editorial notes, not headings.
 * e.g. "Substituted by Notification No. IBBI/2018-19/GN/REG032, dated 5th October, 2018"
 */
function isFootnoteAnnotation(text) {
  // Bare form: "Substituted by Notification No. ..."
  if (/^(substituted|omitted|inserted|amended|added|deleted|replaced|renumbered)\s+by\b/i.test(text)) return true;
  // Number-prefixed form: "26 Substituted by ...", "45 Clause (j) omitted by ..."
  if (/^\d+\s+(substituted|omitted|inserted|amended|added|deleted|replaced|renumbered)\s+by\b/i.test(text)) return true;
  if (/^\d+\s+(clause|sub-regulation|regulation|proviso|explanation)\s+.{0,40}(omitted|substituted|inserted|deleted)\b/i.test(text)) return true;
  // Concatenated forms: "73Substitutedby..." or "73 Substitutedby..." (space missing within word)
  if (/^\d+\s*(substituted|omitted|inserted|amended|added|deleted|replaced)/i.test(text)) return true;
  return false;
}

/**
 * Detect if a line is a header
 */
function detectHeader(line, avgFontSize) {
  const text = line.text.trim();
  // Address lines look like large-font text but are not headings
  if (isAddressLine(text)) return false;
  // Editorial footnotes/amendment annotations are not headings
  if (isFootnoteAnnotation(text)) return false;
  if (text === text.toUpperCase() && text.length > 3 && text.length < 80) return true;
  if (avgFontSize > 14 && text.length < 100) return true;
  if (/^\d+(\.\d+)*\s+[A-Z]/.test(text)) return true;
  return false;
}

/**
 * Detect if text is a list item
 */
function detectList(text) {
  if (/^\d+[\.\)]\s/.test(text)) return true;
  if (/^[•\-\*\○\●]\s/.test(text)) return true;
  if (/^[a-z][\.\)]\s/i.test(text)) return true;
  // Roman numerals in parens: (i), (ii), (iii), (iv), (v), (vi) ...
  if (/^\([ivxlcdmIVXLCDM]+\)/.test(text)) return true;
  // Lettered items in parens: (a), (b), (c) ...
  if (/^\([a-zA-Z]\)/.test(text)) return true;
  return false;
}

/**
 * Detect if text is a footer
 */
function detectFooter(text) {
  const lower = text.toLowerCase();
  if (/page\s*\d+\s*(of|\/)\s*\d+/i.test(text)) return true;
  if (/^\s*\d+\s*$/.test(text)) return true;
  const footerKeywords = ['confidential', 'copyright', '©', 'all rights reserved'];
  for (const keyword of footerKeywords) {
    if (lower.includes(keyword)) return true;
  }
  return false;
}

/**
 * Detect if text is just a page number
 */
function detectPageNumber(text) {
  return /^\s*(page\s*)?\d+\s*(of\s*\d+)?\s*$/i.test(text.trim());
}

/**
 * Detect tables by looking for aligned text blocks
 */
function detectTables(paragraphs) {
  const tables = [];
  for (let i = 0; i < paragraphs.length - 2; i++) {
    const p1 = paragraphs[i];
    const p2 = paragraphs[i + 1];
    const p3 = paragraphs[i + 2];
    if (p1.lines && p2.lines && p3.lines) {
      const x1 = p1.lines.map(l => l.x);
      const x2 = p2.lines.map(l => l.x);
      const x3 = p3.lines.map(l => l.x);
      if (x1.length > 1 && x2.length > 1 && x3.length > 1 &&
          Math.abs(x1[0] - x2[0]) < 10 && Math.abs(x2[0] - x3[0]) < 10) {
        let endIdx = i + 3;
        while (endIdx < paragraphs.length) {
          const nextP = paragraphs[endIdx];
          if (nextP.lines && nextP.lines[0] && Math.abs(nextP.lines[0].x - x1[0]) < 10) {
            endIdx++;
          } else {
            break;
          }
        }
        if (endIdx - i >= 3) {
          tables.push({ id: tables.length, startIdx: i, endIdx: endIdx, columns: x1.length });
        }
      }
    }
  }
  return tables;
}

/**
 * Determine heading level from content patterns + font size.
 * Pattern-based rules take priority over font size so documents that use
 * consistent 12pt fonts (e.g. legal regulations) still get a proper hierarchy.
 *
 * H1 → Chapter / Part / Schedule / Act title
 * H2 → ALL CAPS section titles, numbered top-level sections (1., 2.)
 * H3 → Sub-sections (1.1, 1.2), mixed-case short headings
 */
function getHeadingLevel(text, avgFontSize) {
  // Font size always wins for very large text
  if (avgFontSize > 18) return 1;
  if (avgFontSize > 14) return 2;

  // Chapter / Part / Schedule / Form headings → H1
  if (/^(CHAPTER|PART|SCHEDULE|FORM|ANNEXURE)\b/i.test(text)) return 1;

  // ALL CAPS text (short) → H2
  if (text === text.toUpperCase() && text.length > 3 && text.length < 120) return 2;

  // Numbered section depth: "1." or "1. Title" → H2; "1.1" → H3
  const numMatch = text.match(/^(\d+)(\.(\d+))*/);
  if (numMatch) {
    const dots = (numMatch[0].match(/\./g) || []).length;
    return dots === 0 ? 2 : 3;
  }

  return 3;
}

/**
 * Finalize paragraph object - clean up text by removing internal line breaks
 */
function finalizeParagraph(p) {
  // Clean up text: remove line breaks, collapse spaces, fix boundary spacing
  const cleanText = p.text
    .replace(/[\r\n]+/g, ' ')      // Replace line breaks with space
    .replace(/\s+/g, ' ')          // Collapse multiple spaces to single space
    .trim()
    // Fix missing spaces at sentence/clause boundaries (e.g. "manner.Valuation", "(CD)in", "(i)clause")
    .replace(/([.!?)])([A-Za-z])/g, '$1 $2')
    // Fix ordinal suffixes running into the next word (e.g. "1stApril" → "1st April", "2ndMarch" → "2nd March")
    .replace(/(\d(?:st|nd|rd|th))([A-Z])/g, '$1 $2');

  return {
    text: cleanText,
    y: p.y,
    height: p.totalHeight,
    avgFontSize: Math.round(p.avgFontSize * 10) / 10,
    lineCount: p.lines.length,
    column: p.column || 0,
    x: Math.min(...p.lines.map(l => l.x || 0)),
    width: Math.max(...p.lines.flatMap(l => l.items.map(i => (i.x || 0) + (i.width || 0)))) -
           Math.min(...p.lines.flatMap(l => l.items.map(i => i.x || 0))),
    isHeading: p.isHeader || false,
    headingLevel: p.isHeader ? getHeadingLevel(cleanText, p.avgFontSize) : 0,
    isList: p.isList || false,
    isFooter: p.isFooter || false,
    isTable: false,
    tableId: null
  };
}

/**
 * Build line text from items, inserting spaces where X-position gaps indicate missing spaces.
 * PDFs often store consecutive words as separate text runs with no space character between them.
 */
function buildLineText(items) {
  if (items.length === 0) return '';
  let result = items[0].text || '';
  for (let i = 1; i < items.length; i++) {
    const prev = items[i - 1];
    const curr = items[i];
    const prevEnd = (prev.x || 0) + (prev.width || 0);
    const gap = (curr.x || 0) - prevEnd;
    const avgFontSize = ((curr.fontSize || 12) + (prev.fontSize || 12)) / 2;
    // Insert space if gap exceeds 25% of font size and neither item already has a boundary space
    const spaceThreshold = Math.max(2, avgFontSize * 0.25);
    const prevText = prev.text || '';
    const currText = curr.text || '';
    if (gap > spaceThreshold && !prevText.endsWith(' ') && !currText.startsWith(' ')) {
      result += ' ';
    }
    result += currText;
  }
  return result;
}

/**
 * Group text items into paragraphs with structure detection
 */
function groupIntoParagraphs(textItems, lineThreshold = 5, paragraphThreshold = 15) {
  if (!textItems || textItems.length === 0) {
    return [];
  }

  // Sort items by Y position, then by X position
  const sortedItems = [...textItems].sort((a, b) => {
    const yDiff = (a.y || 0) - (b.y || 0);
    if (Math.abs(yDiff) > lineThreshold) return yDiff;
    return (a.x || 0) - (b.x || 0);
  });

  // Detect columns
  const xPositions = sortedItems.map(i => i.x || 0);
  const columns = detectColumns(xPositions);

  // Group items into lines
  const lines = [];
  let currentLine = [];
  let currentY = null;
  let currentLineHeight = 0;

  for (const item of sortedItems) {
    const itemY = item.y || 0;
    const itemHeight = item.height || 12;

    if (currentY === null) {
      currentLine = [item];
      currentY = itemY;
      currentLineHeight = itemHeight;
    } else if (Math.abs(itemY - currentY) < lineThreshold) {
      currentLine.push(item);
      currentLineHeight = Math.max(currentLineHeight, itemHeight);
    } else {
      if (currentLine.length > 0) {
        lines.push({
          y: currentY,
          height: currentLineHeight,
          items: [...currentLine],
          text: buildLineText(currentLine),
          x: Math.min(...currentLine.map(i => i.x || 0)),
          column: getColumn(columns, Math.min(...currentLine.map(i => i.x || 0)))
        });
      }
      currentLine = [item];
      currentY = itemY;
      currentLineHeight = itemHeight;
    }
  }
  if (currentLine.length > 0) {
    lines.push({
      y: currentY,
      height: currentLineHeight,
      items: [...currentLine],
      text: buildLineText(currentLine),
      x: Math.min(...currentLine.map(i => i.x || 0)),
      column: getColumn(columns, Math.min(...currentLine.map(i => i.x || 0)))
    });
  }

  // Group lines into paragraphs
  const paragraphs = [];
  let currentParagraph = null;

  // Sort by column then Y
  lines.sort((a, b) => {
    if (a.column !== b.column) return a.column - b.column;
    return a.y - b.y;
  });

  for (const line of lines) {
    const avgFontSize = line.items.reduce((sum, i) => sum + (i.fontSize || 12), 0) / line.items.length;
    const lineText = line.text.trim();

    const isHeader = detectHeader(line, avgFontSize);
    const isList = detectList(lineText);
    const isFooter = detectFooter(lineText);
    const isPageNumber = detectPageNumber(lineText);

    if (isPageNumber) continue;

    // A line starting with "N. CapitalLetter" (e.g. "3. In exercise", "4. This circular")
    // always starts a new numbered paragraph, regardless of Y-gap
    const isNewNumberedParagraph = /^\d+\.\s*[A-Z]/.test(lineText) && !!currentParagraph;
    // Sign-off lines ("Yours faithfully", "Yours sincerely") always start a new paragraph
    const isSignOff = /^yours\s+(faithfully|sincerely|truly)/i.test(lineText);
    // Address lines (postal/office addresses) always start their own paragraph
    const isAddress = isAddressLine(lineText);

    if (isHeader || isList || isFooter || isNewNumberedParagraph || isSignOff || isAddress ||
        !currentParagraph ||
        line.column !== currentParagraph.column ||
        (line.y - (currentParagraph.y + currentParagraph.totalHeight)) > paragraphThreshold) {

      if (currentParagraph && currentParagraph.text.trim()) {
        paragraphs.push(finalizeParagraph(currentParagraph));
      }

      currentParagraph = {
        lines: [line],
        y: line.y,
        text: lineText,
        totalHeight: line.height,
        avgFontSize: avgFontSize,
        column: line.column,
        isHeader: isHeader,
        isList: isList,
        isFooter: isFooter
      };
    } else {
      currentParagraph.lines.push(line);
      currentParagraph.text += ' ' + lineText;
      currentParagraph.totalHeight += line.height;
      currentParagraph.avgFontSize = currentParagraph.lines.reduce((sum, l) => {
        return sum + l.items.reduce((s, i) => s + (i.fontSize || 12), 0) / l.items.length;
      }, 0) / currentParagraph.lines.length;
    }
  }

  if (currentParagraph && currentParagraph.text.trim()) {
    paragraphs.push(finalizeParagraph(currentParagraph));
  }

  // Detect tables
  const tables = detectTables(paragraphs);
  for (const table of tables) {
    for (let i = table.startIdx; i < table.endIdx; i++) {
      if (paragraphs[i]) {
        paragraphs[i].isTable = true;
        paragraphs[i].tableId = table.id;
      }
    }
  }

  return paragraphs;
}

/**
 * Convert parsed content to Markdown
 */
function convertToMarkdown(pages, text) {
  if (!pages || pages.length === 0) {
    return text;
  }

  let markdown = '';

  for (const page of pages) {
    const paragraphs = page.paragraphs || [];

    for (const para of paragraphs) {
      const text = para.text || '';
      if (!text.trim()) continue;

      if (para.isHeading) {
        const level = para.headingLevel || 2;
        markdown += '\n' + '#'.repeat(level) + ' ' + text.trim() + '\n\n';
      } else if (para.isList) {
        markdown += text.trim() + '\n';
      } else if (para.isFooter) {
        continue;
      } else {
        markdown += text.trim() + '\n\n';
      }
    }

    markdown += '\n---\n\n';
  }

  return markdown.trim();
}

// ========== API Endpoints ==========

app.post('/parse', upload.single('file'), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: 'No file uploaded' });
    }

    const filepath = req.file.path;
    const filename = req.file.originalname;

    console.log(`📄 Parsing ${filename} with LiteParse...`);

    const result = await parser.parse(filepath, {
      ocrEnabled: true,
      dpi: 150
    });

    // Build response pages with grouped paragraphs
    const responsePages = result.pages?.map((page, idx) => {
      const rawItems = (page.textItems || page.items || []).map(item => ({
        text: item.str || item.text || item.content || '',
        x: item.x || 0,
        y: item.y || 0,
        width: item.width || 0,
        height: item.height || 0,
        fontSize: item.fontSize,
        fontFamily: item.fontName,
        confidence: item.confidence
      }));

      const paragraphs = groupIntoParagraphs(rawItems);

      const sentenceItems = paragraphs.map(para => ({
        text: para.text,
        x: para.x,
        y: para.y,
        width: para.width,
        height: para.height,
        fontSize: para.avgFontSize,
        fontFamily: 'unknown',
        confidence: 1,
        lineCount: para.lineCount,
        isHeading: para.isHeading,
        headingLevel: para.headingLevel,
        isList: para.isList,
        isFooter: para.isFooter,
        isTable: para.isTable
      }));

      return {
        pageNum: page.pageNum || idx + 1,
        width: page.width,
        height: page.height,
        paragraphs: paragraphs,
        textItems: sentenceItems
      };
    }) || [];

    // Generate clean text from paragraphs (no line breaks within paragraphs)
    const cleanText = responsePages
      .map(page => page.paragraphs
        .filter(p => !p.isFooter)
        .map(p => p.text)
        .join('\n\n')
      )
      .join('\n\n---\n\n');

    const markdown = convertToMarkdown(responsePages, cleanText);

    const response = {
      success: true,
      filename: filename,
      text: cleanText,
      markdown: markdown,
      pages: responsePages,
      metadata: {
        totalPages: result.pages?.length || 0,
        characterCount: cleanText.length
      }
    };

    console.log(`✅ Parsed ${filename}: ${response.metadata.totalPages} pages, ${response.metadata.characterCount} chars`);
    res.json(response);

  } catch (error) {
    console.error('❌ LiteParse error:', error);
    res.status(500).json({
      success: false,
      error: error.message,
      stack: error.stack
    });
  }
});

app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'LiteParse' });
});

app.listen(PORT, () => {
  console.log(`🚀 LiteParse Service running on port ${PORT}`);
});