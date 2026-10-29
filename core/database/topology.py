"""Keep database URI/name pairs together when normalizing configuration."""


def paired_database_sources(primary_uri, primary_name, additional_uris, additional_names):
    if len(additional_names) > len(additional_uris):
        raise ValueError('More database names than additional URIs')
    pairs = [(primary_uri, primary_name)]
    for index, uri in enumerate(additional_uris):
        name = additional_names[index] if index < len(additional_names) else primary_name
        pair = (uri, name)
        if pair not in pairs:
            pairs.append(pair)
    return pairs


def validated_database_sources(database_config):
    """Validate distinct source identities without DNS lookups or connections."""
    from pymongo import MongoClient
    from core.database.media_owners import source_key

    try:
        sources = database_config.get_sources()
        if not 1 <= len(sources) <= 32:
            raise ValueError('Invalid source count')
        identities = set()
        for uri, name in sources:
            # connect=False also defers SRV resolution. Indexing the client only
            # validates the database name; it does not read a remote database.
            with MongoClient(uri, connect=False) as client:
                client[name]
            identity = source_key(uri, name)
            if identity in identities:
                raise ValueError('Repeated source identity')
            identities.add(identity)
        return sources
    except Exception:
        # Driver validation errors may include credential-bearing URIs.
        raise ValueError('Configure distinct valid MongoDB URI/database pairs in the environment.') from None
