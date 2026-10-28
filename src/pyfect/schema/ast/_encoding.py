"""Encodings: how a node is reached from what it decodes (Effect's ``Link``
and ``Encoding``).

A node's ``encoding`` is a chain of links, the last one the most encoded.
Decoding parses the input with the last link's ``to``, applies that link's
transformation, parses with the previous link's ``to``, and so on; the
first link's transformation gives a value the node itself then parses (with
its checks). Flipping a node reverses the chain and flips each
transformation, so encoding is decoding the flipped node.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

from pyfect.exit import Success
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._result import MISSING, ParseResult, flat_map, map_issue
from pyfect.schema.issue import Encoding as EncodingIssue
from pyfect.schema.issue import reported

if TYPE_CHECKING:
    from pyfect.schema.ast._base import AST


class LinkTransformation(Protocol):
    """What a link applies: a ``transformation.Transformation`` (a getter
    each way) or a ``transformation.Middleware`` (a function of the whole
    parse each way)."""

    @property
    def sees_failures(self) -> bool:
        """Its decoding runs on failures too (a middleware that may recover),
        so a union cannot pick its member by the source's kind or literals."""
        ...

    def flip(self) -> LinkTransformation: ...

    def decode_result(self, result: ParseResult, options: ParseOptions) -> ParseResult:
        """The decoded side of ``result``, the parse of the source."""
        ...


@dataclass(frozen=True, slots=True)
class Link:
    """``transformation`` from values of ``to`` (Effect's ``Link``)."""

    to: AST
    transformation: LinkTransformation


type Encoding = tuple[Link, *tuple[Link, ...]]


def decode_chain(ast: AST, links: Encoding, input: object, options: ParseOptions) -> ParseResult:
    """``input`` decoded through ``links``, ``ast``'s encoding, then parsed
    by ``ast`` itself; an issue raised on the way is wrapped in
    ``Encoding``."""
    result = links[-1].to.parse(input, options)
    for i in range(len(links) - 1, -1, -1):
        result = links[i].transformation.decode_result(result, options)
        if i:
            node = links[i - 1].to
            result = flat_map(result, lambda value, node=node: node.parse(value, options))
    if type(result) is not Success:
        shown = None if input is MISSING else reported(input, options)
        result = map_issue(result, lambda issue: EncodingIssue(ast, issue, shown))
    return flat_map(result, lambda value: ast.parse_local(value, options))


def flip_encoding(ast: AST, links: Encoding) -> AST:
    """The node that encodes what ``ast`` decodes: its most encoded node,
    with ``links`` (``ast``'s encoding) reversed (Effect's ``flipEncoding``)."""
    flipped = [Link(replace(ast, encoding=None).flip(), links[0].transformation.flip())]
    for i in range(1, len(links)):
        flipped.insert(0, Link(links[i - 1].to.flip(), links[i].transformation.flip()))
    to = links[-1].to.flip()
    chain = (*to.encoding, *flipped) if to.encoding else tuple(flipped)
    return replace(to, encoding=chain)


def decode_to[A: AST](from_: AST, to: A, transformation: LinkTransformation) -> A:
    """``to``, decoding from values of ``from_`` through ``transformation``
    (Effect's ``decodeTo``): a link appended to ``to``'s encoding."""
    link = Link(from_, transformation)
    return replace(to, encoding=(*to.encoding, link) if to.encoding else (link,))


def optional_key[A: AST](ast: A) -> A:
    """``ast`` as a struct key that may be missing on the encoded side, down
    to its most encoded node (Effect's ``optionalKey``)."""
    encoding = ast.encoding
    if encoding is None:
        return ast if ast.optional_key else replace(ast, optional_key=True)
    last = encoding[-1]
    chain: Encoding = (*encoding[:-1], Link(optional_key(last.to), last.transformation))
    return replace(ast, encoding=chain, optional_key=True)


def to_encoded(ast: AST) -> AST:
    """The node's encoded side, as a node of its own (Effect's ``toEncoded``)."""
    return ast.flip().to_type()
