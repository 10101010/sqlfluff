""" The Test file for SQLFluff """

from sqlfluff.rules.base import BaseRule, BaseRuleSet, RuleViolation
from sqlfluff.chunks import PositionedChunk, ChunkString


# ############## BASE RULES TESTS
def test__rules__base__baserule_a():
    r = BaseRule('A', 'DESC', lambda x: True)
    assert isinstance(r.evaluate(None), RuleViolation)


def test__rules__base__baserule_b():
    r = BaseRule('A', 'DESC', lambda x: x % 6 == 0)
    assert isinstance(r.evaluate(36), RuleViolation)
    assert r.evaluate(36).chunk == 36
    assert r.evaluate(36).rule is r
    assert r.evaluate(37) is None


def test__rules__base__ruleset():
    rs = BaseRuleSet(
        BaseRule('A', 'foo', lambda x: True),
        BaseRule('B', 'bar', lambda x: False)
    )
    vs = rs.evaluate(1)
    assert len(vs) == 1
    assert vs[0].rule.code == 'A'


def test__rules__base__ruleset_chunkstring():
    """ An extension of the above test, but applied to a chunkstring """
    rs = BaseRuleSet(
        BaseRule('A', 'foo', lambda x: True),
        BaseRule('B', 'bar', lambda x: False)
    )
    cs = ChunkString(
        PositionedChunk('foo', 1, 20, 'a'),
        PositionedChunk('bar', 1, 21, 'b')
    )
    vs = rs.evaluate_chunkstring(cs)
    # We should get two instances of rule A
    assert len(vs) == 2
    assert vs[0].rule.code == 'A'
    assert vs[0].chunk.chunk == 'foo'
    assert vs[1].rule.code == 'A'
    assert vs[1].chunk.chunk == 'bar'
