"""An owner restart must apply the configured branch before graceful shutdown."""
import asyncio
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
from update import SecureUpdater

REPO_URL = 'https://github.com/example/restart-fixture.git'
BRANCH = 'release/qa'


@pytest.fixture
def restart_installation(tmp_path, monkeypatch):
    """Use real Git offline; main and the requested branch contain different code."""
    remote = tmp_path / 'remote'
    remote.mkdir()

    def git(*args):
        return subprocess.run(['git', *args], cwd=remote, check=True,
                              capture_output=True, text=True).stdout.strip()

    git('init', '--initial-branch', 'main')
    git('config', 'user.email', 'qa@example.invalid')
    git('config', 'user.name', 'Restart QA')
    (remote / 'bot.py').write_text('version = "old"\n')
    (remote / 'requirements.txt').write_text('# No fixture dependencies\n')
    git('add', '.')
    git('commit', '-m', 'Old main version')
    git('checkout', '-b', BRANCH)
    (remote / 'bot.py').write_text('version = "new"\n')
    (remote / 'migrate_media_metadata.py').write_text('version = "new helper"\n')
    (remote / 'core').mkdir()
    (remote / 'core' / 'logic.py').write_text('version = "new core"\n')
    # Even a tracked upstream .env must not replace the installation's secrets.
    (remote / '.env').write_text('PRIVATE=incoming\n')
    git('add', '.')
    git('commit', '-m', 'Update requested branch')
    revision = git('rev-parse', 'HEAD')

    # Git receives the validated HTTPS URL. Its test-only configuration redirects
    # transport to this local repository; no external network is required.
    monkeypatch.setenv('GIT_CONFIG_COUNT', '2')
    monkeypatch.setenv('GIT_CONFIG_KEY_0', f'url.{remote.as_uri()}.insteadOf')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', REPO_URL)
    monkeypatch.setenv('GIT_CONFIG_KEY_1', 'protocol.file.allow')
    monkeypatch.setenv('GIT_CONFIG_VALUE_1', 'always')
    monkeypatch.setenv('IN_DOCKER', 'true')
    live = tmp_path / 'installation'
    live.mkdir()
    monkeypatch.chdir(live)
    (live / 'bot.py').write_text('version = "old"\n')
    (live / 'requirements.txt').write_text('# No fixture dependencies\n')
    (live / '.env').write_text('PRIVATE=original\n')
    (live / 'bot.session').write_text('original session\n')
    (live / 'core').mkdir()
    (live / 'core' / 'obsolete.py').write_text('obsolete = True\n')
    for directory in ['data', 'logs']:
        (live / directory).mkdir()
        (live / directory / 'keep').write_text('original data\n')
    return SimpleNamespace(live=live, remote=remote, git=git, revision=revision)


def restart_handler():
    handler = object.__new__(BotSettingsHandler)
    values = {'UPSTREAM_REPO': REPO_URL, 'UPSTREAM_BRANCH': BRANCH}
    handler.settings_service = SimpleNamespace(get_setting=AsyncMock(side_effect=values.get))
    status = SimpleNamespace(chat=SimpleNamespace(id=11), id=22, edit_text=AsyncMock())
    message = SimpleNamespace(reply_text=AsyncMock(return_value=status))
    return handler, message, status


@pytest.mark.asyncio
@pytest.mark.parametrize('empty_git_dir', [False, True])
async def test_restart_applies_requested_branch_and_preserves_state_before_signal(
        restart_installation, monkeypatch, empty_git_dir):
    fixture = restart_installation
    if empty_git_dir:
        Path('.git').mkdir()  # Existing images contained this invalid empty directory.
    handler, message, status = restart_handler()
    execute = Mock()
    monkeypatch.setattr(os, 'execl', execute)

    def request_stop(pid, sig):
        assert Path('bot.py').read_text() == 'version = "new"\n'
        assert Path('migrate_media_metadata.py').read_text() == 'version = "new helper"\n'
        assert Path('core/logic.py').read_text() == 'version = "new core"\n'
        assert not Path('core/obsolete.py').exists()
        assert handler._get_git_info()['full_hash'] == fixture.revision
        assert json.loads(Path('restart_msg.txt').read_text()) == {
            'chat_id': 11, 'message_id': 22, 'git_before': None}
        assert (pid, sig) == (os.getpid(), signal.SIGTERM)
        backups = list(Path('backups').glob('backup_*'))
        assert len(backups) == 1
        assert (backups[0] / 'bot.py').read_text() == 'version = "old"\n'
        assert Path('.env').read_text() == 'PRIVATE=original\n'
        assert Path('bot.session').read_text() == 'original session\n'
        for directory in ['logs', 'data']:
            assert Path(directory, 'keep').read_text() == 'original data\n'

    stop = Mock(side_effect=request_stop)
    monkeypatch.setattr(os, 'kill', stop)
    await handler.restart_command(SimpleNamespace(), message)
    stop.assert_called_once()
    execute.assert_not_called()
    assert handler.settings_service.get_setting.await_count == 2
    assert 'updated' in status.edit_text.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['missing-branch', 'invalid-source', 'dependency-install'])
