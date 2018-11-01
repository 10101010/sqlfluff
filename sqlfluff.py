""" The Main file for SQLFluff """

import click
# import os
import re
from collections import namedtuple, OrderedDict


def ordinalise(s):
    return [ord(c) for c in s]


# chunks should be immutable, they are a subclass of namedtuple (context defaults to None)
class PositionedChunk(namedtuple('ProtoChunk', ['chunk', 'start_pos', 'line_no', 'context'])):
    def __repr__(self):
        # We introspect the class to make this more generic
        return "<{class_type} @(L:{line_no},P:{start_pos},C:{context}) {chunk!r}>".format(
            class_type=self.__class__.__name__, **self.__dict__)

    def __len__(self):
        return len(self.chunk)

    def contextualise(self, context):
        # Return a copy, just with the context set
        return PositionedChunk(self.chunk, self.start_pos, self.line_no, context=context)

    def split_at(self, pos):
        if self.context:
            raise RuntimeError("Attempting to split a chunk which already has context!")
        if pos <= 0 or pos > len(self):
            raise RuntimeError("Trying to split at wrong index: {pos}".format(pos=pos))
        return (
            PositionedChunk(self.chunk[:pos], self.start_pos, self.line_no, None),
            PositionedChunk(self.chunk[pos:], self.start_pos + pos, self.line_no, None))
    
    def subchunk(self, start, end=None, context=None):
        if end:
            return PositionedChunk(
                self.chunk[start: end], self.start_pos + start,
                self.line_no, context=context or self.context)
        else:
            return PositionedChunk(
                self.chunk[start:], self.start_pos + start,
                self.line_no, context=context or self.context)


class ChunkString(object):
    def __init__(self, *args):
        assert all([isinstance(elem, PositionedChunk) for elem in args])
        self.chunk_list = list(args)

    def __add__(self, other):
        return ChunkString(*self.chunk_list, *other.chunk_list)

    def __getitem__(self, key):
        return self.chunk_list[key]

    def __len__(self):
        return len(self.chunk_list)

    def content_list(self):
        return [elem.content for elem in self.chunk_list]


class CharMatchPattern(object):
    """ Intended for things like quote characters """
    def __init__(self, c, name):
        self._char = c
        self.name = name

    def first_match_pos(self, s):
        # Assume s is a string
        for idx, c in enumerate(s):
            if c == self._char:
                return idx
        else:
            return None

    def span(self, s):
        # SPAN should return the index from and to of the match
        # a single character match will have a difference of span
        # equal to 1.
        first = self.first_match_pos(s)
        # check that we're not matching in the last position
        # (otherwise we can't add one to it)
        if first < len(s):
            # Look or the next match after this
            second = self.first_match_pos(s[first + 1:])
            if second:
                # we add one here because we add it above
                return first, second + 2 + first
        # unless both first AND second match, then return here
        return first, None
    
    def chunkmatch(self, c):
        """ Given a full chunk, rather than just a string, return the first matching subchunk """
        span = self.span(c.chunk)
        if span[0]:
            # there's a start!
            if span[1]:
                # there's a defined end!
                return c.subchunk(start=span[0], end=span[1], context='match')
            else:
                # start but no end
                return c.subchunk(start=span[0], context='match')
        else:
            return None


class RegexMatchPattern(CharMatchPattern):
    def __init__(self, r, name):
        self._pattern = re.compile(r)
        self.name = name

    def span(self, s):
        # Assume s is a string
        m = self._pattern.search(s)
        if m:
            return m.span()
        else:
            return None, None

    def first_match_pos(self, s):
        span = self.span(s)
        return span[0]


class MatcherBag(object):
    def __init__(self, *matchers):
        # Check that names are unique
        assert len(matchers) == len(set([elem.name for elem in matchers]))
        # store them as a dict, so we can do lookups
        self._matchers = {elem.name: elem for elem in matchers}
    
    def __add__(self, other):
        # combining bags is just like making a bag with the combination of the matchers.
        # there will be a uniqueness check in this operation
        return MatcherBag(*self._matchers.values(), *other._matchers.values())


class AnsiSQLDialiect(object):
    patterns = {
        'whitespace'

    }
    # Whitespace is what divides other bits of syntax
    whitespace_regex = re.compile(r'\s+')
    # Anything after an inline comment gets chunked together as not code
    inline_comment_regex = re.compile(r'--|#')
    # Anything between the first and last part of this tuple counts as not code
    block_comment_regex_tuple = (re.compile(r'/\*'), re.compile(r'\*/'))
    # String Quote Characters
    string_quote_characters = ("'",)  # NB in Mysql this should also include "
    # Identifier Quote Characters
    identifier_quote_characters = ('"',)  # NB in Mysql this should be `


LexerContext = namedtuple('LexerContext', ['dialect', 'multiline_comment_active'])


