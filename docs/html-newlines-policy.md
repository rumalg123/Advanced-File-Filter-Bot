# HTML + Newlines Policy

## Overview

This document establishes the standardized approach for text formatting and newline handling across the Advanced File Filter Bot codebase, ensuring consistent rendering in Telegram's HTML parse mode.

## HTML Parse Mode Requirements

### Global Configuration

- **All** Client instances MUST use `ParseMode.HTML`
- Set at Client initialization: `Client(..., parse_mode=ParseMode.HTML)`
- No per-call `parse_mode` overrides unless explicitly `ParseMode.HTML`

### Supported HTML Tags

Use only Telegram-supported HTML tags:

- `<b>text</b>` - Bold text
- `<strong>text</strong>` - Bold text (alternative)
- `<i>text</i>` - Italic text  
- `<em>text</em>` - Italic text (alternative)
- `<u>text</u>` - Underlined text
- `<s>text</s>` - Strikethrough text
- `<code>text</code>` - Monospaced inline code
- `<pre>text</pre>` - Monospaced block
- `<pre language="lang">text</pre>` - Code block with language
- `<a href="url">text</a>` - Hyperlink

### Prohibited Elements

- **NO** `<br>` tags - Telegram HTML parser doesn't support them
- **NO** `<div>`, `<span>`, `<p>`, `<h1-h6>` tags
- **NO** custom CSS or styling attributes

## Markdown Conversion

### Converted Patterns

All Markdown syntax has been converted to HTML:

- `**bold**` → `<b>bold</b>`
- `_italic_` → `<i>italic</i>`
- `__underline__` → `<u>underline</u>`
- `~~strike~~` → `<s>strike</s>`
- `` `code` `` → `<code>code</code>`
- `[text](url)` → `<a href="url">text</a>`

### User-Facing Files Converted

Critical handlers updated:
- `handlers/search.py` - Search results, subscription messages
- `handlers/filter.py` - Filter management messages
- `handlers/filestore.py` - Batch link generation
- `handlers/delete.py` - Deletion confirmations
- `handlers/decorators.py` - Subscription/ban messages
- `handlers/indexing.py` - Bot access requirements
- `handlers/request.py` - Request handling
- `handlers/connection.py` - Connection status
- `handlers/commands_handlers/user.py` - Statistics display
- `bot.py` - Restart and configuration messages

## Newline Handling

### Proper Newline Usage

- **Single newlines** (`\n`) for line breaks
- **Double newlines** (`\n\n`) for paragraph separation
- **NO** `<br>` tags - use actual newline characters
- **NO** double-escaped newlines (`\\n\\n`) - use real newlines (`\n\n`)

### Text Utilities

Use `core/utils/text_fmt.py` helpers:

```python
from core.utils.text_fmt import join_lines, join_paragraphs, bold, code

# Line breaks
text = join_lines(["Line 1", "Line 2", "Line 3"])
# Result: "Line 1\nLine 2\nLine 3"

# Paragraph breaks  
text = join_paragraphs(["Para 1", "Para 2", "Para 3"])
# Result: "Para 1\n\nPara 2\n\nPara 3"

# Safe HTML formatting with escaping
text = bold("User input with <script>")
# Result: "<b>User input with &lt;script&gt;</b>"
```

### URL Encoding

For manual URL construction (rare):
- Encode newlines as `%0A` in URL parameters
- Prefer PyroFork/Client methods over manual URL construction

## Implementation Guidelines

### Safe HTML Generation

Always escape user input:

```python
from core.utils.text_fmt import bold, code, escape_html

# Safe - automatically escapes
user_input = "<script>alert('xss')</script>"
safe_text = bold(user_input)  # "<b>&lt;script&gt;alert('xss')&lt;/script&gt;</b>"

# Manual escaping when needed
escaped = escape_html(user_input)
```

### Message Formatting Examples

**Good:**
```python
message = join_paragraphs([
    bold("File Transfer Complete"),
    f"Files sent: {count}",
    italic("Thank you for using the bot!")
])
```

**Bad:**
```python
message = f"**File Transfer Complete**<br><br>Files sent: {count}<br><i>Thank you!</i>"
```

## Testing

### Validation Script

Run `validate_html.py` to check compliance:

```bash
python validate_html.py
```

### Test Coverage

- HTML tag rendering (`tests/test_html_newlines.py`)
- Newline handling verification
- Markdown conversion accuracy
- Telegram compliance validation

## Migration Checklist

- [x] All Client instances use `ParseMode.HTML`
- [x] All `parse_mode=` calls use `ParseMode.HTML` or removed
- [x] All user-facing Markdown converted to HTML
- [x] No `<br>` tags in message strings
- [x] Proper newline characters (`\n`, `\n\n`)
- [x] HTML escaping for user input
- [x] Text formatting utilities available
- [x] Tests validate HTML compliance

## Performance Impact

- **Positive**: Consistent parsing, no mode switching overhead
- **Neutral**: HTML tags slightly longer than Markdown but negligible
- **Improved**: Better error handling with standardized format

## Maintenance

### Code Review Guidelines

1. Verify all new message strings use HTML tags
2. Check for accidental Markdown syntax introduction
3. Ensure proper newline usage (no `<br>`)
4. Validate HTML escaping for dynamic content

### Monitoring

- Run validation script in CI/CD pipeline
- Monitor for HTML parsing errors in logs
- User feedback on message formatting issues

## References

- [Telegram Bot API - Formatting](https://core.telegram.org/bots/api#formatting-options)
- [PyroFork ParseMode Enum](https://pyrofork.mayuri.my.id/main/api/enums/ParseMode)
- [PyroFork Client Documentation](https://pyrofork.mayuri.my.id/main/api/client.html)