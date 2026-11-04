"""Updater tests operate on temporary installations, never this server tree."""
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

import update as updater_module
from update import SecureUpdater


@pytest.fixture
def updater(tmp_path, monkeypatch):
    live=tmp_path/'installation';live.mkdir();monkeypatch.chdir(live)
    monkeypatch.setattr(SecureUpdater,'_detect_docker_environment',lambda self:False)
    return SecureUpdater('https://github.com/example/bot.git',backup_dir=str(tmp_path/'backups'))


@pytest.mark.parametrize('url',['', 'http://github.com/a/b','https://github.com.evil/a',
    'https://github.com/a/b;id','https://github.com/a/$HOME','https://github.com/a/$(id)',
    'https://github.com/a/`id`','https://gitlab.com/a/b|id','https://bitbucket.org/a/b&x'])
def test_repository_validation_rejects_shell_or_untrusted_transport(updater,url):
    with pytest.raises(ValueError):updater._validate_repo_url(url)


@pytest.mark.parametrize('url',['https://github.com/a/b.git','https://gitlab.com/a/b','https://bitbucket.org/a/b'])
def test_allowed_repository_hosts(updater,url):assert updater._validate_repo_url(url)==url


@pytest.mark.parametrize('branch',['','bad branch','bad;id','bad&x','bad|x','bad`x','bad$x'])
def test_invalid_branch_rejected(updater,branch):
    with pytest.raises(ValueError):updater._validate_branch(branch)


def test_branch_with_slashes_is_supported(updater):assert updater._validate_branch('fix/qa-123')=='fix/qa-123'


def test_backup_restore_and_apply_use_only_the_temporary_installation(updater,tmp_path):
    live=updater.current_dir
    (live/'bot.py').write_text('version="old"\n');(live/'requirements.txt').write_text('wzgram\n')
    (live/'.env').write_text('PRIVATE=fixture\n')
    (live/'core').mkdir();(live/'core'/'logic.py').write_text('old=True\n')
    (live/'scripts').mkdir();(live/'scripts'/'operator.py').write_text('old=True\n')
    backup=updater._create_backup()
    assert not (backup/'.env').exists()
    source=tmp_path/'incoming';source.mkdir()
    (source/'bot.py').write_text('version="new"\n');(source/'requirements.txt').write_text('wzgram\n')
    (source/'core').mkdir();(source/'core'/'logic.py').write_text('new=True\n')
    (source/'scripts').mkdir();(source/'scripts'/'operator.py').write_text('new=True\n')
    (source/'Dockerfile').write_text('FROM python:3.13\n')
    assert updater._validate_update(source)
    updater._apply_update(source)
    assert (live/'core'/'logic.py').read_text()=='new=True\n'
    assert (live/'scripts'/'operator.py').read_text()=='new=True\n'
    assert updater.rollback(str(backup))
    assert (live/'bot.py').read_text()=='version="old"\n'
    assert (live/'core'/'logic.py').read_text()=='old=True\n'
    assert (live/'scripts'/'operator.py').read_text()=='old=True\n'
    assert (live/'.env').read_text()=='PRIVATE=fixture\n'
    assert not updater.rollback(str(tmp_path/'absent'))


def test_backup_names_never_overwrite_an_earlier_recovery_point(updater):
    (updater.current_dir/'bot.py').write_text('old=True\n')
    first=updater._create_backup()
    (updater.current_dir/'bot.py').write_text('new=True\n')
    second=updater._create_backup()
    assert first!=second
    assert (first/'bot.py').read_text()=='old=True\n'


def test_failed_backup_prevents_update_instead_of_reporting_success(updater,monkeypatch):
    (updater.current_dir/'bot.py').write_text('old=True\n')
    monkeypatch.setattr(updater_module.shutil,'copy2',Mock(side_effect=PermissionError('copy denied')))
    clone=Mock();monkeypatch.setattr(updater,'_clone_repository',clone)
    assert updater.update() is False
    clone.assert_not_called()


