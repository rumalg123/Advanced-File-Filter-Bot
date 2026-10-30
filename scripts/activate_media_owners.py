#!/usr/bin/env python3
"""Read-only ownership inventory by default; explicit bounded activation.

Supply DATABASE_URI/NAME and optional DATABASE_URIS/NAMES privately in the
environment, as for the bot. Alternatively MEDIA_OWNER_SOURCES_JSON accepts an
array of {uri, name} objects (useful for seed-list URIs). Stop every writer before
--apply. Failed activation resumes only with the same --activation-token.
"""
import argparse
import asyncio
import json
import os
from types import SimpleNamespace

from motor.motor_asyncio import AsyncIOMotorClient
from core.database.media_owners import GlobalMediaOwners
from scripts.profile_media_search import is_local


def source_configuration():
    raw = os.environ.get('MEDIA_OWNER_SOURCES_JSON')
    if raw:
        sources = json.loads(raw)
    else:
        uris = [os.environ.get('DATABASE_URI', '')] + [s.strip() for s in os.environ.get('DATABASE_URIS', '').split(',') if s.strip()]
        names = [os.environ.get('DATABASE_NAME', '')] + [s.strip() for s in os.environ.get('DATABASE_NAMES', '').split(',') if s.strip()]
        if len(uris) != len(names):
            raise ValueError('Database URI/name counts must match')
        sources = [dict(uri=uri, name=name) for uri, name in zip(uris, names)]
    if not isinstance(sources, list) or not 1 <= len(sources) <= 32:
        raise ValueError('Configure 1..32 media sources')
    if any(not isinstance(s, dict) or not isinstance(s.get('uri'), str) or not s['uri']
           or not isinstance(s.get('name'), str) or not s['name'] for s in sources):
        raise ValueError('Each source requires a URI and database name')
    return sources


async def operate(sources, args):
    clients, databases = [], []
    try:
        for source in sources:
            client = AsyncIOMotorClient(source['uri'], serverSelectionTimeoutMS=10000,
                                       connectTimeoutMS=10000, socketTimeoutMS=30000)
            clients.append(client)
            db = client[source['name']]
            class Pool:
                def __init__(self, database): self.database = database
                async def get_collection(self, name): return self.database[name]
            databases.append(SimpleNamespace(**source, pool=Pool(db), is_active=True))
        owners = GlobalMediaOwners(databases)
        if args.status:
            await owners.attach()
            return {'ready': True, 'sources': len(sources)}
        if args.apply:
            return await owners.activate(args.activation_token, max_docs_per_source=args.limit)
        return await owners.inventory(max_docs_per_source=args.limit)
    finally:
        for client in clients:
            client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--status', action='store_true')
    parser.add_argument('--allow-remote', action='store_true')
    parser.add_argument('--activation-token')
    parser.add_argument('--limit', type=int, default=10000000)
    args = parser.parse_args()
    if args.apply and not args.activation_token:
        parser.error('--apply requires an explicit --activation-token and stopped writers')
    if not 1 <= args.limit <= 10000000:
        parser.error('--limit must be 1..10000000')
    try:
        sources = source_configuration()
        if args.apply and len(sources) < 2:
            parser.error('Media ownership activation requires at least two sources')
        if not args.allow_remote and any(not is_local(s['uri']) for s in sources):
            parser.error('Remote ownership operations require --allow-remote')
        result = asyncio.run(operate(sources, args))
        print(json.dumps(result, sort_keys=True))
        if result.get('eligible') is False:
            raise SystemExit(2)
    except Exception as e:
        parser.exit(1, f'Ownership operation failed; activation remains locked if incomplete. Inspect network, inventory conflicts and configuration without logging secrets {e}.\n')


if __name__ == '__main__':
    main()
