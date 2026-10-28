"""Offline, non-destructive protected-state copy regression tests."""
import pytest

from scripts.migrate_redis_state import transfer_state


class FakeSource:
    def __init__(self, records):
        self.records = records
        self.deleted = False

    def scan_iter(self, count=200):
        yield from self.records

    def pttl(self, key):
        return self.records[key][0]

    def dump(self, key):
        return self.records[key][1]

    def delete(self, *_args):
        self.deleted = True
        raise AssertionError("Migration must never remove source keys")


class FakeDestination:
    def __init__(self):
        self.records = {}
        self.restores = []

    def exists(self, key):
        return key in self.records

    def restore(self, key, ttl, payload, replace=False):
        assert replace is False
        self.records[key] = (ttl, payload)
        self.restores.append((key, ttl, payload))


def test_dry_run_does_not_write_or_remove_any_state():
    source = FakeSource({
        b"rate_limit:42:search": (900, b"counter"),
        b"session:search:42": (1800000, b"session"),
        b"search:doctor x": (45000, b"cache"),
        b"cache:search:version": (-1, b"version"),
    })
    dest = FakeDestination()

    count = transfer_state(source, dest, apply=False)

    assert count["identified"] == 3
    assert count["would_copy"] == 3
    assert dest.records == {}
    assert not source.deleted


def test_apply_copies_only_state_keys_with_original_ttls():
    source = FakeSource({
        b"rate_limit:42:search": (900, b"counter"),
        b"session:search:42": (1800000, b"session"),
        b"search_results_42_123": (0, b"already-expired"),
        b"search:doctor x": (45000, b"cache"),
        b"cache:search:version": (-1, b"version"),
    })
    dest = FakeDestination()
    count = transfer_state(source, dest, apply=True)

    assert count["copied"] == 3
    assert count["almost_expired"] == 1
    assert dest.records == {
        b"rate_limit:42:search": (900, b"counter"),
        b"session:search:42": (1800000, b"session"),
        b"cache:search:version": (0, b"version"),
    }
    assert not source.deleted


def test_migration_does_not_overwrite_destination_state():
    key = b"session:search:42"
    source = FakeSource({key: (30000, b"old")})
    dest = FakeDestination()
    dest.records[key] = (40000, b"new")

    count = transfer_state(source, dest, apply=True)
    assert count["already_exists"] == 1
    assert dest.records[key] == (40000, b"new")
    assert not dest.restores


def test_expiring_state_without_ttl_requires_manual_review():
    source = FakeSource({b"rate_limit:42:search": (-1, b"persistent")})
    with pytest.raises(RuntimeError, match="without a TTL"):
        transfer_state(source, FakeDestination(), apply=True)