@pytest.mark.parametrize('bad', ['missing-bot','bad-python','bad-requirements'])
def test_invalid_update_never_applies(updater,tmp_path,bad):
    source=tmp_path/'invalid';source.mkdir()
    if bad!='missing-bot':(source/'bot.py').write_text('def broken(:\n' if bad=='bad-python' else 'ok=True\n')
    (source/'requirements.txt').write_text('pkg$(id)\n' if bad=='bad-requirements' else '# comment\nwzgram\n')
    assert updater._validate_update(source) is False


@pytest.mark.parametrize('validate,error,success',[(True,None,True),(False,None,False),
    (True,RuntimeError('apply failed'),False)])
def test_update_always_cleans_clone_and_preserves_backup(updater,tmp_path,monkeypatch,validate,error,success):
    monkeypatch.setattr(updater,'_create_backup',Mock(return_value=tmp_path/'backup'))
    monkeypatch.setattr(updater,'_clone_repository',Mock(return_value=tmp_path/'source'))
    monkeypatch.setattr(updater,'_validate_update',Mock(return_value=validate))
    apply=Mock(side_effect=error);monkeypatch.setattr(updater,'_apply_update',apply)
    cleanup=Mock();monkeypatch.setattr(updater,'_cleanup',cleanup)
    assert updater.update()==success
    cleanup.assert_called_once()
    assert apply.call_count==int(validate)


def test_clone_uses_an_argument_list_and_cleanup_removes_only_its_directory(updater,monkeypatch):
    run=Mock();monkeypatch.setattr(updater,'_run_command',run)
    source=updater._clone_repository()
    args=run.call_args.args[0]
    assert args[:2]==['git','clone'] and args[-2:]==[updater.repo_url,str(source)]
    assert source.parent.exists()
    updater._cleanup();assert not source.parent.exists()


@pytest.mark.parametrize('failure',[None,subprocess.TimeoutExpired(['git'],300),
    subprocess.CalledProcessError(1,['git'],output='out',stderr='err')])
def test_subprocess_timeout_and_error_contract(updater,monkeypatch,failure):
    result=subprocess.CompletedProcess(['git','status'],0,stdout='ok')
    run=Mock(return_value=result,side_effect=failure);monkeypatch.setattr(updater_module.subprocess,'run',run)
    if failure is None:assert updater._run_command(['git','status']) is result
    else:
        with pytest.raises(type(failure)):updater._run_command(['git','status'])
    assert run.call_args.kwargs['timeout']==300 and run.call_args.kwargs['check'] is True
    assert 'shell' not in run.call_args.kwargs


@pytest.mark.parametrize('mode', ['update', 'rollback'])
@pytest.mark.parametrize('success', [False, True])
def test_cli_routes_explicit_arguments_and_returns_operation_status(updater, monkeypatch, mode, success):
    operation = Mock(return_value=success)
    monkeypatch.setattr(SecureUpdater, mode, operation)
    argv = ['update.py', '--repo', updater.repo_url, '--branch', 'fix/qa']
    argv += ['--rollback', str(updater.backup_dir)] if mode == 'rollback' else ['--skip-backup']
    monkeypatch.setattr('sys.argv', argv)
    with pytest.raises(SystemExit) as exit_code:
        updater_module.main()
    assert exit_code.value.code == (0 if success else 1)
    if mode == 'rollback':
        operation.assert_called_once_with(str(updater.backup_dir))
    else:
        operation.assert_called_once_with(skip_backup=True)


def test_cli_rejects_invalid_repository_without_starting_update(updater, monkeypatch):
    operation = Mock()
    monkeypatch.setattr(SecureUpdater, 'update', operation)
    monkeypatch.setattr('sys.argv', ['update.py', '--repo', 'http://invalid.test/bot'])
    with pytest.raises(SystemExit) as exit_code:
        updater_module.main()
    assert exit_code.value.code == 1
    operation.assert_not_called()


