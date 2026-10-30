#!/usr/bin/env python3
"""PH-006: bounded, optimistic search-token backfill for explicitly chosen MongoDB.

Without --apply this reports missing/outdated metadata without writing anything.
Remote targets require --allow-remote. No credentials or document values print.
"""
import argparse
import json
import os
from pymongo import MongoClient, UpdateOne
from core.utils.search_tokens import (media_search_tokens, SEARCH_TOKEN_FIELD,
    SEARCH_TOKEN_VERSION_FIELD, SEARCH_TOKEN_VERSION)
from scripts.profile_media_search import is_local


def backfill(collection, *, apply=False, rollback=False, batch_size=200, limit=100000):
    if not 1 <= batch_size <= 1000 or not 1 <= limit <= 1000000:
        raise ValueError('Invalid backfill bounds')
    stats = {'scanned': 0, 'needs_update': 0, 'matched': 0, 'modified': 0, 'truncated': False}
    operations = []
    def flush():
        if operations:
            result = collection.bulk_write(operations, ordered=False)
            stats['matched'] += result.matched_count
            stats['modified'] += result.modified_count
            operations.clear()
    projection = {'file_name': 1, 'caption': 1, SEARCH_TOKEN_FIELD: 1, SEARCH_TOKEN_VERSION_FIELD: 1}
    for doc in collection.find({}, projection).batch_size(batch_size).limit(limit + 1):
        if stats['scanned'] >= limit:
            stats['truncated'] = True
            break
        stats['scanned'] += 1
        if rollback:
            changed = SEARCH_TOKEN_FIELD in doc or SEARCH_TOKEN_VERSION_FIELD in doc
            update = {'$unset': {SEARCH_TOKEN_FIELD: '', SEARCH_TOKEN_VERSION_FIELD: ''}}
        else:
            terms = media_search_tokens(doc.get('file_name'), doc.get('caption'))
            changed = doc.get(SEARCH_TOKEN_FIELD) != terms or doc.get(SEARCH_TOKEN_VERSION_FIELD) != SEARCH_TOKEN_VERSION
            update = {'$set': {SEARCH_TOKEN_FIELD: terms, SEARCH_TOKEN_VERSION_FIELD: SEARCH_TOKEN_VERSION}}
        if not changed:
            continue
        stats['needs_update'] += 1
        if apply:
            # Do not tag a document with tokens computed before a concurrent edit.
            # Plain array equality also matches a nested array element in
            # MongoDB. Compare exact source values to avoid tagging a changed
            # legacy array with tokens from its earlier, smaller value.
            query = {'_id': doc['_id'], '$expr': {'$and': [
                {'$eq': [{'$ifNull': ['$' + field, None]},
                         {'$literal': doc.get(field)}]}
                for field in ('file_name', 'caption')
            ]}}
            operations.append(UpdateOne(query, update))
            if len(operations) >= batch_size:
                flush()
    flush()
    stats['mode'] = 'rollback' if rollback else 'backfill'
    stats['applied'] = apply
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rollback', action='store_true')
    parser.add_argument('--allow-remote', action='store_true')
    parser.add_argument('--batch-size', type=int, default=200)
    parser.add_argument('--limit', type=int, default=100000)
    args = parser.parse_args()
    uri, name = os.environ.get('DATABASE_URI'), os.environ.get('DATABASE_NAME')
    if not uri or not name:
        parser.error('DATABASE_URI and DATABASE_NAME must be supplied')
    if not args.allow_remote and not is_local(uri):
        parser.error('Remote backfill requires --allow-remote')
    try:
        with MongoClient(uri, serverSelectionTimeoutMS=10000) as client:
            result = backfill(client[name].media_files, apply=args.apply,
                rollback=args.rollback, batch_size=args.batch_size, limit=args.limit)
        print(json.dumps(result, sort_keys=True))
    except Exception as e:
        parser.exit(1, f'Search-token operation failed; inspect network/permissions without logging credentials {e}.\n')


if __name__ == '__main__':
    main()
