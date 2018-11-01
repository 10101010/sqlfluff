""" The Test file for SQLFluff """

import pytest
import io
from sqlfluff import CharMatchPattern, RegexMatchPattern, MatcherBag, RecursiveLexer, PositionedChunk, ChunkString


# ############## Chunks
def test__chunk__split():
    c = PositionedChunk('foobarbar', 10, 20, None)
    a, b = c.split_at(3)
    assert a == PositionedChunk('foo', 10, 20, None)
    assert b == PositionedChunk('barbar', 13, 20, None)


def test__chunk__split_context_error():
    c = PositionedChunk('foobarbar', 10, 20, 'context')
    with pytest.raises(RuntimeError):
        c.split_at(4)


def test__chunk__subchunk():
    c = PositionedChunk('foobarbar', 10, 20, None)
    r = c.subchunk(3, 6)
    assert r == PositionedChunk('bar', 13, 20, None)


# ############## Matchers
def test__charmatch__basic_1():
    cmp = CharMatchPattern('s', None)
    s = 'aefalfuinsefuynlsfa'
    assert cmp.first_match_pos(s) == 9


def test__charmatch__none():
    cmp = CharMatchPattern('s', None)
    s = 'aefalfuin^efuynl*fa'
    assert cmp.first_match_pos(s) is None


def test__charmatch__span():
    cmp = CharMatchPattern('"', None)
    s = 'aefal "fuin^ef" uynl*fa'
    assert cmp.span(s) == (6, 15)


def test__charmatch__chunkmatch_1():
    cmp = CharMatchPattern('"', None)
    chk = PositionedChunk('aefal "fuin^ef" uynl*fa', 13, 20, None)
    sub_chunk = cmp.chunkmatch(chk)
    assert sub_chunk is not None
    assert sub_chunk == PositionedChunk('"fuin^ef"', 13 + 6, 20, 'match')


def test__charmatch__chunkmatch_2():
    cmp = CharMatchPattern('a', 'foo')
    chk = PositionedChunk('asdfbjkebkjaekljds', 13, 20, None)
    sub_chunk = cmp.chunkmatch(chk)
    assert sub_chunk == PositionedChunk('asdfbjkebkja', 13, 20, 'match')


def test__charmatch__chunkmatch_3():
    # Check for an no match scenario
    cmp = CharMatchPattern('a', None)
    chk = PositionedChunk('sdflkg;j;d;sflkgjds', 13, 20, None)
    sub_chunk = cmp.chunkmatch(chk)
    assert sub_chunk is None


def test__regexmatch__span():
    cmp = RegexMatchPattern(r'"[a-z]+"', None)
    s = 'aefal "fuinef" uynl*fa'
    assert cmp.span(s) == (6, 14)


# ############## Matcher Bag
def test__matcherbag__unique():
    # raise an error that are duplicate names
    with pytest.raises(AssertionError):
        MatcherBag(CharMatchPattern('"', 'foo'), CharMatchPattern('"', 'foo'))


def test__matcherbag__add_unique():
    # raise an error that are duplicate names
    with pytest.raises(AssertionError):
        MatcherBag(CharMatchPattern('"', 'foo')) + MatcherBag(CharMatchPattern('"', 'foo'))


def test__matcherbag__add_bag():
    # check we can make a bag out of another bag
    bag = MatcherBag(CharMatchPattern('a', 'foo'), MatcherBag(CharMatchPattern('b', 'bar')))
    bag2 = MatcherBag(bag, CharMatchPattern('c', 'bim'))
    assert len(bag2) == 3


def test__matcherbag__chunkmatch_a():
    a = CharMatchPattern('a', 'foo')
    b = CharMatchPattern('b', 'bar')
    m = MatcherBag(a, b)
    chk = PositionedChunk('asdfbjkebkjaekljds', 13, 20, None)
    matches = m.chunkmatch(chk)
    assert len(matches) == 2
    assert matches == [
        (PositionedChunk('asdfbjkebkja', 13, 20, 'match'), 0, a),
        (PositionedChunk('bjkeb', 13 + 4, 20, 'match'), 4, b)]


