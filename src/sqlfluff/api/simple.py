"""The simple public API methods."""

from ..core import Linter


def _unfiy_str_or_file(sql):
    """Unify string and files in the same format."""
    if not isinstance(sql, str):
        try:
            sql = sql.read()
        except AttributeError:
            raise TypeError("Value passed as sql is not a string or a readable object.")
    return sql


def lint(sql, dialect="ansi"):
    """Lint a sql string or file.

    Args:
        sql (:obj:`str` or file-like object): The sql to be linted
            either as a string or a subclass of :obj:`TextIOBase`.
        dialect (:obj:`str`, optional): A reference to the dialect of the sql
            to be linted. Defaults to `ansi`.

    Returns:
        :obj:`list` of :obj:`dict` for each violation found.
    """
    sql = _unfiy_str_or_file(sql)
    linter = Linter(dialect=dialect)

    result = linter.lint_string_wrapped(sql)
    result_records = result.as_records()
    # Return just the violations for this file
    return result_records[0]["violations"]


def fix(sql, dialect="ansi"):
    """Fix a sql string or file.

    Args:
        sql (:obj:`str` or file-like object): The sql to be linted
            either as a string or a subclass of :obj:`TextIOBase`.
        dialect (:obj:`str`, optional): A reference to the dialect of the sql
            to be linted. Defaults to `ansi`.

    Returns:
        :obj:`str` for the fixed sql if possible.
    """
    sql = _unfiy_str_or_file(sql)
    linter = Linter(dialect=dialect)

    result = linter.lint_string_wrapped(sql, fix=True)
    fixed_string = result.paths[0].files[0].fix_string()[0]
    return fixed_string
