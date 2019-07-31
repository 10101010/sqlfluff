
from collections import namedtuple

TokenMemory = namedtuple('TokenMemory', ['pos', 'token'])
Token = namedtuple('Token', ['start', 'end'])

protoFilePositionMarker = namedtuple('FilePositionMarker', ['statement_index', 'line_no', 'line_pos', 'char_pos'])


class FilePositionMarker(protoFilePositionMarker):
    def advance_by(self, raw="", idx=0):
        stmt = self.statement_index
        line = self.line_no
        pos = self.line_pos
        char_pos = self.char_pos
        for elem in raw:
            char_pos += 1
            if elem == '\n':
                line += 1
                pos = 1
            else:
                pos += 1
        return FilePositionMarker(stmt + idx, line, pos, char_pos)

    def __str__(self):
        return "[{0}]({1}, {2}, {3})".format(
            self.char_pos, self.statement_index, self.line_no, self.line_pos)

    def __gt__(self, other):
        return self.char_pos > other.char_pos

    def __lt__(self, other):
        return self.char_pos < other.char_pos


class SQLParseError(ValueError):
    pass


print("Hello World!")

# Multi stage parser

# First strip comments, potentially extracting special comments (which start with sqlfluff:)
#   - this also makes comment sections, config sections (a subset of comments) and code sections


class BaseSegment(object):
    type = 'base'
    grammar = None
    comment_seperate = False
    is_whitespace = False

    def __init__(self, raw, segments=None, pos_marker=None):
        self.raw = raw
        self.segments = segments
        if pos_marker:
            self.pos_marker = pos_marker
        else:
            self.pos_marker = FilePositionMarker(1, 1, 1, 0)

    @property
    def statement_index(self):
        return self.pos_marker.statement_index

    @property
    def line_no(self):
        return self.pos_marker.line_no

    @property
    def line_pos(self):
        return self.pos_marker.line_pos

    def parse(self):
        # raise NotImplementedError("parse not implemented on type {0}".format(self.__class__))
        return self

    def __repr__(self):
        if self.segments:
            return "<{0}: ({1},{2},{3}) {4!s}>".format(
                self.__class__.__name__,
                self.statement_index,
                self.line_no,
                self.line_pos,
                self.segments)
        else:
            return "<{0}: ({1},{2},{3}) {4!r}>".format(
                self.__class__.__name__,
                self.statement_index,
                self.line_no,
                self.line_pos,
                self.raw)

    def reconstruct(self):
        if self.segments:
            return "".join([seg.reconstruct() for seg in self.segments])
        else:
            return self.raw

    def _preface(self, ident, tabsize, pos_idx):
        preface = (' ' * (ident * tabsize)) + self.__class__.__name__ + ":"
        preface = preface + (' ' * max(pos_idx - len(preface), 0)) + str(self.pos_marker)
        return preface

    @property
    def comments(self):
        return [seg for seg in self.segments if seg.type == 'comment']

    @property
    def non_comments(self):
        return [seg for seg in self.segments if seg.type != 'comment']

    def print(self, ident=0, tabsize=4, pos_idx=60, raw_idx=80):
        preface = self._preface(ident=ident, tabsize=tabsize, pos_idx=pos_idx)
        if self.segments:
            print(preface)
            if self.comment_seperate and len(self.comments) > 0:
                if self.comments:
                    print((' ' * ((ident + 1) * tabsize)) + 'Comments:')
                    for seg in self.comments:
                        seg.print(ident=ident + 2, tabsize=tabsize, pos_idx=pos_idx, raw_idx=raw_idx)
                if self.non_comments:
                    print((' ' * ((ident + 1) * tabsize)) + 'Code:')
                    for seg in self.non_comments:
                        seg.print(ident=ident + 2, tabsize=tabsize, pos_idx=pos_idx, raw_idx=raw_idx)
            else:
                for seg in self.segments:
                    seg.print(ident=ident + 1, tabsize=tabsize, pos_idx=pos_idx, raw_idx=raw_idx)
        else:
            print(preface + (' ' * max(raw_idx - len(preface), 0)) + "{0!r}".format(self.raw))

    @classmethod
    def match(cls, raw, segments):
        """
            Matching can be done from either the raw or the segments.
            This raw function can be overridden, or a grammar defined
            on the underlying class.
        """
        if cls.grammar:
            m = cls.grammar.match(raw=raw, segments=segments)
            # m will either be a segment, or a list.
            # if it's a list, it's a list of segments to construct THIS class
            # if it's a segment, then it's a replacement
            # if it's NONE then we haven't matched and we should return that
            if isinstance(m, BaseSegment):
                return m
            elif isinstance(m, list):
                return cls(raw=raw, segments=m)
            elif m is None:
                return None
            else:
                raise ValueError("Unexpected response to cls.grammar.match: {0!r}".format(m))
        else:
            raise NotImplementedError("{0} has no match function implemented".format(cls.__class__.__name__))

    @staticmethod
    def expand(segments):
        segs = []
        for stmt in segments:
            res = stmt.parse()
            if isinstance(res, BaseSegment):
                segs.append(res)
            else:
                # We might get back an iterable of segments
                segs += stmt.parse()
        return segs