def test__matcherbag__chunkmatch_b():
    """ A more complicated matcher test, explicitly testing sorting """
    k = CharMatchPattern('k', 'bim')
    b = CharMatchPattern('b', 'bar')
    a = CharMatchPattern('a', 'foo')
    r = RegexMatchPattern(r'e[a-z][a-df-z]+e[a-z]', 'eee')
    m = MatcherBag(k, b, a, r)
    chk = PositionedChunk('asdfbjkebkjaekljds', 11, 2, None)
    matches = m.chunkmatch(chk)
    assert matches == [
        (PositionedChunk('asdfbjkebkja', 11, 2, 'match'), 0, a),
        (PositionedChunk('bjkeb', 11 + 4, 2, 'match'), 4, b),
        (PositionedChunk('kebk', 11 + 6, 2, 'match'), 6, k),
        (PositionedChunk('ebkjaek', 11 + 7, 2, 'match'), 7, r)]


# ############## LEXER TESTS
def test__recursive__basic_1():
    rl = RecursiveLexer()
    pc = PositionedChunk('   ', 0, 1, None)
    res, context = rl.lex(pc)
    assert isinstance(res, ChunkString)
    assert len(res) == 1
    assert res[0].chunk == '   '


def test__recursive__basic_2():
    rl = RecursiveLexer()
    pc = PositionedChunk('SELECT\n', 0, 1, None)
    res, context = rl.lex(pc)
    assert isinstance(res, ChunkString)
    assert len(res) == 2
    assert res[0].chunk == 'SELECT'


def test__recursive__multi_whitespace_a():
    rl = RecursiveLexer()
    pc = PositionedChunk('    SELECT    \n', 0, 1, None)
    res, context = rl.lex(pc)
    assert isinstance(res, ChunkString)
    assert len(res) == 3
    assert res[0].context == 'whitespace'
    assert res[1].chunk == 'SELECT'


def test__recursive__multi_whitespace_b():
    # This test requires recursion
    rl = RecursiveLexer()
    pc = PositionedChunk('    SELECT   foo    \n', 0, 1, None)
    res, context = rl.lex(pc)
    assert isinstance(res, ChunkString)
    assert len(res) == 5
    assert res[0].context == 'whitespace'
    assert res[1].chunk == 'SELECT'
    assert res[3].chunk == 'foo'
    assert res[3].start_pos == 13


def test__recursive__comment_a():
    # This test requires recursion
    rl = RecursiveLexer()
    # The whitespace on the end of a comment should be it's own chunk
    pc = PositionedChunk('SELECT    -- Testing Comment\n', 0, 1, None)
    res, context = rl.lex(pc)
    assert res.context_list() == ['content', 'whitespace', 'comment', 'whitespace']
    assert res[3].chunk == '\n'


def test__recursive__lex_chunk_buffer():
    # This test requires recursion
    rl = RecursiveLexer()
    # The whitespace on the end of a comment should be it's own chunk
    pc_list = [PositionedChunk('SELECT\n', 0, 1, None), PositionedChunk('NOTHING\n', 0, 2, None)]
    res, context = rl.lex_chunk_buffer(pc_list)
    assert res.context_list() == ['content', 'whitespace', 'content', 'whitespace']
    assert res[1].chunk == '\n'
    assert res[3].chunk == '\n'


def test__recursive__lex_file():
    # Test iterating through a file-like object
    rl = RecursiveLexer()
    f = io.StringIO("Select\n   *\nFROM tbl\n")
    res = rl.lex_file_obj(f)
    assert res.string_list() == ['Select', '\n', '   ', '*', '\n', 'FROM', ' ', 'tbl', '\n']
    assert res.context_list() == [
        'content', 'whitespace', 'whitespace', 'content',
        'whitespace', 'content', 'whitespace', 'content',
        'whitespace']
