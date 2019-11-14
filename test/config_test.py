"""
Automated tests for all dialects.

Any files in the /tests/fixtures/parser directoy will be picked up
and automatically tested against the appropriate dialect.
"""

import os

from sqlfluff.config import ConfigLoader, nested_combine


config_a = {'core': {'testing_val': 'foobar', 'testing_int': 4}, 'bar': {'foo': 'barbar'}}


def test__config__nested_combine():
    a = {'a': {'b': {'c': 123, 'd': 456}}}
    b = {'b': {'b': {'c': 123, 'd': 456}}}
    c = {'a': {'b': {'c': 234, 'e': 456}}}
    r = nested_combine(a, b, c)
    assert r == {'a': {'b': {'c': 234, 'e': 456, 'd': 456}}, 'b': {'b': {'c': 123, 'd': 456}}}


def test__config__load_file_dir():
    c = ConfigLoader()
    cfg = c.load_config_at_path(os.path.join('test', 'fixtures', 'config'))
    assert cfg == config_a


def test__config__load_file_f():
    c = ConfigLoader()
    cfg = c.load_config_at_path(os.path.join('test', 'fixtures', 'config', 'testing.sql'))
    assert cfg == config_a


def test__config__load_nested():
    c = ConfigLoader()
    cfg = c.load_config_up_to_path(os.path.join('test', 'fixtures', 'config', 'nested', 'blah.sql'))
    assert cfg == {'core': {'testing_val': 'foobar', 'testing_int': 4}, 'bar': {'foo': 'foobar'}}
