"""A repeated URI must never drop or misalign its distinct database name."""
from types import SimpleNamespace

import pytest

from bot import BotConfig
from config.settings import DatabaseConfig
from core.database.topology import paired_database_sources


@pytest.mark.parametrize('uris,names,expected',[
    ([],[],[('mongodb://a','primary')]),
    (['mongodb://b'],[],[('mongodb://a','primary'),('mongodb://b','primary')]),
    (['mongodb://a','mongodb://b'],['primary','secondary'],[('mongodb://a','primary'),('mongodb://b','secondary')]),
    (['mongodb://a'],['other'],[('mongodb://a','primary'),('mongodb://a','other')]),
    (['mongodb://b','mongodb://b','mongodb://c'],['b','b','c'],[('mongodb://a','primary'),('mongodb://b','b'),('mongodb://c','c')]),
])
def test_pairing_deduplicates_exact_sources_and_preserves_names(uris,names,expected):
    assert paired_database_sources('mongodb://a','primary',uris,names)==expected


def test_extra_database_names_are_rejected_instead_of_silently_truncated():
    with pytest.raises(ValueError):paired_database_sources('mongodb://a','primary',[],['orphan'])


@pytest.mark.parametrize('uris,names,expected',[
    ('mongodb://a,mongodb://b','primary,secondary',[('mongodb://a','primary'),('mongodb://b','secondary')]),
    ('mongodb://a','other',[('mongodb://a','primary'),('mongodb://a','other')]),
])
def test_bot_configuration_keeps_uri_name_pairs_aligned(uris,names,expected):
    database=DatabaseConfig(_env_file=None,uri='mongodb://a',name='primary',uris=uris,names=names)
    config=object.__new__(BotConfig)
    config._settings=SimpleNamespace(database=database)
    config.DATABASE_URI=database.uri;config.DATABASE_NAME=database.name
    config.DATABASE_URIS=config._parse_database_uris()
    actual=list(zip(config.DATABASE_URIS,config._parse_database_names()))
    assert actual==expected
