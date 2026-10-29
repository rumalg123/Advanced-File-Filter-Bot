"""PH-016 authoritative media index declarations (no DDL on import).

Preserves the names, keys and material options declared by the old repository
and optimizer. Do not delete, rename, or add indexes based on this manifest
without measured query plans and an explicit approved migration.
"""

from typing import Any

# Entries are ordered to preserve the legacy repository's create-first order.
# The other four names previously came from IndexOptimizer.
_MEDIA_INDEXES = (
    ("text_search_idx", (("file_name", "text"), ("caption", "text")),
     {"default_language": "english"}),
    ("file_type_time_idx", (("file_type", 1), ("indexed_at", -1)), {}),
    ("size_index", (("file_size", 1),), {}),
    ("date_index", (("indexed_at", -1),), {}),
    ("file_ref_index", (("file_ref", 1),), {"unique": True, "sparse": True}),
    ("type_name_index", (("file_type", 1), ("file_name", 1)), {}),
    ("unique_file_id_idx", (("file_unique_id", 1),), {"unique": True}),
    ("season_episode_idx", (("season", 1), ("episode", 1)), {"sparse": True}),
    ("season_episode_resolution_idx",
     (("season", 1), ("episode", 1), ("resolution", 1)), {"sparse": True}),
    ("resolution_idx", (("resolution", 1),), {"sparse": True}),
    ("resolution_type_idx", (("resolution", 1), ("file_type", 1)), {"sparse": True}),
    ("episode_idx", (("episode", 1),), {"sparse": True}),
    ("file_type_size_idx", (("file_type", 1), ("file_size", -1)), {}),
    ("channel_time_idx", (("channel_id", 1), ("indexed_at", -1)), {}),
    ("cleanup_time_idx", (("indexed_at", 1),), {}),
    ("resolution_date_idx", (("resolution", 1), ("indexed_at", -1)),
     {"sparse": True}),
)

# Only material fields are relevant for drift. The historical "background"
# option was passed on one path but does not define index key semantics.
MATERIAL_INDEX_OPTIONS = (
    "unique", "sparse", "default_language", "language_override",
    "partialFilterExpression", "expireAfterSeconds", "collation", "wildcardProjection",
    "weights", "hidden",
)


def media_index_manifest() -> list[dict[str, Any]]:
    """Return defensive copies; callers cannot mutate the manifest."""
    return [
        {"name": name, "keys": list(keys), "options": dict(options)}
        for name, keys, options in _MEDIA_INDEXES
    ]


def index_definition(index: dict[str, Any]) -> dict[str, Any]:
    """Normalize index specs to comparable, non-secret material metadata."""
    keys = index.get("keys", index.get("key", []))
    if isinstance(keys, dict):
        keys = list(keys.items())
    options = index.get("options", index)
    # MongoDB rewrites a text index's reported key to _fts/_ftsx and
    # retains the original indexed fields in its weights map.
    if keys == [("_fts", "text"), ("_ftsx", 1)]:
        weights = options.get("weights", {})
        keys = [(field, "text") for field in sorted(weights)]
    if any(kind == "text" for _, kind in keys):
        keys = sorted(keys, key=lambda pair: pair[0])
    # Do not expose fields outside the approved index spec metadata.
    material = {
        k: options[k] for k in MATERIAL_INDEX_OPTIONS if k in options
    }
    return {"keys": [list(pair) for pair in keys], "options": material}


def compare_index_definition(
    expected: dict[str, Any], observed: dict[str, Any]
) -> bool:
    """Ignore defaults but reject material differences and extra options.

    MongoDB stores default text options (language_override and weights) even
    when not explicitly provided; normalize these documented defaults.
    """
    a, z = index_definition(expected), index_definition(observed)
    if a["keys"] != z["keys"]:
        return False
    eo, oo = a["options"], z["options"]
    # These implicit values are safe to ignore only when default-valued.
    defaults = {
        "unique": False, "sparse": False, "hidden": False,
        "default_language": "english", "language_override": "language",
    }
    for option in MATERIAL_INDEX_OPTIONS:
        if option == "weights" and a["keys"] and any(v == "text" for _, v in a["keys"]):
            # Server-generated text index weights default to one per field.
            if option not in eo and oo.get(option) == {
                field: 1 for field, kind in a["keys"] if kind == "text"
            }:
                continue
        left = eo.get(option, defaults.get(option))
        right = oo.get(option, defaults.get(option))
        if left != right:
            return False
    return True
