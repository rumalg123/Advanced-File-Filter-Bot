"""Filter bodies and keyboards survive storage and actual SDK serialization."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from pyrogram import enums
from pyrogram.types import InlineKeyboardButton

import core.services.filter as filters
from core.services.filter import FilterService
from handlers.filter import FilterHandler


@pytest.mark.parametrize('source,expected', [
    ('qa hello world with spaces', ['qa', 'hello world with spaces']),
    ('"two words" <b>formatted body</b>', ['two words', '<b>formatted body</b>']),
    ('qa "hello world"', ['qa', 'hello world']),
    ("qa user's unquoted content", ['qa', "user's unquoted content"]),
])
def test_parser_preserves_the_complete_response(source, expected):
    assert object.__new__(FilterHandler)._split_quotes(source) == expected


@pytest.mark.parametrize('source', ['"" body', "'' body", '"unterminated', '   '])
def test_parser_rejects_empty_or_malformed_keywords(source):
    assert object.__new__(FilterHandler)._split_quotes(source) == []


def service():
    return FilterService(NS(), NS(), NS(), NS())


@pytest.mark.asyncio
@pytest.mark.parametrize('private,media', [(False, False), (False, True), (True, False), (True, True)])
async def test_keyboard_roundtrip_uses_sdk_buttons(monkeypatch, private, media):
    svc = service()
    payload = svc.serialize_buttons([[InlineKeyboardButton('URL', url='https://example.com')]])
    api = AsyncMock()
    monkeypatch.setattr(filters.telegram_api, 'call_api', api)
    client = NS(send_message=object(), send_cached_media=object())
    message = NS(id=7, reply_to_message=None, chat=NS(id=12 if private else -1001,
                 type=enums.ChatType.PRIVATE if private else enums.ChatType.SUPERGROUP))
    assert await svc.send_filter_response(client, message, 'complete response', payload, None,
                                          'qa-media' if media else 'None', group_id='-1001')
    keyboard = api.await_args.kwargs['reply_markup'].inline_keyboard
    assert keyboard[0][0].url == 'https://example.com'
    assert isinstance(keyboard[0][0], InlineKeyboardButton)


def test_legacy_keyboard_repr_is_decoded_without_evaluation():
    svc = service()
    buttons = [[InlineKeyboardButton('URL', url='https://example.com')]]
    assert svc.deserialize_buttons(str(buttons))[0][0].text == 'URL'
    with pytest.raises(ValueError):
        svc.deserialize_buttons("[[__import__('os').system('false')]]")


@pytest.mark.asyncio
async def test_failed_delivery_is_not_a_successful_match(monkeypatch):
    svc = service()
    svc.get_all_filters = AsyncMock(return_value=['qa'])
    svc.get_filter = AsyncMock(return_value=('hello', '[]', None, 'None'))
    monkeypatch.setattr(filters.telegram_api, 'call_api', AsyncMock(side_effect=ConnectionError('QA offline')))
    msg = NS(id=7, reply_to_message=None, text='qa', chat=NS(id=-1001, type=enums.ChatType.SUPERGROUP))
    assert not await svc._check_filter_match(NS(send_message=object()), msg, 'qa', '-1001')


@pytest.mark.asyncio
async def test_delete_absent_filter_reports_a_result():
    handler = object.__new__(FilterHandler)
    handler.bot = NS(config=NS(ADMINS=[12]))
    handler.filter_service = NS(get_active_group_id=AsyncMock(return_value=(-1001, 'QA')),
                                get_all_filters=AsyncMock(return_value=[]))
    handler._check_admin_rights = AsyncMock(return_value=True)
    message = NS(from_user=NS(id=12), text='/del absent', reply_text=AsyncMock())
    await handler.delete_filter_command(None, message)
    assert 'No matching filters' in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('private', [False, True])
async def test_captionless_media_filter_is_a_valid_search_match(private):
    from handlers.search import SearchHandler
    handler = object.__new__(SearchHandler)
    svc = NS(get_all_filters=AsyncMock(return_value=['captionlessqa']),
             get_filter=AsyncMock(return_value=('', '[]', None, 'qa-media-file')),
             send_filter_response=AsyncMock(return_value=True))
    handler.bot = NS(config=NS(DISABLE_FILTER=False), filter_service=svc,
                     connection_service=NS(can_manage_group=AsyncMock(return_value=True)))
    assert await handler._check_and_send_filter(None, NS(), 'captionlessqa', '-1001', 12, private)
    assert svc.send_filter_response.await_args.args[5] == 'qa-media-file'


@pytest.mark.parametrize('plain,expected', [
    ('"two words" response with spaces', ['two words', 'response with spaces']),
    ("'two words' response with spaces", ['two words', 'response with spaces']),
    ('"" body', []), ("'' body", []), ('"unterminated', []),
    ('qa "hello world"', ['qa', 'hello world']),
])
def test_telegram_html_escaping_does_not_change_keyword_syntax(plain, expected):
    from pyrogram.types.messages_and_media.message import Str
    encoded = Str(plain).init([]).html
    assert object.__new__(FilterHandler)._split_quotes(encoded) == expected


def test_button_labels_urls_and_alerts_decode_sdk_html_entities():
    from pyrogram.types.messages_and_media.message import Str
    body = 'body [A & B](buttonurl:https://example.com/?a=1&b=2) [Info](buttonalert:Tom & "QA")'
    _, buttons, alerts = service().parse_filter_text(Str(body).init([]).html, 'qa')
    assert buttons[0][0].text == 'A & B'
    assert buttons[0][0].url == 'https://example.com/?a=1&b=2'
    assert alerts == ['Tom & "QA"']
