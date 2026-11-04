"""Maintenance errors retain type/code while redacting arbitrary driver payloads."""
from unittest.mock import AsyncMock, Mock

import pytest
from pymongo.errors import DuplicateKeyError, OperationFailure, ServerSelectionTimeoutError

from core.utils.operator_errors import operator_error_summary

SENSITIVE = 'mongodb://fixture-user:fixture-password@private.invalid/fixture-media'


@pytest.mark.parametrize('error,expected', [
    (ConnectionError(SENSITIVE), 'ConnectionError'),
    (ServerSelectionTimeoutError(SENSITIVE), 'ServerSelectionTimeoutError'),
    (OperationFailure(SENSITIVE, code=13, details={'raw': SENSITIVE}), 'OperationFailure, MongoDB code 13'),
    (DuplicateKeyError(SENSITIVE, code=11000, details={'keyValue': SENSITIVE}), 'DuplicateKeyError, MongoDB code 11000'),
])
def test_error_summary_omits_message_details_and_credentials(error, expected):
    assert operator_error_summary(error) == expected
    assert SENSITIVE not in operator_error_summary(error)


@pytest.mark.parametrize('code', [None, True, SENSITIVE])
def test_non_numeric_error_codes_are_not_rendered(code):
    error = RuntimeError(SENSITIVE)
    error.code = code
    assert operator_error_summary(error) == 'RuntimeError'


@pytest.mark.parametrize('tool', ['activate_media_owners', 'backfill_search_tokens'])
@pytest.mark.parametrize('error', [
    ConnectionError(SENSITIVE),
    ServerSelectionTimeoutError(SENSITIVE),
    OperationFailure(SENSITIVE, code=18, details={'errmsg': SENSITIVE}),
    DuplicateKeyError(SENSITIVE, code=11000, details={'keyValue': SENSITIVE}),
])
def test_cli_error_output_preserves_category_and_numeric_code_without_raw_payload(
        monkeypatch, capsys, tool, error):
    import importlib
    cli = importlib.import_module('scripts.' + tool)
    monkeypatch.setattr('sys.argv', [tool])
    if tool == 'activate_media_owners':
        monkeypatch.setenv('MEDIA_OWNER_SOURCES_JSON', '[{"uri":"mongodb://localhost","name":"qa"}]')
        monkeypatch.setattr(cli, 'operate', AsyncMock(side_effect=error))
    else:
        monkeypatch.setenv('DATABASE_URI', 'mongodb://localhost')
        monkeypatch.setenv('DATABASE_NAME', 'qa')
        monkeypatch.setattr(cli, 'MongoClient', Mock(side_effect=error))
    with pytest.raises(SystemExit) as exit_code:
        cli.main()
    assert exit_code.value.code == 1
    captured = capsys.readouterr()
    assert type(error).__name__ in captured.err
    if type(getattr(error, 'code', None)) is int:
        assert str(error.code) in captured.err
    for private in [SENSITIVE, 'fixture-user', 'fixture-password', 'private.invalid', 'fixture-media']:
        assert private not in captured.out + captured.err
