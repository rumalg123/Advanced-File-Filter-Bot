import html

import pytest

from bsettings_support import fixture


LITERAL = 'QA <unknown> & "quoted" {file_name}'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['str', 'list'])
async def test_saved_markup_is_literal_inside_setting_details(kind):
    value = [LITERAL] if kind == 'list' else LITERAL
    handler, message, _ = fixture('CUSTOM_FILE_CAPTION', value, value, kind)
    await handler.show_setting_details(message, 'CUSTOM_FILE_CAPTION')
    rendered = message.edit_text.await_args.args[0]
    assert html.escape(LITERAL) in rendered
    assert '<unknown>' not in rendered
    assert rendered.count(html.escape(LITERAL)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('key,kind', [
    ('CUSTOM_FILE_CAPTION', 'str'), ('AUTO_DELETE_MESSAGE', 'str'), ('PICS', 'list'),
])
async def test_edit_prompt_preserves_literal_saved_value(key, kind):
    value = [LITERAL] if kind == 'list' else LITERAL
    handler, message, _ = fixture(key, value, '', kind)
    await handler.start_edit_session(message, key, 1)
    rendered = message.edit_text.await_args.args[0]
    assert '&lt;unknown&gt;' in rendered and '<unknown>' not in rendered
