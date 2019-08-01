
import logging

from .segments_base import (BaseSegment, RawSegment)
from .grammar import (Sequence, GreedyUntil, StartsWith, ContainsOnly, OneOf)

# NOTE: There is a concept here, of parallel grammars.
# We use one (slightly more permissive) grammar to MATCH
# and then a more detailed one to PARSE. One is called first,
# then the other - which allows sections of the file to be
# parsed even when others won't.

# Multi stage parser

# First strip comments, potentially extracting special comments (which start with sqlfluff:)
#   - this also makes comment sections, config sections (a subset of comments) and code sections

# Note on SQL Grammar
# https://www.cockroachlabs.com/docs/stable/sql-grammar.html#select_stmt


class KeywordSegment(RawSegment):
    """ The Keyword Segment is a bit special, because while it
    can be instantiated directly, we mostly generate them on the
    fly for convenience """

    type = 'keyword'
    is_code = True
    _template = '<unset>'
    _case_sensitive = False

    @classmethod
    def match(cls, segments):
        """ Keyword implements it's own matching function """
        # If we've been passed the singular, make it a list
        if isinstance(segments, BaseSegment):
            segments = [segments]
        # We only match if it's of length 1, otherwise not
        if len(segments) == 1:
            raw = segments[0].raw
            pos = segments[0].pos_marker
            logging.warning(raw)
            if ((cls._case_sensitive and cls._template == raw) or (not cls._case_sensitive and cls._template == raw.upper())):
                return cls(raw=raw, pos_marker=pos)
        else:
            logging.warning("Keyword will not match sequence of length {0}".format(len(segments)))
        return None

    @classmethod
    def make(cls, template, case_sensitive=False):
        # Let's deal with the template first
        if case_sensitive:
            _template = template
        else:
            _template = template.upper()
        # Now lets make the classname (it indicates the mother class for clarity)
        classname = "{0}_{1}".format(_template, cls.__name__)
        # This is the magic, we generate a new class! SORCERY
        newclass = type(classname, (cls, ),
                        dict(_template=_template, _case_sensitive=case_sensitive))
        # Now we return that class in the abstract. NOT INSTANTIATED
        return newclass


class StatementSeperatorSegment(KeywordSegment):
    type = 'statement_seperator'
    _template = ';'


class SelectTargetGroupStatementSegment(BaseSegment):
    type = 'select_target_group'
    # From here down, comments are printed seperately.
    comment_seperate = True
    # match grammar - doesn't exist - don't match, only parse
    grammar = None
    parse_grammar = Sequence(GreedyUntil(KeywordSegment.make('from')))


class SelectStatementSegment(BaseSegment):
    type = 'select_statement'
    # From here down, comments are printed seperately.
    comment_seperate = True
    # match grammar
    grammar = StartsWith(KeywordSegment.make('select'))
    parse_grammar = Sequence(KeywordSegment.make('select'), SelectTargetGroupStatementSegment, GreedyUntil(KeywordSegment.make('limit')))


class InsertStatementSegment(BaseSegment):
    type = 'insert_statement'
    # From here down, comments are printed seperately.
    comment_seperate = True
    grammar = StartsWith(KeywordSegment.make('insert'))


class EmptyStatementSegment(BaseSegment):
    type = 'empty_statement'
    # From here down, comments are printed seperately.
    comment_seperate = True
    grammar = ContainsOnly('comment', 'newline')
    # TODO: At some point - we should lint that these are only
    # allowed at the END - otherwise it's probably a parsing error


class StatementSegment(BaseSegment):
    type = 'statement'
    # From here down, comments are printed seperately.
    comment_seperate = True
    # Let's define a grammar from here on in
    grammar = OneOf(SelectStatementSegment, InsertStatementSegment, EmptyStatementSegment)


class RawCodeSegment(RawSegment):
    type = 'rawcode'

    def parse(self):
        # Split into whitespace, newline and StrippedCode
        whitespace_chars = [' ', '\t']
        newline_chars = ['\n']
        this_pos = self.pos_marker
        segment_stack = []
        started = tuple()  # empty tuple to satisfy the linter (was None)
        last_char = None
        for idx, c in enumerate(self.raw):
            if last_char:
                this_pos = this_pos.advance_by(last_char)
            # Save the last char
            last_char = c
            if c in newline_chars:
                if started:
                    if started[0] == 'whitespace':
                        segment_stack.append(
                            WhitespaceSegment(
                                self.raw[started[2]:idx],
                                pos_marker=started[1])
                        )
                        started = None
                    elif started[0] == 'code':
                        segment_stack.append(
                            StrippedRawCodeSegment(
                                self.raw[started[2]:idx],
                                pos_marker=started[1])
                        )
                        started = None
                    else:
                        raise ValueError("Unexpected `started` value?!")
                segment_stack.append(
                    NewlineSegment(c, pos_marker=this_pos)
                )
            elif c in whitespace_chars:
                if started:
                    if started[0] == 'whitespace':
                        # We don't want to reset the whitespace counter!
                        continue
                    elif started[0] == 'code':
                        segment_stack.append(
                            StrippedRawCodeSegment(
                                self.raw[started[2]:idx],
                                pos_marker=started[1])
                        )
                    else:
                        raise ValueError("Unexpected `started` value?!")
                started = ('whitespace', this_pos, idx)
            else:
                # This isn't whitespace or a newline
                if started:
                    if started[0] == 'code':
                        # We don't want to reset the code counter!
                        continue
                    elif started[0] == 'whitespace':
                        segment_stack.append(
                            WhitespaceSegment(
                                self.raw[started[2]:idx],
                                pos_marker=started[1])
                        )
                    else:
                        raise ValueError("Unexpected `started` value?!")
                started = ('code', this_pos, idx)
        return segment_stack


class QuotedSegment(RawSegment):
    type = 'quoted'


class StrippedRawCodeSegment(RawSegment):
    type = 'strippedcode'
    is_code = True


class WhitespaceSegment(RawSegment):
    type = 'whitespace'
    is_whitespace = True


class NewlineSegment(WhitespaceSegment):
    type = 'newline'


class CommentSegment(RawSegment):
    type = 'comment'

    def parse(self):
        # Split into several types of comment? Or just parse as is?
        # Probably parse as is.
        return self
