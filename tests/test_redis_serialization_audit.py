"""PH-009: read-only legacy Redis inventory safely inspects prefixes only."""
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import Mock

from scripts.audit_redis_serialization import classify, inventory


def test_prefix_classification_cannot_decode_or_invoke_pickle():
    assert classify(b"p\x80") == "possibly_pickle_tagged"
    assert classify(b"cp") == "possibly_pickle_tagged"
    assert classify(b"\x80\x05") == "possibly_untagged_binary_pickle"
    assert classify(b"cj") == "compressed_safe_tagged"
    assert classify(b"cm") == "compressed_safe_tagged"
    assert classify(b"j{") == "safe_tagged_or_ambiguous_plaintext"
    assert classify(b"m\x82") == "safe_tagged_or_ambiguous_plaintext"
    assert classify(b"XY") == "untagged_or_other"


def test_inventory_reads_only_metadata_and_never_exposes_key_names():
    samples = OrderedDict([
        (b"session:secret-user-id", (b"p\x80", -1, b"string")),
        (b"search:private-title", (b"cm", 45_000, b"string")),
        (b"counter:long", (b"", -1, b"int")),
        (b"session:legacy-protocol", (b"\x80\x04", 3_000, b"string")),
    ])
    client = SimpleNamespace(
        scan=Mock(return_value=(0, list(samples))),
        type=Mock(side_effect=lambda k: samples[k][2]),
        getrange=Mock(side_effect=lambda k, start, end: samples[k][0]),
        pttl=Mock(side_effect=lambda k: samples[k][1]),
        get=Mock(side_effect=AssertionError("No full Redis values allowed")),
        delete=Mock(side_effect=AssertionError("Read-only scan")),
        set=Mock(side_effect=AssertionError("Read-only scan")),
    )

    result = inventory(client, max_keys=20)
    assert result["scanned_keys"] == 4
    assert result["scan_completed"] is True
    assert result["read_only"] is True
    counts = result["approximate_counts"]
    assert counts["possibly_pickle_tagged"] == 1
    assert counts["possibly_untagged_binary_pickle"] == 1
    assert counts["compressed_safe_tagged"] == 1
    assert counts["non_string_keys"] == 1
    assert counts["string_keys_without_ttl"] == 1
    assert counts["string_keys_with_ttl"] == 2
    assert "secret-user-id" not in str(result)
    assert "private-title" not in str(result)
    assert client.getrange.call_count == 3
    client.get.assert_not_called()
    client.delete.assert_not_called()
    client.set.assert_not_called()
