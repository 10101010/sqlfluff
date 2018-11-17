# SqlFluff
## The SQL Linter for humans

# Documentation

## `sqlfluff version`

**Purpose:** Read out the current version information of sqlfluff.

**Usage:** `sqlfluff version [-v, --verbose]`

**Parameters:**

- `[-v, --verbose]`: Verbosity, how detailed should the output be.

**Example responses:**

> *Not verbose:*
> ```shell
> $ sqlfluff version
> 0.0.4
> ```

> *Verbose:*
> ```shell
> $ sqlfluff version -v
> sqlfluff:      0.0.4 python:        3.6.7
> ```

## `sqlfluff lint`

**Purpose:** Actually lint things.

**Usage:** `sqlfluff lint [-v, --verbose] [-n, --nocolor] [--dialect ansi] [--rules RULES] [PATH]`

**Parameters:**

- `[-v, --verbose]`: Verbosity, how detailed should the output be.
- `[-n, --nocolor]`: No color - if this is set then the output will be
  without ANSI color codes.
- `[--dialect ansi]`: Which dialect to run sqlfluff with, defaulting
  to `ansi`. Options
  - `ansi` - Currently the only option - assumes that the sql is in
    line with [_ISO/IEC 9075_](https://en.wikipedia.org/wiki/ISO/IEC_9075)
  - ... to come `mysql`, `redshift` and potentially others...
- `[--rules RULES]`: Narrow the search to only specific rules. For example
  specifying `--rules L001` will only search for rule `L001` (Unnessesary
  trailing whitespace). Multiple rules can be specified with commas e.g.
  `--rules L001,L002` will specify only looking for violations of rule 
  `L001` and rule `L002`.
- `[PATH]` the path to a sql file or directory to lint.
  - _Files_ e.g. `test_file.sql` or `src/some_other_file.sql` - passing
    the path of a single file just lints a single file.
  - _Directories_ e.g. `src` or `~/dev/my_project` - pass a directory path
    searches through that directory for `.sql` files and lints all the
    files it finds.
  - _Blank_. If you just call `sqlfluff lint` without a path specified
    if will be as though you passed the current working directory and
    will behave as per the above command.

**Example responses:**

_NB: Examples of the `--nocolor` option not shown as the textual output is the same, just with different colors_

> *Not verbose:*
> ```shell
> $ sqlfluff lint test.sql
> == [test.sql] FAIL
> L:   1 | P:   1 | L003 | Single indentation uses a number of spaces not a multiple of 4
> L:   1 | P:  14 | L006 | Operators should be surrounded by a single space unless at the start/end of a line
> L:   1 | P:  27 | L001 | Unnecessary trailing whitespace
> ```

> *Verbose (with dialect):*
> ```shell
> $ sqlfluff lint test.sql -v  --dialect ansi
> ==== sqlfluff ====
> sqlfluff:      0.0.4 python:        3.6.7
> dialect:        ansi verbosity:         1
> ==== readout ====
> === [ path: test.sql ] ===
> == [test.sql] FAIL
> L:   1 | P:   1 | L003 | Single indentation uses a number of spaces not a multiple of 4
> L:   1 | P:  14 | L006 | Operators should be surrounded by a single space unless at the start/end of a line
> L:   1 | P:  27 | L001 | Unnecessary trailing whitespace
> ==== summary ====
> violations:        3 status:         FAIL
> ```


> *Very Verbose:*
> ```shell
> $ sqlfluff lint test.sql -vv
> ==== sqlfluff ====
> sqlfluff:      0.0.4 python:        3.6.7
> dialect:        ansi verbosity:         2
> ==== readout ====
> === [ path: test.sql ] ===
> == [test.sql] FAIL
> L:   1 | P:   1 | L003 | Single indentation uses a number of spaces not a multiple of 4
> L:   1 | P:  14 | L006 | Operators should be surrounded by a single space unless at the start/end of a line
> L:   1 | P:  27 | L001 | Unnecessary trailing whitespace
> ==== summary ====
> files:             1 violations:        3
> clean files:       0 unclean files:     1
> avg per file:   3.00 status:         FAIL
> ```