class FileSegment(BaseSegment):
    type = 'file'

    def parse(self):
        """ The parse function on the file segment is a bit special
        so that it contains errors between each statement """
        # Parsing files involves seperating comment segments and code segments and statements segments

        # Comments override everything unless we're in a string literal
        string_tokens = [
            Token('\'', '\''),
            Token('"', '"'),
            Token('`', '`')
        ]

        comment_tokens = [
            Token('/*', '*/'),
            Token('-- ', '\n'),
            Token('#', '\n')
        ]

        statement_seperators = [';']

        statement_stack = []
        segment_stack = []
        comment_entry = None
        string_entry = None
        skip = 0
        this_pos = self.pos_marker
        last_char = None
        last_seg_pos = this_pos  # The starting position of the "current" segment
        last_stmt_pos = this_pos  # The starting position of the "current" statement
        stmt_idx_buff = 0
        for c in self.raw:
            # Advance using the last character
            if last_char:
                this_pos = this_pos.advance_by(last_char, idx=stmt_idx_buff)
                stmt_idx_buff = 0
            # Save the last char
            last_char = c

            # Skip if we're in skip mode (we get a skip of 1 automatically, so only above one matters)
            if skip > 1:
                skip -= 1
                continue

            # Get a forward looking view for comparison
            forward = self.raw[this_pos.char_pos:]

            # What state are we in?
            if not comment_entry and not string_entry:
                for s in string_tokens:
                    if forward.startswith(s.start):
                        print("Found string start at pos {0}! [{1!r}]".format(this_pos, forward[:5]))
                        string_entry = TokenMemory(this_pos, s)
                        # check that we have a segment to add
                        if this_pos > last_seg_pos:
                            segment_stack.append(
                                CodeSegment(
                                    raw[last_seg_pos.char_pos:this_pos.char_pos],
                                    pos_marker=last_seg_pos
                                )
                            )
                            last_seg_pos = this_pos
                        continue
                for c in comment_tokens:
                    if forward.startswith(c.start):
                        print("Found comment start at pos {0}! [{1!r}]".format(this_pos, forward[:5]))
                        comment_entry = TokenMemory(this_pos, c)
                        # check that we have a segment to add
                        if this_pos > last_seg_pos:
                            segment_stack.append(
                                CodeSegment(
                                    raw[last_seg_pos.char_pos:this_pos.char_pos],
                                    pos_marker=last_seg_pos
                                )
                            )
                            last_seg_pos = this_pos
                        continue
                for e in statement_seperators:
                    if forward.startswith(e):
                        # Ok we've found a statement ender, not in a comment or a string
                        print("Found statement end at pos {0}! [{1!r}]".format(this_pos, forward[:5]))
                        # We need to end the current code segment FIRST
                        segment_stack.append(
                            CodeSegment(
                                raw[last_seg_pos.char_pos:this_pos.char_pos],
                                pos_marker=last_seg_pos
                            )
                        )
                        last_seg_pos = this_pos
                        statement_stack.append(
                            StatementSegment(
                                raw[last_stmt_pos.char_pos:this_pos.char_pos],
                                segments=segment_stack,
                                pos_marker=last_stmt_pos))
                        statement_stack.append(
                            StatementSperatorSegment(
                                e, pos_marker=this_pos)
                        )
                        segment_stack = []
                        stmt_idx_buff = 1
                        last_stmt_pos = this_pos.advance_by(e, idx=stmt_idx_buff)
                        last_seg_pos = this_pos.advance_by(e, idx=stmt_idx_buff)
                        skip = len(e)
                        continue
                # print(raw[pos:])
            elif string_entry:
                # We're in a string, just look for the end, of THIS KIND of string
                if string_entry.token.end and forward.startswith(string_entry.token.end):
                    print("Found string end at pos {0}! [{1!r}]".format(this_pos, forward[:5]))
                    # End of segment
                    skip = len(string_entry.token.end)
                    segment_stack.append(
                        QuotedSegment(
                            raw[last_seg_pos.char_pos:this_pos.char_pos + skip],
                            pos_marker=last_seg_pos
                        )
                    )
                    last_seg_pos = this_pos.advance_by(string_entry.token.end)
                    string_entry = None
                    continue
            elif comment_entry:
                # We're in a string, just look for the end, of THIS KIND of string
                if comment_entry.token.end and forward.startswith(comment_entry.token.end):
                    print("Found comment end at pos {0}! [{1!r}]".format(this_pos, forward[:5]))
                    # End of segment
                    skip = len(comment_entry.token.end)
                    segment_stack.append(
                        CommentSegment(
                            raw[last_seg_pos.char_pos:this_pos.char_pos + skip],
                            pos_marker=last_seg_pos
                        )
                    )
                    last_seg_pos = this_pos.advance_by(comment_entry.token.end)
                    comment_entry = None
                    continue
            else:
                raise NotImplementedError("Aaargh!")
        # ok we got to the end, what did we finish in?
        if not comment_entry and not string_entry:
            # We ended on a code block. OK
            if this_pos.char_pos > last_seg_pos.char_pos:
                segment_stack.append(
                    CodeSegment(
                        raw[last_seg_pos.char_pos:this_pos.char_pos],
                        pos_marker=last_seg_pos
                    )
                )
        elif comment_entry:
            # We ended on a comment block
            # Should it have an ending?
            if comment_entry.token.end:
                raise SQLParseError("Final comment not terminated (Expected {0!r})".format(comment_entry.token.end))
            else:
                segment_stack.append(
                    CommentSegment(
                        raw[last_seg_pos.char_pos:this_pos.char_pos],
                        pos_marker=last_seg_pos
                    )
                )
        elif string_entry:
            if string_entry.token.end:
                raise SQLParseError("Final string not terminated (Expected {0!r})".format(string_entry.token.end))
            else:
                raise ValueError("Huh? safiihew")
        else:
            raise ValueError("Huh? eaiuyawren")

        if len(segment_stack) > 0:
            # Let's just terminate this as a statement
            statement_stack.append(
                StatementSegment(
                    raw[last_stmt_pos.char_pos:this_pos.char_pos],
                    segments=segment_stack,
                    pos_marker=last_stmt_pos))

        # We now need to parse each of the sub elements. Expand does that.
        self.segments = self.expand(statement_stack)
        return self


