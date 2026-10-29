"""An owner restart must preserve a deployed image and exit through client stop."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from handlers.commands_handlers.bot_settings import BotSettingsHandler


@pytest.mark.asyncio
async def test_container_restart_saves_ack_then_signals_without_git_or_upstream(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('IN_DOCKER', 'true')
    handler = object.__new__(BotSettingsHandler)
    handler._get_git_info = Mock()
    handler.settings_service = SimpleNamespace(get_setting=AsyncMock(
        side_effect=AssertionError('Container restart must not consult update settings')))
    status = SimpleNamespace(chat=SimpleNamespace(id=11), id=22, edit_text=AsyncMock())
    message = SimpleNamespace(reply_text=AsyncMock(return_value=status))
    commands = Mock()
    monkeypatch.setattr(subprocess, 'run', commands)
    execute = Mock()
    monkeypatch.setattr(os, 'execl', execute)
    def request_stop(pid, sig):
        message.reply_text.assert_awaited_once()
        assert json.loads(Path('restart_msg.txt').read_text()) == {
            'chat_id': 11, 'message_id': 22, 'git_before': None}
        assert (pid, sig) == (os.getpid(), signal.SIGTERM)
    stop = Mock(side_effect=request_stop)
    monkeypatch.setattr(os, 'kill', stop)
    await handler.restart_command(SimpleNamespace(), message)
    stop.assert_called_once()
    handler._get_git_info.assert_not_called()
    handler.settings_service.get_setting.assert_not_awaited()
    commands.assert_not_called()
    execute.assert_not_called()


@pytest.mark.parametrize('provider', ['handler', 'bot'])
@pytest.mark.parametrize('empty_git_dir', [False, True])
def test_images_without_checkout_do_not_execute_git_or_log_failure(tmp_path, monkeypatch, provider, empty_git_dir):
    from bot import MediaSearchBot
    monkeypatch.chdir(tmp_path)
    if empty_git_dir:
        (tmp_path / '.git').mkdir()
    command = Mock(side_effect=subprocess.CalledProcessError(128, ['git']))
    monkeypatch.setattr(subprocess, 'run', command)
    cls = BotSettingsHandler if provider == 'handler' else MediaSearchBot
    assert cls._get_git_info(object()) is None
    command.assert_not_called()


def test_restart_signal_finishes_real_wzgram_idle_and_calls_stop(tmp_path):
    root = Path(__file__).resolve().parents[1]
    program = '''
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from pyrogram import Client
from handlers.commands_handlers.bot_settings import BotSettingsHandler
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
handler = object.__new__(BotSettingsHandler)
handler.settings_service = SimpleNamespace(get_setting=AsyncMock(return_value=None))
status = SimpleNamespace(chat=SimpleNamespace(id=11), id=22, edit_text=AsyncMock())
message = SimpleNamespace(reply_text=AsyncMock(return_value=status))
async def request():
    await asyncio.sleep(.1)
    await handler.restart_command(client, message)
async def start():
    loop.create_task(request())
async def stop():
    Path('stop-completed').write_text('yes')
client = SimpleNamespace(loop=loop, start=start, stop=stop)
Client.run(client)
assert Path('stop-completed').read_text() == 'yes'
loop.close()
'''
    result = subprocess.run([sys.executable, '-c', program], cwd=tmp_path,
        env={**os.environ, 'PYTHONPATH': str(root), 'IN_DOCKER': 'true'},
        capture_output=True, text=True, timeout=8)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / 'stop-completed').exists()
