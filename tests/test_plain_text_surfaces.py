import ast
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.utils.error_formatter import ErrorMessageFormatter
from handlers.commands_handlers.bot_settings import BotSettingsHandler


ROOT = Path(__file__).resolve().parents[1]


def _is_plain_text_true(call: ast.Call) -> bool:
    value = next((keyword.value for keyword in call.keywords if keyword.arg == "plain_text"), None)
    return isinstance(value, ast.Constant) and value.value is True


def test_formatter_plain_text_mode_never_emits_html_tags():
    messages = [
        ErrorMessageFormatter.format_error("problem", plain_text=True),
        ErrorMessageFormatter.format_failed("operation", plain_text=True),
        ErrorMessageFormatter.format_success("done", plain_text=True),
        ErrorMessageFormatter.format_warning("careful", plain_text=True),
        ErrorMessageFormatter.format_info("details", plain_text=True),
        ErrorMessageFormatter.format_access_denied("reason", plain_text=True),
        ErrorMessageFormatter.format_not_found("File", plain_text=True),
        ErrorMessageFormatter.format_invalid("value", plain_text=True),
    ]

    assert all(not re.search(r"</?[a-zA-Z][^>]*>", message) for message in messages)


@pytest.mark.asyncio
async def test_bsetting_boolean_alert_uses_plain_text():
    settings_service = SimpleNamespace(update_setting=AsyncMock(return_value=True))
    bot = SimpleNamespace(bot_settings_service=settings_service, session_manager=None)
    handler = BotSettingsHandler(bot)
    handler.invalidate_related_caches = AsyncMock()
    handler.show_setting_details = AsyncMock()
    query = SimpleNamespace(message=object(), answer=AsyncMock())

    await handler.update_boolean_setting(query, "FEATURE_FAVORITES", True)

    alert_text = query.answer.await_args.args[0]
    assert alert_text == "✅ Success: Setting updated! Restart bot for changes to take effect."
    assert query.answer.await_args.kwargs["show_alert"] is True


def test_callback_and_inline_answers_do_not_receive_html_formatter_output():
    violations = []

    for path in (ROOT / "handlers").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            receiver = node.func.value
            if (
                node.func.attr != "answer"
                or not isinstance(receiver, ast.Name)
                or receiver.id not in {"query", "callback_query"}
            ):
                continue

            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call) or not isinstance(inner.func, ast.Attribute):
                    continue
                owner = inner.func.value
                if not (
                    isinstance(owner, ast.Name)
                    and owner.id == "ErrorMessageFormatter"
                    and inner.func.attr.startswith("format_")
                ):
                    continue
                if not _is_plain_text_true(inner):
                    violations.append(f"{path.relative_to(ROOT)}:{inner.lineno}")

            literal_values = [
                part.value
                for part in ast.walk(node)
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            ]
            if any(re.search(r"</?[a-zA-Z][^>]*>", value) for value in literal_values):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:literal-html")

    assert violations == []
