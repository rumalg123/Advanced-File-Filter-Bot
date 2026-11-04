from datetime import UTC, datetime, timedelta, timezone

import pytest

from favorites_recent_support import storage
from ban_support import user_repository

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.parametrize('encoding', ['bson', 'naive-iso', 'offset-iso'])
@pytest.mark.parametrize('expired', [False, True])
async def test_stored_warning_dates_allow_stats_escalation_and_unban(
    storage, monkeypatch, encoding, expired
):
    repo, _, db = await user_repository(storage, monkeypatch)
    now = datetime.now(UTC)
    warning_date = now - timedelta(days=31 if expired else 1)
    if encoding == 'naive-iso':
        warning_date = warning_date.replace(tzinfo=None).isoformat()
    elif encoding == 'offset-iso':
        warning_date = warning_date.astimezone(
            timezone(timedelta(hours=5, minutes=30))
        ).isoformat()
    await db.users.update_one({'_id': 42}, {'$set': {
        'warning_count': 1, 'last_warning_date': warning_date,
        'last_request_date': now.date().isoformat(), 'daily_request_count': 1,
        'daily_retrieval_count': 7,
    }})

    stats = await repo.get_request_stats(42)
    assert stats['warning_reset_in_days'] == (0 if expired else 29)
    result = await repo.track_request(42)
    assert result[0] is False and result[2] is False
    current = await db.users.find_one({'_id': 42})
    assert current['warning_count'] == (1 if expired else 2)
    # New warning writes use BSON dates too; exercise their next strict read.
    for _ in range(2 if expired else 1):
        result = await repo.track_request(42)
    assert result[2] is True
    assert (await repo.auto_ban_for_request_abuse(42))[0]
    assert (await repo.unban_user(42))[0]
    current = await db.users.find_one({'_id': 42})
    assert current['status'] == 'active'
    assert current['warning_count'] == current['daily_request_count'] == 0
    assert current['daily_retrieval_count'] == 7