class RecursiveLexer(object):
    def __init__(self, dialect=AnsiSQLDialiect):
        self.dialect = dialect

    def lex(self, chunk, **start_context):
        # scan the chunk for whitespace
        first_whitespace = self.dialect.whitespace_regex.search(chunk.chunk)
        first_single_comment = self.dialect.inline_comment_regex.search(chunk.chunk)
        first_block_comment_start = self.dialect.block_comment_regex_tuple[0].search(chunk.chunk)
        first_block_comment_end = self.dialect.block_comment_regex_tuple[0].search(chunk.chunk)
        if first_whitespace:
            match_start, match_end = first_whitespace.span()
            if match_start == 0:
                # Whitespace at the start
                if match_end == len(chunk):
                    # All whitespace
                    return ChunkString(chunk.contextualise('whitespace')), start_context
                else:
                    # Some content after the whitespace
                    white_chunk, remainder_chunk = chunk.split_at(match_end)
                    remainder_string, end_context = self.lex(remainder_chunk, **start_context)
                    return ChunkString(white_chunk.contextualise('whitespace')) + remainder_string, end_context
            else:
                # White space after some content
                if match_end == len(chunk):
                    # Whitespace to the end
                    remainder_chunk, white_chunk = chunk.split_at(match_start)
                    remainder_string, end_context = self.lex(remainder_chunk, **start_context)
                    # NB whitespacec shouldn't change context so we'll assume that whatever context is left
                    # at the end of the remainder is what should persist
                    return remainder_string + ChunkString(white_chunk.contextualise('whitespace')), end_context
                else:
                    # Content at the start, then some whitespace, then more content
                    content_chunk, remainder_chunk = chunk.split_at(match_start)
                    content_chunk = content_chunk.contextualise('content')
                    white_chunk, remainder_chunk = remainder_chunk.split_at(match_end - len(content_chunk))
                    remainder_string, end_context = self.lex(remainder_chunk, **start_context)
                    return ChunkString(content_chunk, white_chunk.contextualise('whitespace')) + remainder_string, end_context
        else:
            # No whitespace, all content
            return ChunkString(chunk.contextualise('content')), start_context


def recursive_lexer(chunk, context):
    click.echo("Parsing: {chunk!r}".format(chunk=chunk))
    if context.multiline_comment_active:
        # if there's a comment in progress, then it's all comment unless we find the end
        multi_comment_match = context.dialect.block_comment_regex_tuple[1].search(chunk.chunk)
        if multi_comment_match:
            match_start, match_end = m.span()
            click.echo("Found end of block comment")
        else:
            chunk.set_content('comment')
            return ChunkString(chunk), context
    else:
        # Any comments starting
        single_comment_match = context.dialect.inline_comment_regex.search(chunk.chunk)
        multi_comment_match = context.dialect.block_comment_regex_tuple[0].search(chunk.chunk)
        if single_comment_match and multi_comment_match:
            # both!? - we need to work out which first
            pass
        elif single_comment_match:
            # if there's a single line comment, then it takes all of the rest of the line
            if single_comment_match.pos > 0:
                code_chunk, comment_chunk = chunk.split_at(single_comment_match.pos)
                comment_chunk.set_content('comment')
                substr = recursive_lexer(code_chunk, context)
                return substr + ChunkString(comment_chunk), context
            else:
                chunk.set_content('comment')
                return ChunkString(chunk), context
        elif multi_comment_match:
            # if there's a single line comment, then it takes all of the rest of the line
            if multi_comment_match.pos > 0:
                first_chunk, second_chunk = chunk.split_at(multi_comment_match.pos)
                comment_chunk.set_content('comment')
                substr = recursive_lexer(code_chunk, context)
                return substr + ChunkString(comment_chunk), context
            else:
                chunk.set_content('comment')
                return ChunkString(chunk), context

        # THIS NEEDS TO CHANGE
        return ChunkString(chunk), context


def parse_file(file_obj, dialect=AnsiSQLDialiect):
    """ Take a file like oject and parse it into chunks """
    # Create some variables to hold context between lines
    multi_line_comment_active = False
    string_buffer = None
    chunk_buffer = []
    # initialise the context
    context = LexerContext(dialect=dialect, multiline_comment_active=False)
    for idx, line in enumerate(file_obj, start=1):
        line_chunk = PositionedChunk(line, 0, idx)
        # context carries on
        chunks, context = recursive_lexer(line_chunk, context)


class ParsedLine(object):
    def __init__(self, line, line_no, dialect=AnsiSQLDialiect):
        self.initial_chunk = None
        self.terminal_chunk = None
        self.core_chunk = None
        # click.echo(len(line))
        # Iterate through whitespace matches
        for m in dialect.whitespace_regex.finditer(line):
            if m:
                # click.echo(m)
                # click.echo(repr(m.group()))
                match_start, match_end = m.span()
                if match_start == 0:
                    # click.echo("Initial String")
                    self.initial_chunk = PositionedChunk(m.group(), match_start, line_no)
                elif match_end == len(line):
                    # click.echo("Terminal Match")
                    self.terminal_chunk = PositionedChunk(m.group(), match_start, line_no)
        central_start = len(self.initial_chunk or '')
        central_end = len(line) - len(self.terminal_chunk or '')
        central_chunk = line[central_start: central_end]
        self.core_chunk = PositionedChunk(central_chunk, central_start, line_no)
        # click.echo(self.core_chunk)

    def __repr__(self):
        return '<Parsed Line - Core:%r, Initial=%r, Terminal=%r>' % (self.core_chunk, self.initial_chunk, self.terminal_chunk)


@click.command()
@click.option('--dialect', default='ansi', help='The dialect of SQL to lint')
@click.argument('paths', nargs=-1)
def sqlfluff_lint(dialect, paths):
    """Lint SQL files"""
    click.echo('Linting... [Dialect: {0}]'.format(dialect))
    click.echo(paths)
    if len(paths) == 0:
        # No paths specified - assume local
        paths = ('.',)
    for path in paths:
        click.echo('Linting: {0}'.format(path))
        # Iterate through files recursively in the specified directory (if it's a directory)
        # or read the file directly if it's not
    click.echo("Loading the example file...")
    for fname in ['example.sql', 'example-tab.sql']:
        click.echo(fname)
        with open(fname) as f:
            parse_file(f)


if __name__ == '__main__':
    sqlfluff_lint()
