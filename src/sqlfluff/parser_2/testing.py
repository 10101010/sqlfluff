
from collections import namedtuple

TokenMemory = namedtuple('TokenMemory', ['pos', 'token'], verbose=True)
Token = namedtuple('Token', ['start', 'end'], verbose=True)

protoFilePositionMarker = namedtuple('FilePositionMarker', ['statement_index', 'line_no', 'line_pos', 'char_pos'], verbose=True)

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

## First strip comments, potentially extracting special comments (which start with sqlfluff:)
##   - this also makes comment sections, config sections (a subset of comments) and code sections


class BaseSegment(object):
    type = 'base'
    grammar = None

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
        raise NotImplementedError("parse not implemented on type {0}".format(self.__class__))
    
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

    def print(self, ident=0, tabsize=4, pos_idx=60, raw_idx=80):
        preface = (' ' * (ident * tabsize)) + self.__class__.__name__ + ":"
        preface = preface + (' ' * max(pos_idx - len(preface), 0)) + str(self.pos_marker)
        if self.segments:
            print(preface)
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
        if grammar:
            return grammar.match(raw=raw, segments=segments)
        else:
            raise NotImplementedError("{0} has no match function implemented".format(cls.__class__.__name__))


class FileSegment(BaseSegment):
    type = 'file'

    def parse(self):
        """ The parse function on the file segment is a bit special
        so that it contains errors between each statement """
        # Parsing files involves seperating comment segments and code segments and statements segments
        last_pos = self.pos_marker

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
        was_newline = False
        this_pos = self.pos_marker
        last_char = None
        last_seg_pos = this_pos # The starting position of the "current" segment
        last_stmt_pos = this_pos # The starting position of the "current" statement
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
                        # Don't store the segment, because we're only looking for
                        # strings at this stage so we can ignore "false" comments
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
                    # Don't save, remember, we're only looking for comments!
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

        self.segments = statement_stack
        return self

class StatementSperatorSegment(BaseSegment):
    type = 'statement_seperator'

    def parse(self):
        return self

class StatementSegment(BaseSegment):
    type = 'statement'

    def parse(self):
        if self.segments is None:
            raise ValueError("No Segments to parse!?")
        # Here we then need to allow any number of comments and whitespace
        # (to lint later)
        # THEN it must match a type of sql statement

        # Mutate itself, and then return

        # If it can't match, then we should have an unparsable block
        return self

class CodeSegment(BaseSegment):
    type = 'code'

    def parse(self):
        return self

class CommentSegment(BaseSegment):
    type = 'comment'

    def parse(self):
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
values (123)
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
