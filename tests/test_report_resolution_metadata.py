from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.database.errors import SearchBackendUnavailableError
from handlers.features import FeatureHandler


@pytest.mark.asyncio
@pytest.mark.parametrize('stored_name',['Reported QA file.txt',None])
async def test_resolved_report_still_notifies_when_optional_media_lookup_is_unavailable(stored_name):
    handler=object.__new__(FeatureHandler)
    report={'_id':'qa-report','file_unique_id':'qa-file','file_name':stored_name,
            'reason':'broken','reporter_ids':[42]}
    handler.repository=SimpleNamespace(resolve_file_report=AsyncMock(return_value=report),
        record_report_notification_results=AsyncMock())
    handler.bot=SimpleNamespace(media_repo=SimpleNamespace(find_file=AsyncMock(
        side_effect=SearchBackendUnavailableError('private fixture backend failure'))))
    handler._notify_reporters=AsyncMock(return_value={'notified':[42],'unreachable':[],'failed':[]})
    handler._send_report_log=AsyncMock()
    message=SimpleNamespace(text='/resolve_report qa-report',from_user=SimpleNamespace(id=1),reply_text=AsyncMock())
    await handler.resolve_report_command(SimpleNamespace(),message)
    assert handler._notify_reporters.await_args.args[2]==(stored_name or 'Unavailable file')
    assert message.reply_text.await_args.args[0]=='Report resolved. Notified 1; unreachable 0; failed 0.'
    handler.repository.record_report_notification_results.assert_awaited_once_with('qa-report',[42],[],[])
    if stored_name: handler.bot.media_repo.find_file.assert_not_awaited()
