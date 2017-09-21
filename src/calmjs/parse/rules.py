# -*- coding: utf-8 -*-
"""
Rules setup functions for standard Unparser constructors.  All functions
here return a rule setup function that returns a working and complete
set of handlers for the desired functionality as designed.  While the
rules defined here can mix, note that the Unparser will treat the later
rules as having prescedence for any rule conflicts.
"""

from calmjs.parse.ruletypes import (
    Space,
    OptionalSpace,
    RequiredSpace,
    Newline,
    OptionalNewline,
    Indent,
    Dedent,
    Resolve,
)
from calmjs.parse.handlers.core import (
    rule_handler_noop,

    token_handler_unobfuscate,

    layout_handler_space_imply,
    layout_handler_space_optional_pretty,
    layout_handler_space_minimum,

    default_rules,
    minimum_rules,
)
from calmjs.parse.handlers.indentation import Indentator
from calmjs.parse.handlers.obfuscation import Obfuscator

__all__ = ['default', 'minimum', 'indent', 'obfuscate']


def default():
    """
    A default set of handlers
    """

    return default_rules


def minimum():
    """
    The minimum required set of handlers for the results to still be
    considered valid code.  This is due to the fact that a set of
    minimum whitespace handlers are still needed.
    """

    return minimum_rules


def indent(indent_str=None):
    """
    A complete, standalone indent ruleset.

    Arguments:

    indent_str
        The string used for indentation.  Defaults to None, which will
        defer the value used to the one provided by the Dispatcher.
    """

    def indentation_rule():
        inst = Indentator(indent_str)
        return {'layout_handlers': {
            Space: layout_handler_space_imply,
            OptionalSpace: layout_handler_space_optional_pretty,
            RequiredSpace: layout_handler_space_imply,
            Indent: inst.layout_handler_indent,
            Dedent: inst.layout_handler_dedent,
            Newline: inst.layout_handler_newline,
            OptionalNewline: inst.layout_handler_newline_optional,
            (Indent, Newline, Dedent): rule_handler_noop,
        }}
    return indentation_rule


def obfuscate(
        obfuscate_globals=False,
        shadow_funcname=False,
        reserved_keywords=()):
    """
    The name obfuscation ruleset.

    Arguments:

    obfuscate_globals
        If true, identifier names on the global scope will also be
        obfuscated.  Default is False.
    shadow_funcname
        If True, permit the shadowing of the name of named functions by
        names within the scope it defines.  Default is False.
    reserved_keywords
        A tuple of strings that should not be generated as obfuscated
        identifiers.
    """

    def name_obfuscation_rules():
        inst = Obfuscator(
            obfuscate_globals=obfuscate_globals,
            shadow_funcname=shadow_funcname,
            reserved_keywords=reserved_keywords,
        )
        return {
            'token_handler': token_handler_unobfuscate,
            'layout_handlers': {
                Space: layout_handler_space_minimum,
                OptionalSpace: layout_handler_space_minimum,
                RequiredSpace: layout_handler_space_imply,
            },
            'deferrable_handlers': {
                Resolve: inst.resolve,
            },
            'prewalk_hooks': [
                inst.prewalk_hook,
            ],
        }
    return name_obfuscation_rules