def test_docker_update_preserves_build_dockerfile_and_updates_application(updater, tmp_path):
    updater.in_docker = True
    (updater.current_dir/'Dockerfile').write_text('original build')
    (updater.current_dir/'bot.py').write_text('old application')
    source = tmp_path/'incoming'; source.mkdir()
    (source/'Dockerfile').write_text('incoming build')
    (source/'bot.py').write_text('new application')
    updater._apply_update(source)
    assert (updater.current_dir/'Dockerfile').read_text() == 'original build'
    assert (updater.current_dir/'bot.py').read_text() == 'new application'


def test_rollback_reports_copy_failure(updater, tmp_path, monkeypatch):
    backup = tmp_path/'recovery'; backup.mkdir()
    (backup/'bot.py').write_text('backup application')
    monkeypatch.setattr(updater_module.shutil, 'copy2', Mock(side_effect=PermissionError('fixture')))
    assert updater.rollback(str(backup)) is False


@pytest.mark.parametrize('docker,venv', [(False, False), (True, False), (True, True)])
def test_explicit_update_installs_changed_requirements_with_matching_python(
        updater, tmp_path, monkeypatch, docker, venv):
    source = tmp_path / 'incoming'; source.mkdir()
    (source / 'requirements.txt').write_text('new-package==2\n')
    (updater.current_dir / 'requirements.txt').write_text('old-package==1\n')
    updater.in_docker = docker
    monkeypatch.setattr(updater_module.sys, 'prefix', '/fixture-venv' if venv else updater_module.sys.base_prefix)
    run = Mock()
    monkeypatch.setattr(updater, '_run_command', run)
    updater._install_changed_requirements(source)
    command = run.call_args.args[0]
    assert command[:4] == [updater_module.sys.executable, '-m', 'pip', 'install']
    assert command[-2:] == ['-r', str(source / 'requirements.txt')]
    assert ('--user' in command) == (docker and not venv)
    assert '--no-deps' not in command


def test_unchanged_requirements_do_not_contact_package_index(updater, tmp_path, monkeypatch):
    source = tmp_path / 'incoming'; source.mkdir()
    for directory in [source, updater.current_dir]:
        (directory / 'requirements.txt').write_text('wzgram\n')
    run = Mock()
    monkeypatch.setattr(updater, '_run_command', run)
    updater._install_changed_requirements(source)
    run.assert_not_called()


def test_partial_apply_failure_restores_previous_source_and_revision(updater, tmp_path, monkeypatch):
    live = updater.current_dir
    (live / 'bot.py').write_text('version="old"\n')
    (live / '.runtime_revision.json').write_text('{"full_hash":"old"}')
    (live / '.env').write_text('PRIVATE=original\n')
    source = tmp_path / 'incoming'; source.mkdir()
    (source / 'bot.py').write_text('version="new"\n')
    (source / 'requirements.txt').write_text('# fixture\n')
    monkeypatch.setattr(updater, '_clone_repository', Mock(return_value=source))

    def interrupted_copy(source_dir):
        (live / 'bot.py').write_text('version="partially applied"\n')
        raise OSError('fixture disk failure')

    monkeypatch.setattr(updater, '_apply_update', interrupted_copy)
    assert updater.update() is False
    assert (live / 'bot.py').read_text() == 'version="old"\n'
    assert (live / '.runtime_revision.json').read_text() == '{"full_hash":"old"}'
    assert (live / '.env').read_text() == 'PRIVATE=original\n'
    assert (updater.last_backup / 'bot.py').read_text() == 'version="old"\n'


def test_rollback_to_image_source_removes_later_applied_revision(updater):
    live = updater.current_dir
    (live / 'bot.py').write_text('version="old"\n')
    backup = updater._create_backup()
    (live / 'bot.py').write_text('version="new"\n')
    (live / '.runtime_revision.json').write_text('{"full_hash":"new"}')
    assert updater.rollback(str(backup))
    assert (live / 'bot.py').read_text() == 'version="old"\n'
    assert not (live / '.runtime_revision.json').exists()
