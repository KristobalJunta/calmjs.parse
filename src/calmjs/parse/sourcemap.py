# -*- coding: utf-8 -*-
"""
Source map helpers
"""

from __future__ import unicode_literals
import logging

from calmjs.parse.vlq import encode_mappings

logger = logging.getLogger(__name__)

# for NotImplemented source values
INVALID_SOURCE = 'about:invalid'


class Names(object):
    """
    A class for tracking and reporting of names for usage with source
    maps.
    """

    def __init__(self):
        self._names = {}
        self._current = 0

    def update(self, name):
        """
        Query a name for the relative index value to be added into the
        source map name field (optional 5th element).
        """

        if name is None:
            return

        if name not in self._names:
            # add the name if it isn't already tracked
            self._names[name] = len(self._names)

        result = self._names[name] - self._current
        self._current = self._names[name]
        return result

    def __iter__(self):
        for name, idx in sorted(self._names.items(), key=lambda x: x[1]):
            yield name


class Bookkeeper(object):
    """
    A class for tracking positions

    Set a current position, read out a delta compared to the previous
    for a given attribute
    """

    def __init__(self):
        super(Bookkeeper, self).__setattr__('_prev', {})
        super(Bookkeeper, self).__setattr__('_curr', {})

    def _hasattr(self, attr):
        return all(
            isinstance(check.get(attr, None), int)
            for check in (self._prev, self._curr)
        )

    def __setattr__(self, attr, value):
        """
        Set the current position
        """

        chk = attr[:1] == '_'
        attr = attr[1:] if chk else attr

        if not isinstance(value, int):
            raise TypeError("assignment must be of type 'int'")

        if not self._hasattr(attr) or chk:
            self._curr[attr] = self._prev[attr] = value
        else:
            self._curr[attr], self._prev[attr] = value, self._curr[attr]

    def __getattr__(self, attr):
        chk = attr[:1] == '_'
        attr = attr[1:] if chk else attr
        if not self._hasattr(attr):
            raise AttributeError("'%s' object has no attribute %r" % (
                self.__class__.__name__, attr))
        return self._curr[attr] if chk else self._curr[attr] - self._prev[attr]

    def __delattr__(self, attr):
        if not self._hasattr(attr):
            raise AttributeError("'%s' object has no attribute %r" % (
                self.__class__.__name__, attr))
        self._prev[attr] = self._curr[attr] = 0


def default_book():
    book = Bookkeeper()
    # index of the current file can be implemented/tracked with the
    # Names class.

    # position of the current line that is being written; 0-indexed as
    # there are no existing requirements, and that it maps directly to
    # the length of the string written (usually).
    book.sink_column = 0
    # since the source line/col positions have been implemented as
    # 1-indexed values, so the offset is pre-applied like so.
    book.source_line = 1
    book.source_column = 1
    return book


