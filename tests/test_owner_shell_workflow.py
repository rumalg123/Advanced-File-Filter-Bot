"""Owner shell QA runs harmless Python children inside the isolated test runner."""
import asyncio
import shlex
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from handlers.commands_handlers.admin import AdminCommandHandler


def fixture(code, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    command=shlex.quote(sys.executable)+' -c '+shlex.quote(code)
    status=SimpleNamespace(edit_text=AsyncMock())
    message=SimpleNamespace(text='/shell '+command,from_user=SimpleNamespace(id=1),
        reply_text=AsyncMock(return_value=status),reply_document=AsyncMock())
    handler=AdminCommandHandler(SimpleNamespace(config=SimpleNamespace(ADMINS=[1])))
    return handler,message,status


@pytest.mark.asyncio
async def test_owner_shell_wait_does_not_block_unrelated_bot_work(tmp_path,monkeypatch):
    handler,message,status=fixture('import time; time.sleep(0.25); print("qa-ready")',tmp_path,monkeypatch)
    started=time.monotonic();probe=[]
    async def unrelated_work():
        await asyncio.sleep(0.02);probe.append(time.monotonic()-started)
    await asyncio.gather(handler.shell_command(None,message),unrelated_work())
    assert probe[0]<0.15,'Shell execution blocked the bot event loop'
    assert 'qa-ready' in status.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_owner_shell_output_is_literal_telegram_html(tmp_path,monkeypatch):
    handler,message,status=fixture('import sys; print("<qa>&"); print("<err>&",file=sys.stderr)',tmp_path,monkeypatch)
    await handler.shell_command(None,message)
    result=status.edit_text.await_args.args[0]
    assert '&lt;qa&gt;&amp;' in result and '&lt;err&gt;&amp;' in result
    initial=message.reply_text.await_args.args[0]
    assert '<qa>' not in initial


@pytest.mark.asyncio
async def test_failed_shell_output_upload_removes_its_temporary_file(tmp_path,monkeypatch):
    handler,message,status=fixture('print("QA"*3000)',tmp_path,monkeypatch)
    message.reply_document.side_effect=RuntimeError('QA upload failed')
    await handler.shell_command(None,message)
    message.reply_document.assert_awaited_once()
    assert not Path(message.reply_document.await_args.args[0]).exists()
    assert not list(tmp_path.glob('shell_output_*.txt'))


@pytest.mark.asyncio
async def test_concurrent_shell_output_files_are_distinct_and_removed(tmp_path,monkeypatch):
    first,one,_=fixture('print("A"*5000)',tmp_path,monkeypatch)
    second,two,_=fixture('print("B"*5000)',tmp_path,monkeypatch)
    paths=[];contents=[];both=asyncio.Event()
    async def upload(filename,**kwargs):
        paths.append(Path(filename))
        if len(paths)==2:both.set()
        await both.wait()
        contents.append(Path(filename).read_text())
    one.reply_document.side_effect=upload;two.reply_document.side_effect=upload
    await asyncio.wait_for(asyncio.gather(first.shell_command(None,one),second.shell_command(None,two)),3)
    assert len(set(paths))==2 and all(not path.exists() for path in paths)
    assert any('A'*5000 in value for value in contents) and any('B'*5000 in value for value in contents)


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel',[False,True])
async def test_shell_timeout_or_cancellation_terminates_child_process_group(tmp_path,monkeypatch,cancel):
    code='import os,time,pathlib; pathlib.Path("child.pid").write_text(str(os.getpid())); print("started",flush=True); time.sleep(30)'
    handler,message,status=fixture(code,tmp_path,monkeypatch)
    monkeypatch.setattr(handler,'SHELL_TIMEOUT_SECONDS',5 if cancel else .2)
    task=asyncio.create_task(handler.shell_command(None,message))
    deadline=time.monotonic()+2
    pidfile=tmp_path/'child.pid'
    while not pidfile.exists():
        assert time.monotonic()<deadline
        await asyncio.sleep(.01)
    pid=int(pidfile.read_text())
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    else:
        await asyncio.wait_for(task,2)
        assert 'timed out' in status.edit_text.await_args.args[0]
    state=Path(f'/proc/{pid}/stat')
    # A container init can reap the terminated orphan slightly later.
    assert not state.exists() or state.read_text().split()[2]=='Z'


@pytest.mark.asyncio
async def test_non_owner_cannot_launch_a_shell_child(tmp_path,monkeypatch):
    handler,message,status=fixture('print("forbidden")',tmp_path,monkeypatch)
    message.from_user.id=2
    create=AsyncMock();monkeypatch.setattr(asyncio,'create_subprocess_shell',create)
    await handler.shell_command(None,message)
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_dangerous_command_guard_does_not_offer_an_unimplemented_confirmation(tmp_path,monkeypatch):
    handler,message,status=fixture('print("unused")',tmp_path,monkeypatch)
    message.text='/shell rm -rf /tmp/qa-never-run'
    create=AsyncMock();monkeypatch.setattr(asyncio,'create_subprocess_shell',create)
    await handler.shell_command(None,message)
    create.assert_not_awaited()
    assert 'EXECUTE ANYWAY' not in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_shell_output_write_failure_also_removes_the_created_file(tmp_path,monkeypatch):
    import tempfile
    handler,message,status=fixture('print("QA"*3000)',tmp_path,monkeypatch)
    factory=tempfile.NamedTemporaryFile;created=[]
    class BrokenWrite:
        def __enter__(self):
            self.file=factory(mode='w',prefix='shell_output_',suffix='.txt',delete=False)
            self.name=self.file.name;created.append(Path(self.name));return self
        def __exit__(self,*args):self.file.close()
        def write(self,text):raise OSError('simulated full disk')
    monkeypatch.setattr(tempfile,'NamedTemporaryFile',lambda **kwargs:BrokenWrite())
    await handler.shell_command(None,message)
    assert created and not any(path.exists() for path in created)
    message.reply_document.assert_not_awaited()