class StatementSperatorSegment(BaseSegment):
    type = 'statement_seperator'


class BaseGrammar(object):
    """ Grammars are a way of composing match statements, any grammar
    must implment the `match` function. Segments can also be passed to
    most grammars. Segments implement `match` as a classmethod. Grammars
    implement it as an instance method """

    # TODO: We should probably remove the raw idea from here. We don't use it,
    # and we should just reconstruct from the segments if we need to.
    def match(self, raw, segments):
        """
            Matching can be done from either the raw or the segments.
            This raw function can be overridden, or a grammar defined
            on the underlying class.
        """
        raise NotImplementedError("{0} has no match function implemented".format(self.__class__.__name__))


class OneOf(BaseGrammar):
    """ Match any of the elements given once, if it matches
    multiple, it returns the first """
    def __init__(self, *args, **kwargs):
        self._options = args

    def match(self, raw, segments):
        # Match on each of the options
        matches = [opt.match(raw, segments) for opt in self._options]

        if sum([1 if m is not None else 0 for m in matches]) > 1:
            print("WARNING! Ambiguous match!")

        for m in matches:
            if m:
                return m
        else:
            return None


class GreedyUntil(BaseGrammar):
    """ Match anything, up to but not including the given options """
    def __init__(self, *args, **kwargs):
        self._options = args
        # `strict`, means the segment will not be matched WITHOUT
        # the ending clause. Normally, if we run out of segments,
        # then this will still match
        self.strict = kwargs.get('strict', False)

    def match(self, raw, segments):
        seg_buffer = []
        for seg in segments:
            for opt in self._options:
                if opt.match(seg.raw, seg):
                    # it's a match! Return everything up to this point
                    if seg_buffer:
                        return seg
                    else:
                        # if the buffer is empty, then no match
                        return None
                else:
                    continue
            else:
                # Add this to the buffer
                seg_buffer.append(seg)
        else:
            # We've gone through all the segments, and not found the end
            if self.strict:
                # Strict mode means this is NOT at match because we didn't find the end
                return None
            else:
                return seg_buffer


