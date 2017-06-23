# -*- coding: utf-8 -*-
"""
Base pretty printing state and visitor function.
"""

from calmjs.parse.pptypes import Token
from calmjs.parse.pptypes import LayoutRuleChunk


class PrettyPrintState(object):
    """
    Provide storage and lookup for the stored definitions and the
    handlers, which is documented by the constructor below.

    Instances of this class also provides two forms of lookup, via
    calling this with a Rule, or lookup using a Node type.

    Calling on an instance of this object with a Rule (typically either
    a Token instance, or a Layout type/class object) will return the
    associated handler that was set up initially for a given instance.

    Accessing via a Node type as a key will return the definition that
    was initially set up for a given instance.

    The default implementation also provide a couple properties for ease
    of layout customization, which are the indent character and the
    newline character.  As certain users and/or platforms expect certain
    character sequences for these outputs, they can be specified in the
    constructor for this class.

    While this class can be used (it was originally conceived) as a
    generic object that allow arbitrary assignments of arguments for
    consumption by layout functions, it's better to have a dedicated
    class that provide instance methods that plug into this.  See the
    ``.visitors.layout`` module for the Indentation class and its
    factory function for an example on how this could be set up.
    """

    # TODO move definitions to first argument, provide newline/indent
    def __init__(
            self, definitions, token_handler, layout_handlers,
            indent_str='  ', newline_str='\n'):
        """
        The constructor takes three arguments.

        definitions
            A mapping from the names of a Node to their definitions; a
            definition is a tuple of rules for describing how a
            particular Node should be rendered.  The Nodes are described
            in the asttypes module, while the Rules are described in the
            pptypes module.

        token_handler
            The handler that will deal with tokens.  It must be a
            callable that accepts four arguments

            token
                the token instance that will do the invocation
            state
                an instance of this class
            node
                a Node instance (from asttypes)
            value
                the value that was derived by the token based on its
                implementation.

        layout_handlers
            A map (dictionary) from Layout types to the handlers, which
            are callables that accepts these four arguments

            state
                an instance of this class
            node
                a Node instance (from asttypes)
            before
                a value that was yielded by the previous token
            after
                a value to be yielded by the subsequent token

        indent_str
            The string used to indent a line with.  Default is '  '.
            This attribute will be provided as the property
            ``indent_str``.

        newline_str
            The string used for renderinga new line with.  Default is
            <LF> (line-feed, or '\\n').  This attribute will be provided
            as the property ``newline_str``.
        """

        self.__token_handler = token_handler
        self.__layout_handlers = {}
        self.__layout_handlers.update(layout_handlers)
        self.__definitions = {}
        self.__definitions.update(definitions)
        self.__indent_str = indent_str
        self.__newline_str = newline_str

    def __getitem__(self, key):
        # TODO figure out how to do proper lookup by the type, rather
        # than this string hack.
        return self.__definitions[key.__class__.__name__]

    def __call__(self, rule):
        if isinstance(rule, Token):
            return self.__token_handler
        else:
            return self.__layout_handlers.get(rule)

    @property
    def indent_str(self):
        return self.__indent_str

    @property
    def newline_str(self):
        return self.__newline_str


def pretty_print_visitor(state, node, definition):
    """
    The default, standalone visitor function following the standard
    argument format, where the first argument is a PrettyPrintState,
    second being the node, third being the definition tuple to follow
    from for generating a rendering of the node.

    While the state object is able to provide the lookup directly, this
    extra definition argument allow more flexibility in having Token
    subtypes being able to provide specific definitions also that may
    be required, such as the generation of optional rendering output.
    """

    def visitor(state, node, definition):
        for rule in definition:
            if isinstance(rule, Token):
                # tokens are callables that will generate the chunks
                # that will ultimately form the output, so simply invoke
                # that with this function, the state and the node.
                for chunk in rule(visitor, state, node):
                    yield chunk
            else:
                # Otherwise, it's simply a layout class (inert and does
                # nothing aside from serving as a marker).  Lookup the
                # handler by invoking it directly like so:
                handler = state(rule)
                if handler:
                    yield LayoutRuleChunk(rule, handler, node)

    def process_layouts(layout_rule_chunks, last_chunk, chunk):
        before_text = last_chunk.text if last_chunk else None
        after_text = chunk.text if chunk else None
        # the text that was yielded by the previous layout handler
        prev_text = None

        compacted_rule = tuple(c.rule for c in layout_rule_chunks)
        compacted_handler = state(compacted_rule)
        compacted = None if not compacted_handler else [LayoutRuleChunk(
            compacted_rule, compacted_handler, layout_rule_chunks[0].rule)]
        # Do one final lookup since we have a series of layouts that
        # could be compacted into a single rule; if the compacted layout
        # rule was present, use that instead.
        for lr_chunk in (compacted if compacted else layout_rule_chunks):
            gen = lr_chunk.handler(
                state, lr_chunk.node, before_text, after_text, prev_text)
            if not gen:
                continue
            for chunk_from_layout in gen:
                yield chunk_from_layout
                prev_text = chunk_from_layout.text
        layout_rule_chunks.clear()

    last_chunk = None
    layout_rule_chunks = []

    for chunk in visitor(state, node, definition):
        if isinstance(chunk, LayoutRuleChunk):
            layout_rule_chunks.append(chunk)
        else:
            # process layout rule chunks that had been cached.
            for layout in process_layouts(
                    layout_rule_chunks, last_chunk, chunk):
                yield layout
            yield chunk
            last_chunk = chunk

    # process the remaining layout rule chunks.
    for layout in process_layouts(layout_rule_chunks, last_chunk, None):
        yield layout
