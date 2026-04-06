"""
liteparse_parser.py - Document parsing using LiteParse

This module provides document parsing using LiteParse (LlamaIndex),
an open-source, local document parsing library.

Key difference from Docling:
- LiteParse runs locally (no Docker required)
- Uses spatial grid projection for layout preservation
- Returns flattened text with page-level structure
- Output is converted to Docling-compatible format for compatibility

Usage:
    from liteparse_parser import parse_document

    result = parse_document("document.pdf")
    # Returns Docling-compatible JSON structure
"""

import os
import re
from typing import Dict, Any, Optional
from pathlib import Path


def parse_document(
    file_path: str,
    ocr_enabled: bool = True
) -> Dict[str, Any]:
    """
    Parse a document using LiteParse.

    Args:
        file_path: Path to the document file (PDF, DOCX, XLSX, PNG, etc.)
        ocr_enabled: Whether to use OCR for scanned documents

    Returns:
        Docling-compatible JSON structure with parsed content

    Raises:
        FileNotFoundError: If the file doesn't exist
        RuntimeError: If LiteParse fails to parse the document
    """
    file_path = str(Path(file_path).resolve())

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    try:
        from liteparse import LiteParse

        parser = LiteParse()
        result = parser.parse(file_path, ocr_enabled=ocr_enabled)

        # Convert LiteParse output to Docling-compatible format
        return _liteparse_to_docling_format(result, os.path.basename(file_path))

    except ImportError:
        raise RuntimeError(
            "LiteParse not installed. Install with: pip install liteparse"
        )
    except Exception as e:
        raise RuntimeError(f"Failed to parse document with LiteParse: {e}")


def _liteparse_to_docling_format(liteparse_result: Any, filename: str) -> Dict[str, Any]:
    """
    Convert LiteParse result to Docling-compatible format.

    This transformation allows existing code (DoclingStructuredChunker)
    to work with LiteParse output without modification.

    Args:
        liteparse_result: Raw result from LiteParse parser
        filename: Original filename for metadata

    Returns:
        Docling-compatible JSON structure
    """
    # Extract data from LiteParse result
    # LiteParse returns an object with text, pages, and optionally json
    if hasattr(liteparse_result, 'text'):
        full_text = liteparse_result.text
    elif hasattr(liteparse_result, 'json'):
        full_text = liteparse_result.json.get('text', '')
    else:
        full_text = str(liteparse_result)

    # Get pages information
    if hasattr(liteparse_result, 'pages'):
        pages = liteparse_result.pages
    elif hasattr(liteparse_result, 'json'):
        pages = liteparse_result.json.get('pages', [])
    else:
        pages = []

    # Build Docling-compatible structure
    # We'll create a simplified but functional structure
    texts = []
    tables = []
    pictures = []

    # Process pages and create text entries
    char_offset = 0
    for page_idx, page_data in enumerate(pages):
        if hasattr(page_data, 'textItems'):
            text_items = page_data.textItems
        elif isinstance(page_data, dict) and 'textItems' in page_data:
            text_items = page_data['textItems']
        else:
            continue

        for item_idx, item in enumerate(text_items):
            if hasattr(item, 'text'):
                item_text = item.text
            elif isinstance(item, dict) and 'text' in item:
                item_text = item['text']
            else:
                continue

            if not item_text.strip():
                continue

            # Get coordinates if available
            if hasattr(item, 'x'):
                x, y = item.x, item.y
            elif isinstance(item, dict):
                x = item.get('x', 0)
                y = item.get('y', 0)
            else:
                x, y = 0, 0

            text_ref = f"#/texts/{len(texts)}"
            texts.append({
                "text": item_text,
                "label": "text",
                "prov": [{
                    "page_no": page_idx + 1,  # Docling uses 1-based
                    "bbox": [x, y, x + 100, y + 20]  # Simplified bbox
                }]
            })

            char_offset += len(item_text)

    # Create a simple hierarchical structure
    # We'll use paragraphs as a basic structure
    body_tree = {
        "self_ref": "#/body",
        "label": "document",
        "children": []
    }

    # Group text items into paragraphs based on newlines and structure
    paragraph_count = 0
    current_paragraph = {
        "self_ref": f"#/body/paragraph_{paragraph_count}",
        "label": "paragraph",
        "children": []
    }

    for idx, text_item in enumerate(texts):
        text = text_item["text"]

        # Check if this should start a new paragraph
        # Simple heuristic: double newline or heading-like text
        if current_paragraph["children"] and (
            text.strip().endswith('\n\n') or
            _is_heading(text) or
            len(current_paragraph["children"]) > 10  # Max items per paragraph
        ):
            body_tree["children"].append(current_paragraph)
            paragraph_count += 1
            current_paragraph = {
                "self_ref": f"#/body/paragraph_{paragraph_count}",
                "label": "paragraph",
                "children": []
            }

        # Add text reference to current paragraph
        current_paragraph["children"].append({
            "self_ref": f"#/texts/{idx}",
            "label": "text"
        })

    # Add the last paragraph
    if current_paragraph["children"]:
        body_tree["children"].append(current_paragraph)

    # Build the final Docling-compatible structure
    docling_format = {
        "document": {
            "texts": texts,
            "tables": tables,
            "pictures": pictures
        },
        "body": body_tree,
        # Metadata for compatibility
        "filename": filename,
        "page_count": len(pages),
        "full_text": full_text,
        # LiteParse-specific info
        "_parser": "LiteParse",
        "_parser_version": "1.0"
    }

    return docling_format


def _is_heading(text: str) -> bool:
    """
    Simple heuristic to detect if text is likely a heading.

    Args:
        text: Text content to check

    Returns:
        True if text appears to be a heading
    """
    text = text.strip()

    # Short lines (headings are usually concise)
    if len(text) > 150:
        return False

    # Starts with number pattern (1., 1.1, 1.1.1, etc.)
    if re.match(r'^\d+(\.\d+)*\s+', text):
        return True

    # All caps (often used for main headings)
    if text.isupper() and len(text) < 50:
        return True

    # Ends with colon (common in headings)
    if text.endswith(':'):
        return True

    return False


def get_supported_formats() -> list[str]:
    """
    Get list of file formats supported by LiteParse.

    Returns:
        List of supported file extensions
    """
    return [
        '.pdf',
        '.docx',
        '.doc',
        '.xlsx',
        '.xls',
        '.pptx',
        '.ppt',
        '.txt',
        '.rtf',
        '.png',
        '.jpg',
        '.jpeg',
        '.tiff',
        '.bmp',
        '.html',
        '.htm',
        '.md'
    ]


if __name__ == "__main__":
    # Test the parser
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python liteparse_parser.py <file_path>")
        print(f"\nSupported formats: {', '.join(get_supported_formats())}")
        sys.exit(1)

    file_path = sys.argv[1]
    print(f"📄 Parsing {file_path} with LiteParse...")

    try:
        result = parse_document(file_path)

        print(f"✅ Parsed successfully")
        print(f"   Pages: {result.get('page_count', 0)}")
        print(f"   Text items: {len(result['document']['texts'])}")
        print(f"   Structure nodes: {len(result['body']['children'])}")

        # Save output for inspection
        output_file = "liteparse_output.json"
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"\n💾 Output saved to {output_file}")

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)