class Sequence(BaseGrammar):
    """ Match a specific sequence of elements """
    def __init__(self, *args, **kwargs):
        self._elems = args

    def match(self, raw, segments):
        # we should assume that segments aren't mutated in a grammar
        # so that the number we get back from a match is the same as
        # the number we should skip.
        seg_idx = 0
        for elem in self.elems:
            m = elem.match(segments[seg_idx:])
            if m:
                # deal with the matches
                # advance the counter
                seg_idx += len(m)
            else:
                # We failed to match an element, fail out.
                return None
        else:
            # If the segments get mutated we might need to do something different here
            return segments


class ContainsOnly(BaseGrammar):
    """ match a sequence of segments which are only of the types,
    or only match the grammars in the list """
    def __init__(self, *args, **kwargs):
        self._options = args

    def match(self, raw, segments):
        for seg in segments:
            matched = False
            for opt in self._options:
                if isinstance(opt, str) and seg.type == opt:
                    matched = True
                    break
                elif isinstance(opt, (BaseGrammar, BaseSegment)) and opt.match(seg.raw, [seg]):
                    matched = True
                    break
            if not matched:
                print("Non Matching Segment! {0!r}".format(seg))
                # found a non matching segment:
                return None
        else:
            # Should we also be returning a raw here?
            return segments


class StartsWith(BaseGrammar):
    """ Match if the first element is the same, with configurable
    whitespace and comment handling """
    def __init__(self, target, code_only=True, **kwargs):
        self.target = target
        self.code_only = code_only
        # Implement config handling later...

    def match(self, raw, segments):
        if self.code_only:
            first_code = None
            first_code_idx = None
            for idx, seg in enumerate(segments):
                if seg.type == 'strippedcode':
                    first_code_idx = idx
                    first_code = seg
                    break
            else:
                return None

            match = self.target.match(raw=first_code.raw, segments=[first_code])
            if match:
                # Let's actually make it a keyword segment
                segments[first_code_idx] = match
                return segments
            else:
                return None
        else:
            raise NotImplementedError("Not expecting to match StartsWith and also not just code!?")


