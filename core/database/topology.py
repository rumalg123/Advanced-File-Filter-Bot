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