def normalize_mapping_line(mapping_line, previous_source_column=0):
    """
    Often times the position will remain stable, such that the naive
    process will end up with many redundant values; this function will
    iterate through the line and remove all extra values.
    """

    if not mapping_line:
        return [], previous_source_column

    # Note that while the local record here is also done as a 4-tuple,
    # element 1 and 2 are never used since they are always provided by
    # the segments in the mapping line; they are defined for consistency
    # reasons.

    def regenerate(segment):
        if len(segment) == 5:
            result = (record[0], segment[1], segment[2], record[3], segment[4])
        else:
            result = (record[0], segment[1], segment[2], record[3])
        # reset the record
        # XXX this is insufficient, we need to know exactly where the
        # record is, because for pretty-printing of a long line into
        # proper indentation, this will reset the positions wrongly
        record[:] = [0, 0, 0, 0]
        return result

    # first element of the line; sink column (0th element) is always
    # the absolute value, so always use the provided value sourced from
    # the original mapping_line; the source column (3rd element) is
    # never reset, so if a previous counter exists (which is specified
    # by the optional argument), make use of it to generate the initial
    # normalized segment.
    record = [0, 0, 0, previous_source_column]
    result = []
    regen_next = True

    for segment in mapping_line:
        if not segment:
            # ignore empty records
            continue
        # if the line has not changed, and that the increases of both
        # columns are the same, accumulate the column counter and drop
        # the segment.

        # accumulate the current record first
        record[0] += segment[0]
        if len(segment) == 1:
            # Mark the termination, as 1-tuple determines the end of the
            # previous symbol and denote that whatever follows are not
            # in any previous source files.  So if it isn't recorded,
            # make note of this if it wasn't done already.
            if result and len(result[-1]) != 1:
                result.append((record[0],))
                record[0] = 0
                # the next complete segment will require regeneration
                regen_next = True
            # skip the remaining processing.
            continue

        record[3] += segment[3]

        # 5-tuples are always special case with the remapped identifier
        # name element, and to mark the termination the next token must
        # also be explicitly written (in our case, regenerated).  If the
        # filename or source line relative position changed (idx 1 and
        # 2), regenerate it too.  Finally, if the column offsets differ
        # between source and sink, regenerate.
        if len(segment) == 5 or regen_next or segment[1] or segment[2] or (
                record[0] != record[3]):
            result.append(regenerate(segment))
            regen_next = len(segment) == 5

    # must return the consumed/omitted values.
    return result, record[3]


