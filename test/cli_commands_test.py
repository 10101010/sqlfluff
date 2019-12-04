"""The Test file for CLI (General)."""

import configparser
import tempfile
import os
import shutil

import pytest
from click.testing import CliRunner

import sqlfluff
from sqlfluff.cli.commands import lint, version, rules, fix, parse


def invoke_assert_code(ret_code=0, args=None, kwargs=None):
    """Invoke a command and check return code."""
    args = args or []
    kwargs = kwargs or {}
    runner = CliRunner()
    result = runner.invoke(*args, **kwargs)
    if ret_code == 0:
        if result.exception:
            raise result.exception
    assert ret_code == result.exit_code
    return result


def test__cli__command_directed():
    """Basic checking of lint functionality."""
    result = invoke_assert_code(
        ret_code=65,
        args=[lint, ['-n', 'test/fixtures/linter/indentation_error_simple.sql']]
    )
    # We should get a readout of what the error was
    check_a = "L:   2 | P:   1 | L003"
    # NB: Skip the number at the end because it's configurable
    check_b = "Indentation length is not a multiple of"
    assert check_a in result.output
    assert check_b in result.output


def test__cli__command_dialect():
    """Check the script raises the right exception on an unknown dialect."""
    # The dialect is unknown should be a non-zero exit code
    invoke_assert_code(
        ret_code=66,
        args=[lint, ['-n', '--dialect', 'faslkjh', 'test/fixtures/linter/indentation_error_simple.sql']]
    )


def test__cli__command_lint_a():
    """Check basic commands on a simple script."""
    # Not verbose
    invoke_assert_code(args=[lint, ['-n', 'test/fixtures/cli/passing_a.sql']])
    # Verbose
    invoke_assert_code(args=[lint, ['-n', '-v', 'test/fixtures/cli/passing_a.sql']])
    # Very Verbose
    invoke_assert_code(args=[lint, ['-n', '-vvvv', 'test/fixtures/cli/passing_a.sql']])
    # Very Verbose (Colored)
    invoke_assert_code(args=[lint, ['-vvvv', 'test/fixtures/cli/passing_a.sql']])


@pytest.mark.parametrize('command', [
    ('-', '-n', ), ('-', '-n', '-v',), ('-', '-n', '-vv',), ('-', '-vv',),
])
def test__cli__command_lint_stdin(command):
    """Check basic commands on a simple script using stdin.

    The subprocess command should exit without errors, as no issues should be found.
    """
    with open('test/fixtures/cli/passing_a.sql', 'r') as f:
        sql = f.read()
    invoke_assert_code(args=[lint, command], kwargs=dict(input=sql))


@pytest.mark.parametrize('command', [
    # Test basic linting
    (lint, ['-n', 'test/fixtures/cli/passing_b.sql']),
    # Check basic parsing
    (parse, ['-n', 'test/fixtures/cli/passing_b.sql']),
    # Check basic parsing, with the code only option
    (parse, ['-n', 'test/fixtures/cli/passing_b.sql', '-c']),
    # Check linting works in specifying rules
    (lint, ['-n', '--rules', 'L001', 'test/fixtures/linter/operator_errors.sql']),
    # Check linting works in specifying multiple rules
    (lint, ['-n', '--rules', 'L001,L002', 'test/fixtures/linter/operator_errors.sql']),
    # Check linting works with both included and excluded rules
    (lint, ['-n', '--rules', 'L001,L006', '--exclude-rules', 'L006', 'test/fixtures/linter/operator_errors.sql']),
    # Check linting works with just excluded rules
    (lint, ['-n', '--exclude-rules', 'L006,L007', 'test/fixtures/linter/operator_errors.sql'])
])
def test__cli__command_lint_b(command):
    """Check basic commands on a more complicated script."""
    invoke_assert_code(args=command)


def test__cli__command_versioning():
    """Check version command."""
    # Get the package version info
    pkg_version = sqlfluff.__version__
    # Get the version info from the config file
    config = configparser.ConfigParser()
    config.read_file(open('src/sqlfluff/config.ini'))
    config_version = config['sqlfluff']['version']
    assert pkg_version == config_version
    # Get the version from the cli
    runner = CliRunner()
    result = runner.invoke(version)
    assert result.exit_code == 0
    # We need to strip to remove the newline characters
    assert result.output.strip() == pkg_version


def test__cli__command_version():
    """Just check version command for exceptions."""
    # Get the package version info
    pkg_version = sqlfluff.__version__
    runner = CliRunner()
    result = runner.invoke(version)
    assert result.exit_code == 0
    assert pkg_version in result.output
    # Check a verbose version
    result = runner.invoke(version, ['-v'])
    assert result.exit_code == 0
    assert pkg_version in result.output


def test__cli__command_rules():
    """Just check rules command for exceptions."""
    invoke_assert_code(args=[rules])


def generic_roundtrip_test(source_file, rulestring):
    """A test for roundtrip testing, take a file buffer, lint, fix and lint.

    This is explicitly different from the linter version of this, in that
    it uses the command line rather than the direct api.
    """
    filename = 'tesing.sql'
    # Lets get the path of a file to use
    tempdir_path = tempfile.mkdtemp()
    filepath = os.path.join(tempdir_path, filename)
    # Open the example file and write the content to it
    with open(filepath, mode='w') as dest_file:
        for line in source_file:
            dest_file.write(line)
    # Check that we first detect the issue
    invoke_assert_code(ret_code=65, args=[lint, ['--rules', rulestring, filepath]])
    # Fix the file (in force mode)
    invoke_assert_code(args=[fix, ['--rules', rulestring, '-f', filepath]])
    # Now lint the file and check for exceptions
    invoke_assert_code(args=[lint, ['--rules', rulestring, filepath]])
    shutil.rmtree(tempdir_path)


def test__cli__command__fix_L001():
    """Test the round trip of detecting, fixing and then not detecting rule L001."""
    with open('test/fixtures/linter/indentation_errors.sql', mode='r') as f:
        generic_roundtrip_test(f, 'L001')


def test__cli__command__fix_L008_a():
    """Test the round trip of detecting, fixing and then not detecting rule L001."""
    with open('test/fixtures/linter/whitespace_errors.sql', mode='r') as f:
        generic_roundtrip_test(f, 'L008')


def test__cli__command__fix_L008_b():
    """Test the round trip of detecting, fixing and then not detecting rule L001."""
    with open('test/fixtures/linter/indentation_errors.sql', mode='r') as f:
        generic_roundtrip_test(f, 'L008')
