import html
import pytest
from sendall_support import fixture, run


@pytest.mark.asyncio
async def test_sendall_statuses_display_query_as_literal_text(monkeypatch):
    handler, client, query, status, _ = fixture(monkeypatch)
    await run(handler, client, query)
    expected = html.escape(handler.bot.cache.get.return_value['query'])
    assert expected in client.send_message.await_args.args[1]
    assert all(expected in call.args[0] for call in status.edit_text.await_args_list)
    assert client.send_cached_media.await_count == 2
