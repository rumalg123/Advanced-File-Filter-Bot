# core/utils/text_fmt.py
"""
Text formatting utilities for HTML mode compliance
"""

import html
from typing import List


def join_lines(parts: List[str]) -> str:
    """Join text parts with newlines"""
    return "\n".join(parts)


def join_paragraphs(parts: List[str]) -> str:
    """Join text parts with paragraph spacing (double newlines)"""
    return "\n\n".join(parts)


def escape_html(text: str) -> str:
    """Escape HTML special characters for safe rendering"""
    return html.escape(text)


def bold(text: str) -> str:
    """Format text as bold HTML"""
    return f"<b>{escape_html(text)}</b>"


def italic(text: str) -> str:
    """Format text as italic HTML"""
    return f"<i>{escape_html(text)}</i>"


def underline(text: str) -> str:
    """Format text as underlined HTML"""
    return f"<u>{escape_html(text)}</u>"


def strikethrough(text: str) -> str:
    """Format text as strikethrough HTML"""
    return f"<s>{escape_html(text)}</s>"


def code(text: str) -> str:
    """Format text as inline code HTML"""
    return f"<code>{escape_html(text)}</code>"


def pre(text: str, language: str = None) -> str:
    """Format text as preformatted block"""
    if language:
        return f'<pre language="{escape_html(language)}">{escape_html(text)}</pre>'
    return f"<pre>{escape_html(text)}</pre>"


def link(text: str, url: str) -> str:
    """Format text as HTML link"""
    return f'<a href="{escape_html(url)}">{escape_html(text)}</a>'


def convert_markdown_to_html(text: str) -> str:
    """
    Convert basic Markdown formatting to HTML
    WARNING: This is a simple converter for basic patterns
    """
    import re
    
    # Bold: **text** -> <b>text</b>
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    
    # Italic: _text_ -> <i>text</i>
    text = re.sub(r'_([^_]+)_', r'<i>\1</i>', text)
    
    # Underline: __text__ -> <u>text</u>
    text = re.sub(r'__([^_]+)__', r'<u>\1</u>', text)
    
    # Strikethrough: ~~text~~ -> <s>text</s>
    text = re.sub(r'~~([^~]+)~~', r'<s>\1</s>', text)
    
    # Inline code: `text` -> <code>text</code>
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    
    # Links: [text](url) -> <a href="url">text</a>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    
    return text