class Keyword(BaseGrammar):
    """ Match a keyword, optionally case sensitive """
    def __init__(self, word, case_sensitive=False, **kwargs):
        # NB We store the word as upper case unless case sensitive
        # For this one we won't accept whitespace or comments
        self.case_sensitive = case_sensitive
        if self.case_sensitive:
            self.word = word
        else:
            self.word = word.upper()

    def match(self, raw, segments):
        # We can only match segments of length 1
        if len(segments) == 1:
            if ((self.case_sensitive and self.word == raw) or (not self.case_sensitive and self.word == raw.upper())):
                return KeywordSegment(raw=raw, segments=segments)
        return None

# Note on SQL Grammar
# https://www.cockroachlabs.com/docs/stable/sql-grammar.html#select_stmt


class KeywordSegment(BaseSegment):
    type = 'keyword'


class SelectStatementSegment(BaseSegment):
    type = 'select_statement'
    # From here down, comments are printed seperately.
    comment_seperate = True
    # match grammar
    grammar = StartsWith(Keyword('select'))

    def parse(self):
        print("PARSING SELECT STATEMENT")
        raise NotImplementedError("Blah!")
        return self


class InsertStatementSegment(BaseSegment):
    type = 'insert_statement'
    # From here down, comments are printed seperately.
    comment_seperate = True
    grammar = StartsWith(Keyword('insert'))


class EmptyStatementSegment(BaseSegment):
    type = 'empty_statement'
    # From here down, comments are printed seperately.
    comment_seperate = True
    grammar = ContainsOnly('comment', 'newline')
    # TODO: At some point - we should lint that these are only
    # allowed at the END - otherwise it's probably a parsing error


class UnparsableSegment(BaseSegment):
    type = 'unparsable'
    # From here down, comments are printed seperately.
    comment_seperate = True


class StatementSegment(BaseSegment):
    type = 'statement'
    # From here down, comments are printed seperately.
    comment_seperate = True
    # Let's define a grammar from here on in
    grammar = OneOf(SelectStatementSegment, InsertStatementSegment, EmptyStatementSegment)

    def parse(self):
        if self.segments is None:
            raise ValueError("No Segments to parse!?")

        # First we need to allow any existing segments in this
        # statement to expand out. This could inlude code and comment
        # segments
        self.segments = self.expand(self.segments)

        # Here we then need to allow any number of comments and whitespace
        # (to lint later)
        # THEN it must match a type of sql statement

        # Mutate itself, and then return

        # If it can't match, then we should have an unparsable block
        match = self.match(raw=self.raw, segments=self.segments)
        if match is None:
            self.segments = [UnparsableSegment(raw=self.raw, segments=self.segments)]
        else:
            self.segments = [match]

        return self


class CodeSegment(BaseSegment):
    type = 'code'

    def parse(self):
        # Split into whitespace, newline and StrippedCode
        whitespace_chars = [' ', '\t']
        newline_chars = ['\n']
        this_pos = self.pos_marker
        segment_stack = []
        started = None
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
                            StrippedCodeSegment(
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
                            StrippedCodeSegment(
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


class QuotedSegment(BaseSegment):
    type = 'quoted'


class StrippedCodeSegment(BaseSegment):
    type = 'strippedcode'


class WhitespaceSegment(BaseSegment):
    type = 'whitespace'
    is_whitespace = True


class NewlineSegment(WhitespaceSegment):
    type = 'newline'


class CommentSegment(BaseSegment):
    type = 'comment'

    def parse(self):
        # Split into several types of comment? Or just parse as is?
        # Probably parse as is.
        return self


raw = """\
# COMMENT
-- Another Comment
Select A from Sys.dual where a
-- inline comment
in  ('RED',  /* Inline */  'GREEN','BLUE');
select * from tbl_b; # as another comment
insert into sch.tbl_b
    (col1)
values (123);
with tmp as (
    select * from  blah
)
select a, b from tmp;
# And that's the end
"""


tabsize = 4
SEMICOLON = ';'


if __name__ == "__main__":
    print("##### parsing:")
    print(raw)
    fs = FileSegment(raw)
    parsed = fs.parse()
    print(parsed.segments)
    print(parsed.reconstruct())
    parsed.print()
