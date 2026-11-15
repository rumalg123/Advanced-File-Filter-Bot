"""Qualified Telegram commands must retain protection and tolerate normal spacing."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from handlers.filestore import FileStoreHandler


@pytest.mark.parametrize('command,method,protected', [
    ('/batch', 'batch_command', False), ('/pbatch', 'batch_command', True),
    ('/batch@qa_bot', 'batch_command', False), ('/pbatch@qa_bot', 'batch_command', True),
    ('/batch_premium@qa_bot', 'premium_batch_command', False),
    ('/pbatch_premium@qa_bot', 'premium_batch_command', True),
    ('/bprem@qa_bot', 'premium_batch_command', False),
    ('/pbprem@qa_bot', 'premium_batch_command', True),
])
@pytest.mark.parametrize('separator', [' ', ' \t '])
@pytest.mark.asyncio
async def test_batch_command_forms_preserve_protection(command, method, protected, separator):
    handler = object.__new__(FileStoreHandler)
    handler.bot = NS(config=NS(ADMINS=[1], DISABLE_PREMIUM=False))
    handler.filestore_service = NS(create_batch_link=AsyncMock(return_value='https://t.me/qa_bot?start=qa'),
                                    create_premium_batch_link=AsyncMock(return_value='https://t.me/qa_bot?start=qa'))
    message = NS(from_user=NS(id=1), text=separator.join([command,
        'https://t.me/c/1234567890/10', 'https://t.me/c/1234567890/11']),
        reply=AsyncMock(return_value=NS(edit=AsyncMock())))
    await getattr(handler, method)(None, message)
    service = (handler.filestore_service.create_batch_link if method == 'batch_command'
               else handler.filestore_service.create_premium_batch_link)
    service.assert_awaited_once()
    assert service.await_args.kwargs['protect'] is protected