def write(
        stream_fragments, stream, normalize=True,
        book=None, sources=None, names=None):
    """
    Given an iterable of stream fragments, write it to the stream object
    by using its write method.  Returns a 3-tuple, where the first
    element is the mapping, second element is the list of sources and
    the third being the original names referenced by the given fragment.

    Arguments:

    stream_fragments
        an iterable that only contains StreamFragments
    stream
        an io.IOBase compatible stream object
    normalize
        the default True setting will result in the mappings that were
        returned be normalized to the minimum form.  This will reduce
        the size of the generated source map at the expense of slightly
        lower quality.
    book
        A Bookkeeper instance; if none is provided an instance will be
        created for internal use.  The Bookkeeper instance is used for
        tracking the positions of rows and columns of the input stream.
    sources
        a Names instance for tracking sources; if None is provided, an
        instance will be created for internal use.
    names
        a Names instance for tracking names; if None is provided, an
        instance will be created for internal use.

    A stream fragment tuple must contain the following

    - The string to write to the stream
    - Original starting line of the string; None if not present
    - Original starting column fo the line; None if not present
    - Original string that this fragment represents (i.e. for the case
      where this string fragment was an identifier but got mangled into
      an alternative form); use None if this was not the case.
    - The source of the fragment.  If the first fragment is unspecified,
      the INVALID_SOURCE url will be used (i.e. about:invalid).  After
      that, a None value will be treated as the implicit value, and if
      NotImplemented is encountered, the INVALID_SOURCE url will be used
      also.

    If a number of stream_fragments are to be provided, common instances
    of Bookkeeper (for book) and Names (for sources and names) should be
    provided if they are not chained together.
    """

    if names is None:
        names = Names()

    if sources is None:
        sources = Names()

    if book is None:
        book = default_book()

    # declare state variables and local helpers
    mappings = []

    def push_line():
        # should normalize the current line if possible.
        mappings.append([])
        book._sink_column = 0

    # finalize initial states; the most recent list (mappings[-1]) is
    # the current line
    push_line()
    p_line_len = 0

    for chunk, lineno, colno, original_name, source in stream_fragments:
        # note that lineno/colno are assumed to be both provided or none
        # provided.
        lines = chunk.splitlines(True)
        for line in lines:
            stream.write(line)

            name_id = names.update(original_name)
            # this is a bit of a trick: an unspecified value (None) will
            # simply be treated as the implied value, hence 0.  However,
            # a NotImplemented will be recorded and be convereted to the
            # invalid url at the end.
            source_id = sources.update(source) or 0

            # Two separate checks are done.  As per specification, if
            # either lineno or colno are unspecified, it is assumed that
            # the segment is unmapped - append a termination (1-tuple)
            #
            # Otherwise, note that if this segment is the beginning of a
            # line, and that an implied source colno/linecol were
            # provided (i.e. value of 0), and that the string is empty,
            # it can be safely skipped, since it is an implied and
            # unmapped indentation

            if lineno is None or colno is None:
                mappings[-1].append((book.sink_column,))
            else:
                if lineno:
                    # a new lineno is provided, apply it to the book and
                    # use the result as the written value.
                    book.source_line = lineno
                    source_line = book.source_line
                else:
                    # no change in offset, do not calculate and assume
                    # the value to be written is unchanged.
                    source_line = 0

                # if the provided colno is to be implied, calculate it
                # based on the previous line length plus the previous
                # real source column value, otherwise standard value
                # for tracking.
                if colno:
                    book.source_column = colno
                else:
                    book.source_column = book._source_column + p_line_len

                if original_name is not None:
                    mappings[-1].append((
                        book.sink_column, source_id,
                        source_line, book.source_column,
                        name_id
                    ))
                else:
                    mappings[-1].append((
                        book.sink_column, source_id,
                        source_line, book.source_column
                    ))

            # doing this last to update the position for the next line
            # or chunk for the relative values based on what was added
            if line[-1:] in '\r\n':
                # Note: this HAS to be an edge case and should never
                # happen, but this has the potential to muck things up.
                # Since the parent only provided the start, will need
                # to manually track the chunks internal to here.
                # This normally shouldn't happen with sane parsers
                # and lexers, but this assumes that no further symbols
                # aside from the new lines got inserted.
                colno = (
                    colno if colno in (0, None) else
                    colno + len(line.rstrip()))
                p_line_len = 0
                push_line()

                if line is not lines[-1]:
                    logger.warning(
                        'text in the generated document at line %d may be '
                        'mapped incorrectly due to trailing newline character '
                        'in provided text fragment.', len(mappings)
                    )
                    logger.info(
                        'text in stream fragments should not have trailing '
                        'characters after a new line, they should be split '
                        'off into a separate fragment.'
                    )
            else:
                p_line_len = len(line)
                book.sink_column = book._sink_column + p_line_len

    # normalize everything
    if normalize:
        column = 0
        result = []
        for ml in mappings:
            new_ml, column = normalize_mapping_line(ml, column)
            result.append(new_ml)
        mappings = result
    list_sources = [
        INVALID_SOURCE if s == NotImplemented else s for s in sources
    ] or [INVALID_SOURCE]
    return mappings, list_sources, list(names)


def encode_sourcemap(filename, mappings, sources, names=[]):
    """
    Take a filename, mappings and names produced from the write function
    and sources.  As the write function currently does not handle the
    tracking of source filenames, the sources should be a list of one
    element with the original filename.

    Arguments

    filename
        The target filename that the stream was or to be written to.
        The stream being the argument that was supplied to the write
        function
    mappings
        The raw unencoded mappings produced by write, which is returned
        as its second element.
    sources
        List of original source filenames.  When used in conjunction
        with the above write function, it should be a list of one item,
        being the path to the original filename.
    names
        The list of original names generated by write, which is returned
        as its first element.

    Returns a dict which can be JSON encoded into a sourcemap file.

    Example usage:

    >>> from io import StringIO
    >>> from calmjs.parse import es5
    >>> from calmjs.parse.unparsers.es5 import pretty_printer
    >>> from calmjs.parse.sourcemap import write, encode_sourcemap
    >>> program = es5(u"var i = 'hello';")
    >>> stream = StringIO()
    >>> printer = pretty_printer()
    >>> sourcemap = encode_sourcemap(
    ...     'demo.min.js', *write(printer(program), stream))
    """

    return {
        "version": 3,
        "sources": sources,
        "names": names,
        "mappings": encode_mappings(mappings),
        "file": filename,
    }