async def test_failed_update_keeps_old_source_and_does_not_restart(
        restart_installation, monkeypatch, failure):
    handler, message, status = restart_handler()
    if failure == 'missing-branch':
        values = {'UPSTREAM_REPO': REPO_URL, 'UPSTREAM_BRANCH': 'missing-branch'}
        handler.settings_service.get_setting.side_effect = values.get
    else:
        name, content = ('bot.py', 'def broken(:\n') if failure == 'invalid-source' else (
            'requirements.txt', 'fixture-package==2\n')
        (restart_installation.remote / name).write_text(content)
        restart_installation.git('add', '.')
        restart_installation.git('commit', '-m', 'Failure fixture')
    if failure == 'dependency-install':
        monkeypatch.setattr(SecureUpdater, '_install_changed_requirements',
                            Mock(side_effect=RuntimeError('fixture pip failure')))
    stop = Mock()
    monkeypatch.setattr(os, 'kill', stop)
    await handler.restart_command(SimpleNamespace(), message)
    stop.assert_not_called()
    assert Path('bot.py').read_text() == 'version = "old"\n'
    assert Path('.env').read_text() == 'PRIVATE=original\n'
    assert not Path('restart_msg.txt').exists()
    assert not Path('.runtime_revision.json').exists()
    assert handler._restart_in_progress is False
    assert 'restart cancelled' in status.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_missing_upstream_does_not_silently_restart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    handler, message, status = restart_handler()
    handler.settings_service.get_setting.side_effect = None
    handler.settings_service.get_setting.return_value = None
    update = Mock()
    stop = Mock()
    monkeypatch.setattr(SecureUpdater, 'update', update)
    monkeypatch.setattr(os, 'kill', stop)
    await handler.restart_command(SimpleNamespace(), message)
    update.assert_not_called()
    stop.assert_not_called()
    assert 'restart cancelled' in status.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_deleted_status_does_not_strand_successfully_updated_code(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('IN_DOCKER', 'true')
    handler, message, status = restart_handler()
    status.edit_text.side_effect = RuntimeError('message deleted')
    update = Mock(return_value=True)
    monkeypatch.setattr(SecureUpdater, 'update', update)
    stop = Mock()
    monkeypatch.setattr(os, 'kill', stop)
    await handler.restart_command(SimpleNamespace(), message)
    update.assert_called_once_with(install_dependencies=True)
    stop.assert_called_once_with(os.getpid(), signal.SIGTERM)
    assert Path('restart_msg.txt').exists()


@pytest.mark.asyncio
async def test_concurrent_restart_runs_only_one_update(tmp_path, monkeypatch):
    import threading
    monkeypatch.chdir(tmp_path)
    handler, message, status = restart_handler()
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def update(**kwargs):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=3)
        return False

    operation = Mock(side_effect=update)
    monkeypatch.setattr(SecureUpdater, 'update', operation)
    first = asyncio.create_task(handler.restart_command(SimpleNamespace(), message))
    try:
        await asyncio.wait_for(started.wait(), timeout=3)
        await handler.restart_command(SimpleNamespace(), message)
        assert 'already in progress' in message.reply_text.await_args.args[0]
    finally:
        release.set()
        await first
    operation.assert_called_once()
    assert handler._restart_in_progress is False


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


@pytest.mark.parametrize('provider', ['handler', 'bot'])
def test_applied_revision_is_reported_without_git(tmp_path, monkeypatch, provider):
    from bot import MediaSearchBot
    monkeypatch.chdir(tmp_path)
    revision = {'hash': 'a' * 7, 'full_hash': 'a' * 40, 'date': '2026-10-29',
                'message': 'Applied revision', 'has_changes': False}
    Path('.runtime_revision.json').write_text(json.dumps(revision))
    command = Mock(side_effect=AssertionError('source-only image must not execute Git'))
    monkeypatch.setattr(subprocess, 'run', command)
    cls = BotSettingsHandler if provider == 'handler' else MediaSearchBot
    assert cls._get_git_info(object()) == revision
    command.assert_not_called()


def test_restart_updates_then_finishes_real_wzgram_idle_and_calls_stop(restart_installation):
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
values = {'UPSTREAM_REPO': 'https://github.com/example/restart-fixture.git',
          'UPSTREAM_BRANCH': 'release/qa'}
handler.settings_service = SimpleNamespace(get_setting=AsyncMock(side_effect=values.get))
status = SimpleNamespace(chat=SimpleNamespace(id=11), id=22, edit_text=AsyncMock())
message = SimpleNamespace(reply_text=AsyncMock(return_value=status))
async def request():
    await asyncio.sleep(.1)
    await handler.restart_command(client, message)
async def start():
    loop.create_task(request())
async def stop():
    assert Path('bot.py').read_text() == 'version = "new"\\n'
    Path('stop-completed').write_text('yes')
client = SimpleNamespace(loop=loop, start=start, stop=stop)
Client.run(client)
assert Path('stop-completed').read_text() == 'yes'
loop.close()
'''
    result = subprocess.run([sys.executable, '-c', program], cwd=restart_installation.live,
        env={**os.environ, 'PYTHONPATH': str(root), 'IN_DOCKER': 'true'},
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (restart_installation.live / 'stop-completed').exists()
    revision = json.loads((restart_installation.live / '.runtime_revision.json').read_text())
    assert revision['full_hash'] == restart_installation.revision
