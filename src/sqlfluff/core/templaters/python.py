"""Defines the templaters."""

import ast
from string import Formatter
from typing import Iterable, Dict, Tuple, List, Iterator, Any

from ..errors import SQLTemplaterError

from .base import RawTemplateInterface, register_templater, TemplatedFile


@register_templater
class PythonTemplateInterface(RawTemplateInterface):
    """A templater using python format strings.

    See: https://docs.python.org/3/library/string.html#format-string-syntax

    For the python templater we don't allow functions or macros because there isn't
    a good way of doing it securely. Use the jinja templater for this.

    The python templater also defines a lot of the logic for how
    to allow fixing and translation in a templated file.
    """

    name = "python"

    def __init__(self, override_context=None, **kwargs):
        self.default_context = dict(test_value="__test__")
        self.override_context = override_context or {}

    @staticmethod
    def infer_type(s):
        """Infer a python type from a string ans convert.

        Given a string value, convert it to a more specific built-in Python type
        (e.g. int, float, list, dictionary) if possible.

        """
        try:
            return ast.literal_eval(s)
        except (SyntaxError, ValueError):
            return s

    def get_context(self, fname=None, config=None):
        """Get the templating context from the config."""
        # TODO: The config loading should be done outside the templater code. Here
        # is a silly place.
        if config:
            # This is now a nested section
            loaded_context = (
                config.get_section((self.templater_selector, self.name, "context"))
                or {}
            )
        else:
            loaded_context = {}
        live_context = {}
        live_context.update(self.default_context)
        live_context.update(loaded_context)
        live_context.update(self.override_context)

        # Infer types
        for k in loaded_context:
            live_context[k] = self.infer_type(live_context[k])
        return live_context

    def process(self, in_str, fname=None, config=None):
        """Process a string and return a TemplatedFile.

        Args:
            in_str (:obj:`str`): The input string.
            fname (:obj:`str`, optional): The filename of this string. This is
                mostly for loading config files at runtime.
            config (:obj:`FluffConfig`): A specific config to use for this
                templating operation. Only necessary for some templaters.

        """
        live_context = self.get_context(fname=fname, config=config)
        try:
            new_str = in_str.format(**live_context)
        except KeyError as err:
            # TODO: Add a url here so people can get more help.
            raise SQLTemplaterError(
                "Failure in Python templating: {0}. Have you configured your variables?".format(
                    err
                )
            )
        return TemplatedFile(source_str=in_str, templated_str=new_str, fname=fname), []

    @staticmethod
    def _findall(substr: str, in_str: str) -> Iterator[int]:
        """Yields all the positions sbstr within in_str.

        https://stackoverflow.com/questions/4664850/how-to-find-all-occurrences-of-a-substring
        """
        # Return nothing if one of the inputs is trivial
        if not substr or not in_str:
            return
        idx = in_str.find(substr)
        while idx != -1:
            yield idx
            idx = in_str.find(substr, idx + 1)

    @classmethod
    def _substring_occurances(
        cls, in_str: str, substrings: Iterable[str]
    ) -> Dict[str, List[int]]:
        """Find every occurance of the given substrings."""
        occurances = {}
        for substring in substrings:
            occurances[substring] = list(cls._findall(substring, in_str))
        return occurances

    @staticmethod
    def _sorted_occurance_tuples(
        occurances: Dict[str, List[int]]
    ) -> List[Tuple[str, int]]:
        """Sort a dict of occurances into a sorted list of tuples."""
        return sorted(
            ((raw, idx) for raw in occurances.keys() for idx in occurances[raw]),
            # Sort first by position, then by lexical (for stability)
            key=lambda x: (x[1], x[0]),
        )

    @classmethod
    def _slice_python_template(cls, in_str: str) -> List[Tuple[str, str, int]]:
        """Slice a templated python string into token tuples.

        This uses Formatter() as per:
        https://docs.python.org/3/library/string.html#string.Formatter
        """
        fmt = Formatter()
        elems = []
        in_idx = 0
        for literal_text, field_name, format_spec, conversion in fmt.parse(in_str):
            if literal_text:
                escape_chars = cls._sorted_occurance_tuples(
                    cls._substring_occurances(literal_text, ["}", "{"])
                )
                idx = 0
                while escape_chars:
                    first_char = escape_chars.pop()
                    # Is there a literal first?
                    if first_char[1] > idx:
                        elems.append(
                            (literal_text[idx : first_char[1]], "literal", in_idx)
                        )
                        in_idx += first_char[1] - idx
                    # Add the escaped
                    idx = first_char[1] + len(first_char[0])
                    elems.append(
                        # We double them here to make the raw
                        (literal_text[first_char[1] : idx] * 2, "escaped", in_idx)
                    )
                    # Will always be 2 in this case
                    in_idx += 2
                # Deal with last one (if present)
                if literal_text[idx:]:
                    elems.append((literal_text[idx:], "literal", in_idx))
                    in_idx += len(literal_text) - idx
            # Deal with fields
            if field_name:
                constructed_token = "{{{field_name}{conv}{spec}}}".format(
                    field_name=field_name,
                    conv="!{}".format(conversion) if conversion else "",
                    spec=":{}".format(format_spec) if format_spec else "",
                )
                elems.append((constructed_token, "templated", in_idx))
                in_idx += len(constructed_token)
        return elems

    @staticmethod
    def _split_invariants(
        raw_sliced: List[Tuple[str, str, int]],
        literals: List[str],
        raw_occurances: Dict[str, List[int]],
        templated_occurances: Dict[str, List[int]],
    ) -> List[Tuple[str, slice, slice, Any]]:
        """Split a sliced file on its invariant literals."""
        # Calculate invariants
        invariants = [
            literal
            for literal in literals
            if len(raw_occurances[literal]) == 1
            and len(templated_occurances[literal]) == 1
        ]
        # Set up some buffers
        split_buffer: List[Tuple[str, slice, slice, Any]] = []
        buffer: List[Tuple[str, str, int]] = []
        idx = None
        templ_tdx = 0
        # Loop through
        for raw, token_type, raw_pos in raw_sliced:
            if raw in invariants:
                if len(buffer) > 1:
                    split_buffer.append(
                        (
                            "compound",
                            slice(idx, raw_pos),
                            slice(templ_tdx, templated_occurances[raw][0]),
                            buffer,
                        )
                    )
                elif len(buffer) == 1:
                    split_buffer.append(
                        (
                            "simple",
                            slice(idx, raw_pos),
                            slice(templ_tdx, templated_occurances[raw][0]),
                            buffer[0],
                        )
                    )
                buffer = []
                idx = None
                # NB: Longer tuple format here
                split_buffer.append(
                    (
                        "invariant",
                        slice(raw_pos, raw_pos + len(raw)),
                        slice(
                            templated_occurances[raw][0],
                            templated_occurances[raw][0] + len(raw),
                        ),
                        (raw, token_type, templated_occurances[raw][0]),
                    )
                )
                templ_tdx = templated_occurances[raw][0] + len(raw)
            else:
                buffer.append((raw, token_type, raw_pos))
                if not idx:
                    idx = raw_pos
        return split_buffer

    @staticmethod
    def _filter_occurances(
        file_slice: slice, occurances: Dict[str, List[int]]
    ) -> Dict[str, List[int]]:
        """Filter a dict of occurances to just those within a slice."""
        filtered = {
            key: [
                pos
                for pos in occurances[key]
                if pos >= file_slice.start and pos < file_slice.stop
            ]
            for key in occurances.keys()
        }
        return {key: filtered[key] for key in filtered.keys() if filtered[key]}

    @staticmethod
    def _coalesce_types(elems: List[Tuple[str, str, int]]) -> str:
        """Coalesce to the priority type."""
        # Make a set of types
        types = {elem[1] for elem in elems}
        # Take the easy route if they're all the same type
        if len(types) == 1:
            return types.pop()
        # Then deal with priority
        priority = ["templated", "escaped", "literal"]
        for p in priority:
            if p in types:
                return p
        raise RuntimeError("Exhausted priorities in _coalesce_types!")

    @classmethod
    def _split_uniques_coalesce_rest(
        cls,
        raw_occurances: Dict[str, List[int]],
        templ_occurances: Dict[str, List[int]],
        split_file: List[Tuple[str, slice, slice, Any]],
    ) -> Iterator[Tuple[str, slice, slice]]:
        """Within each of the compound sections split on unique literals.

        For everything else we coalesce to the dominant type.
        """
        for elem in split_file:
            # Yield anything simple
            if elem[0] in ("simple", "invariant"):
                yield ("literal", elem[1], elem[2])
                continue

            raw_occs = cls._filter_occurances(elem[1], raw_occurances)
            templ_occs = cls._filter_occurances(elem[2], templ_occurances)

            # if we don't have anything to anchor on, then just return (coalescing types)
            if not raw_occs or not templ_occs:
                yield (cls._coalesce_types(elem[3]), elem[1], elem[2])
                continue

            # Do we have any uniques to split on?
            uniques = [
                key
                for key in raw_occs.keys()
                if len(raw_occs[key]) == 1 and len(templ_occs[key]) == 1
            ]
            if not uniques:
                # Nope, just coalesce
                yield (cls._coalesce_types(elem[3]), elem[1], elem[2])
                continue

            # Yield the uniques and coalesce anything between.
            bookmark_idx = 0
            last_end = (elem[1].start, elem[2].start)
            for idx in range(len(elem[3])):
                # Is this one a unique?
                raw = elem[3][idx][0]
                if raw in uniques:
                    # Do we have anything before it to process?
                    if idx > bookmark_idx:
                        yield (
                            cls._coalesce_types(elem[3][bookmark_idx:idx]),
                            # slice up to this unique
                            slice(last_end[0], raw_occs[raw][0]),
                            slice(last_end[1], templ_occs[raw][0]),
                        )
                    # Process the value itself
                    last_end = (
                        raw_occs[raw][0] + len(raw),
                        templ_occs[raw][0] + len(raw),
                    )
                    yield (
                        elem[3][idx][1],
                        # It's a literal so use its length
                        slice(raw_occs[raw][0], last_end[0]),
                        slice(templ_occs[raw][0], last_end[1]),
                    )
                    # Move the bookmark after this position
                    bookmark_idx = idx + 1
            # At the end of the loop deal with any hangover
            if len(elem[3]) > bookmark_idx:
                yield (
                    cls._coalesce_types(elem[3][bookmark_idx : len(elem[3])]),
                    # Slicing is easy here, we have no choice
                    slice(last_end[0], elem[1].stop),
                    slice(last_end[1], elem[2].stop),
                )
