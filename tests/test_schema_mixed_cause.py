"""A child's failure that mixes an issue with a defect keeps both, and the
issue still says where it happened (Effect's ``Composite`` of a
``Pointer`` over the cause)."""

from typing import TypedDict

from pyfect import effect as fx
from pyfect import schema as S
from pyfect.cause import Cause, Die, Fail
from pyfect.exit import Failure
from pyfect.result import Ok
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.issue import InvalidValue

_MIXED = Cause((Fail(InvalidValue({"message": "bad"})), Die(RuntimeError("defect"))))


def _mixed(value: str, options: S.ParseOptions) -> fx.Effect[str, InvalidValue]:
    return fx.fail_cause(_MIXED)


_FAILING = S.String.pipe(S.decode(T.Transformation(G.transform_effect(_mixed), G.passthrough())))


class _A(TypedDict):
    a: str


def _message_and_defect(schema: S.Codec[object, object], input: object) -> str:
    exit = S.decode_unknown_exit(schema)(input)
    assert isinstance(exit, Failure)
    assert any(isinstance(r, Die) for r in exit.cause.reasons)
    match exit.cause.find_error():
        case Ok(error):
            return error.message
        case other:
            raise AssertionError(other)


def test_a_struct_key_keeps_its_path():
    assert _message_and_defect(S.Struct(_A, a=_FAILING), {"a": "x"}) == 'bad\n  at ["a"]'


def test_a_tuple_element_keeps_its_path():
    assert _message_and_defect(S.Tuple(_FAILING), ["x"]) == "bad\n  at [0]"
