"""Defines the templaters."""

import os.path

from jinja2.sandbox import SandboxedEnvironment
from jinja2 import meta
import jinja2.nodes

from ..errors import SQLTemplaterError
from ..parser import FilePositionMarker

from .base import register_templater, TemplatedFile
from .python import PythonTemplateInterface


@register_templater
class JinjaTemplateInterface(PythonTemplateInterface):
    """A templater using the jinja2 library.

    See: https://jinja.palletsprojects.com/
    """

    name = "jinja"

    @staticmethod
    def _extract_macros_from_template(template, env, ctx):
        """Take a template string and extract any macros from it.

        Lovingly inspired by http://codyaray.com/2015/05/auto-load-jinja2-macros
        """
        from jinja2.runtime import Macro  # noqa

        # Iterate through keys exported from the loaded template string
        context = {}
        macro_template = env.from_string(template, globals=ctx)
        # This is kind of low level and hacky but it works
        for k in macro_template.module.__dict__:
            attr = getattr(macro_template.module, k)
            # Is it a macro? If so install it at the name of the macro
            if isinstance(attr, Macro):
                context[k] = attr
        # Return the context
        return context

    @classmethod
    def _extract_macros_from_path(cls, path, env, ctx):
        """Take a path and extract macros from it."""
        # Does the path exist? It should as this check was done on config load.
        if not os.path.exists(path):
            raise ValueError("Path does not exist: {0}".format(path))

        macro_ctx = {}
        if os.path.isfile(path):
            # It's a file. Extract macros from it.
            with open(path, "r") as opened_file:
                template = opened_file.read()
            # Update the context with macros from the file.
            macro_ctx.update(
                cls._extract_macros_from_template(template, env=env, ctx=ctx)
            )
        else:
            # It's a directory. Iterate through files in it and extract from them.
            for dirpath, _, files in os.walk(path):
                for fname in files:
                    if fname.endswith(".sql"):
                        macro_ctx.update(
                            cls._extract_macros_from_path(
                                os.path.join(dirpath, fname), env=env, ctx=ctx
                            )
                        )
        return macro_ctx

    def _extract_macros_from_config(self, config, env, ctx):
        """Take a config and load any macros from it."""
        if config:
            # This is now a nested section
            loaded_context = (
                config.get_section((self.templater_selector, self.name, "macros")) or {}
            )
        else:
            loaded_context = {}

        # Iterate to load macros
        macro_ctx = {}
        for value in loaded_context.values():
            macro_ctx.update(
                self._extract_macros_from_template(value, env=env, ctx=ctx)
            )
        return macro_ctx

    @staticmethod
    def _generate_dbt_builtins():
        """Generate the dbt builtins which are injected in the context."""
        # This feels a bit wrong defining these here, they should probably
        # be configurable somewhere sensible. But for now they're not.
        # TODO: Come up with a better solution.

        class ThisEmulator:
            """A class which emulates the `this` class from dbt."""

            name = "this_model"
            schema = "this_schema"
            database = "this_database"

            def __str__(self):
                return self.name

        dbt_builtins = {
            # `is_incremental()` renders as False, always in this case.
            # TODO: This means we'll never parse the other part of the query,
            # so we should find a solution to that. Perhaps forcing the file
            # to be parsed TWICE if it uses this variable.
            "is_incremental": lambda: False,
            "this": ThisEmulator(),
        }
        return dbt_builtins

    @classmethod
    def _crawl_tree(cls, tree, variable_names, raw):
        """Crawl the tree looking for occurances of the undeclared values."""
        # First iterate through children
        for elem in tree.iter_child_nodes():
            yield from cls._crawl_tree(elem, variable_names, raw)
        # Then assess self
        if isinstance(tree, jinja2.nodes.Name) and tree.name in variable_names:
            line_no = tree.lineno
            line = raw.split("\n")[line_no - 1]
            pos = line.index(tree.name) + 1
            # Generate the charpos. +1 is for the newline characters themselves
            charpos = (
                sum(len(raw_line) + 1 for raw_line in raw.split("\n")[: line_no - 1])
                + pos
            )
            # NB: The positions returned here will be *inconsistent* with those
            # from the linter at the moment, because these are references to the
            # structure of the file *before* templating.
            yield SQLTemplaterError(
                "Undefined jinja template variable: {0!r}".format(tree.name),
                pos=FilePositionMarker(None, line_no, pos, charpos),
            )

    def process(self, in_str, fname=None, config=None):
        """Process a string and return the new string.

        Args:
            in_str (:obj:`str`): The input string.
            fname (:obj:`str`, optional): The filename of this string. This is
                mostly for loading config files at runtime.
            config (:obj:`FluffConfig`): A specific config to use for this
                templating operation. Only necessary for some templaters.

        """
        # We explicitly want to preserve newlines.
        env = SandboxedEnvironment(
            keep_trailing_newline=True,
            # The do extension allows the "do" directive
            autoescape=False,
            extensions=["jinja2.ext.do"],
        )

        if not config:
            raise ValueError(
                "For the jinja templater, the `process()` method requires a config object."
            )

        # Load the context
        live_context = self.get_context(fname=fname, config=config)
        # Apply dbt builtin functions if we're allowed.
        apply_dbt_builtins = config.get_section(
            (self.templater_selector, self.name, "apply_dbt_builtins")
        )
        if apply_dbt_builtins:
            # This feels a bit wrong defining these here, they should probably
            # be configurable somewhere sensible. But for now they're not.
            # TODO: Come up with a better solution.
            dbt_builtins = self._generate_dbt_builtins()
            for name in dbt_builtins:
                # Only apply if it hasn't already been set at this stage.
                if name not in live_context:
                    live_context[name] = dbt_builtins[name]

        # Load config macros
        ctx = self._extract_macros_from_config(config=config, env=env, ctx=live_context)
        # Load macros from path (if applicable)
        macros_path = config.get_section(
            (self.templater_selector, self.name, "load_macros_from_path")
        )
        if macros_path:
            ctx.update(
                self._extract_macros_from_path(macros_path, env=env, ctx=live_context)
            )
        live_context.update(ctx)

        # Load the template, passing the global context.
        template = env.from_string(in_str, globals=live_context)
        violations = []

        # Attempt to identify any undeclared variables
        try:
            syntax_tree = env.parse(in_str)
            undefined_variables = meta.find_undeclared_variables(syntax_tree)
        except Exception as err:
            # TODO: Add a url here so people can get more help.
            raise SQLTemplaterError(
                "Failure in identifying Jinja variables: {0}.".format(err)
            )

        # Get rid of any that *are* actually defined.
        for val in live_context:
            if val in undefined_variables:
                undefined_variables.remove(val)

        if undefined_variables:
            # Lets go through and find out where they are:
            for val in self._crawl_tree(syntax_tree, undefined_variables, in_str):
                violations.append(val)

        try:
            # NB: Passing no context. Everything is loaded when the template is loaded.
            out_str = template.render()
            return (
                TemplatedFile(source_str=in_str, templated_str=out_str, fname=fname),
                violations,
            )
        except Exception as err:
            # TODO: Add a url here so people can get more help.
            violations.append(
                SQLTemplaterError(
                    (
                        "Unrecoverable failure in Jinja templating: {0}. Have you configured "
                        "your variables? https://docs.sqlfluff.com/en/latest/configuration.html"
                    ).format(err)
                )
            )
            return None, violations
