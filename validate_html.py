#!/usr/bin/env python3
"""
Simple validation script for HTML formatting and newlines compliance
"""

import sys
import re
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from core.utils.text_fmt import (
    join_lines, join_paragraphs, bold, italic, underline, 
    strikethrough, code, pre, link, convert_markdown_to_html
)


def test_formatting():
    """Test HTML formatting functions"""
    print("Testing HTML formatting functions...")
    
    # Test basic formatting
    assert bold("test") == "<b>test</b>", "Bold formatting failed"
    assert italic("test") == "<i>test</i>", "Italic formatting failed"
    assert code("test") == "<code>test</code>", "Code formatting failed"
    
    # Test escaping
    assert bold("test & <script>") == "<b>test &amp; &lt;script&gt;</b>", "HTML escaping failed"
    
    # Test newlines
    parts = ["Line 1", "Line 2", "Line 3"]
    result = join_lines(parts)
    assert result == "Line 1\nLine 2\nLine 3", "Line joining failed"
    
    result = join_paragraphs(parts)
    assert result == "Line 1\n\nLine 2\n\nLine 3", "Paragraph joining failed"
    
    print("OK: HTML formatting functions work correctly")


def test_markdown_conversion():
    """Test Markdown to HTML conversion"""
    print("Testing Markdown conversion...")
    
    # Test bold conversion
    result = convert_markdown_to_html("**bold text**")
    assert result == "<b>bold text</b>", f"Expected '<b>bold text</b>', got '{result}'"
    
    # Test mixed conversion
    text = "This is **bold** and _italic_ and `code`"
    expected = "This is <b>bold</b> and <i>italic</i> and <code>code</code>"
    result = convert_markdown_to_html(text)
    assert result == expected, f"Expected '{expected}', got '{result}'"
    
    print("OK: Markdown conversion works correctly")


def test_newline_handling():
    """Test newline handling"""
    print("Testing newline handling...")
    
    # Test no <br> tags
    text = join_lines(["Line 1", "Line 2"])
    assert "<br>" not in text, "Found <br> tags in text"
    assert "<br/>" not in text, "Found <br/> tags in text"
    assert "<br />" not in text, "Found <br /> tags in text"
    
    # Test proper newlines
    text = join_paragraphs([bold("Para 1"), italic("Para 2")])
    assert "\n\n" in text, "Missing paragraph separation"
    assert "<b>Para 1</b>" in text, "Missing bold formatting"
    assert "<i>Para 2</i>" in text, "Missing italic formatting"
    
    print("OK: Newline handling works correctly")


def scan_for_markdown_patterns():
    """Scan for remaining Markdown patterns in code"""
    print("Scanning for remaining Markdown patterns...")
    
    # Patterns to check
    markdown_patterns = [
        r'\*\*[^*]+\*\*',  # **bold**
        r'`[^`]+`',        # `code`
        r'~~[^~]+~~',      # ~~strike~~
        r'_[^_]+_',        # _italic_
        r'\[[^\]]+\]\([^)]+\)',  # [link](url)
    ]
    
    # Files to check (critical user-facing files)
    critical_files = [
        'handlers/search.py',
        'handlers/filter.py',
        'handlers/filestore.py',
        'handlers/delete.py',
        'handlers/request.py',
        'handlers/connection.py',
        'bot.py'
    ]
    
    issues_found = 0
    
    for file_path in critical_files:
        if not Path(file_path).exists():
            continue
            
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        for pattern in markdown_patterns:
            matches = re.findall(pattern, content)
            if matches:
                # Filter out code comments and docstrings
                filtered_matches = []
                lines = content.split('\n')
                for i, line in enumerate(lines, 1):
                    if re.search(pattern, line):
                        # Skip if in comment or docstring
                        stripped = line.strip()
                        if (stripped.startswith('#') or 
                            stripped.startswith('"""') or 
                            stripped.startswith("'''") or
                            '"""' in line):
                            continue
                        filtered_matches.extend(re.findall(pattern, line))
                
                if filtered_matches:
                    print(f"FAIL: Found Markdown patterns in {file_path}: {filtered_matches}")
                    issues_found += len(filtered_matches)
    
    if issues_found == 0:
        print("OK: No critical Markdown patterns found in user-facing files")
    else:
        print(f"WARNING: Found {issues_found} Markdown patterns that need conversion")


def validate_parse_modes():
    """Check for non-HTML parse modes"""
    print("Checking for non-HTML parse modes...")
    
    non_html_patterns = [
        r'parse_mode\s*=\s*["\']markdown["\']',
        r'parse_mode\s*=\s*ParseMode\.MARKDOWN',
        r'parse_mode\s*=\s*enums\.ParseMode\.MARKDOWN',
        r'parse_mode\s*=\s*ParseMode\.DISABLED',
    ]
    
    python_files = list(Path('.').rglob('*.py'))
    issues_found = 0
    
    for file_path in python_files:
        if 'test' in str(file_path) or 'audit' in str(file_path):
            continue
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            for pattern in non_html_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    print(f"FAIL: Found non-HTML parse mode in {file_path}: {matches}")
                    issues_found += len(matches)
        except Exception:
            continue
    
    if issues_found == 0:
        print("OK: All parse modes are HTML compliant")
    else:
        print(f"WARNING: Found {issues_found} non-HTML parse modes")


def main():
    """Run all validation tests"""
    print("HTML & Newlines Compliance Validation")
    print("=" * 50)
    
    try:
        test_formatting()
        test_markdown_conversion()
        test_newline_handling()
        scan_for_markdown_patterns()
        validate_parse_modes()
        
        print("\n" + "=" * 50)
        print("SUCCESS: HTML & Newlines compliance validation completed successfully!")
        
    except Exception as e:
        print(f"\nFAIL: Validation failed: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())