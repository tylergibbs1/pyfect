"""Ports of Effect's ``test/reactivity/AsyncResult.test.ts``.

``is not equal to an unrelated Equal value with the same tag and hash``
builds a plain object implementing ``Equal``; the Python analog is an
object with the same tag, fields and hash that is not an ``AsyncResult``.
The builder's handlers take ``(value, result)`` as Effect's do; Python
lambdas name both.
"""

from typing import Any

from pyfect import cause as cause_
from pyfect.option import Some
from pyfect.reactivity import async_result
from pyfect.reactivity.async_result import Failure
from pyfect.schema import TaggedError


def test_waiting_dispatches_with_optional_options() -> None:
    """waiting dispatches with optional options"""
    result = async_result.success(1)
    assert async_result.waiting(result).waiting is True
    assert async_result.waiting(result, touch=False).waiting is True
    assert async_result.waiting()(result).waiting is True
    assert async_result.waiting(touch=False)(result).waiting is True


class _Lookalike:
    _tag = "Initial"
    waiting = False

    def __eq__(self, other: object) -> bool:
        return NotImplemented

    def __hash__(self) -> int:
        return hash(async_result.initial())


def test_is_not_equal_to_an_unrelated_equal_value_with_the_same_tag_and_hash() -> None:
    """is not equal to an unrelated Equal value with the same tag and hash"""
    result: Any = async_result.initial()
    assert result != _Lookalike()
    assert hash(result) == hash(_Lookalike())


_CAUSE = cause_.fail("offline")


def _refetch_failed() -> async_result.AsyncResult[int, str]:
    return async_result.failure(
        _CAUSE, previous_success=Some(async_result.success(1)), waiting=True
    )


def test_all_rebuilds_a_failed_inputs_previous_success_in_the_combined_record_shape() -> None:
    """all / rebuilds a failed input's previous success in the combined record shape"""
    result = async_result.all(
        {
            "a": _refetch_failed(),
            "b": async_result.success("x"),
            "c": 2,
            "d": async_result.failure(
                cause_.fail("later"), previous_success=Some(async_result.success(3))
            ),
        }
    )
    assert isinstance(result, Failure)
    assert result.cause == _CAUSE
    assert result.waiting is True
    found = async_result.value(result)
    assert found is not None
    assert found.value == {"a": 1, "b": "x", "c": 2, "d": 3}


def test_all_rebuilds_a_failed_inputs_previous_success_in_the_combined_tuple_shape() -> None:
    """all / rebuilds a failed input's previous success in the combined tuple shape"""
    result = async_result.all([async_result.success("x"), _refetch_failed()])
    found = async_result.value(result)
    assert found is not None
    assert found.value == ["x", 1]


def test_all_drops_the_previous_success_when_another_input_has_no_value() -> None:
    """all / drops the previous success when another input has no value"""
    result = async_result.all({"a": _refetch_failed(), "b": async_result.initial()})
    assert isinstance(result, Failure)
    assert result.cause == _CAUSE
    assert result.waiting is True
    assert async_result.value(result) is None


def test_builder_on_defect_handles_defects() -> None:
    """builder / onDefect handles defects"""
    defect = RuntimeError("boom")
    result: async_result.AsyncResult[int, str] = async_result.failure(cause_.die(defect))
    handled = (
        async_result.builder(result).on_defect(lambda received, _: received).or_else(lambda: None)
    )
    assert handled is defect


def test_builder_on_defect_does_not_handle_typed_errors() -> None:
    """builder / onDefect does not handle typed errors"""
    handled = (
        async_result.builder(async_result.fail("error"))
        .on_defect(lambda _defect, _result: "defect")
        .or_else(lambda: "fallback")
    )
    assert handled == "fallback"


class NotFoundError(TaggedError):
    resource: str


def test_builder_exhaustive_returns_output_when_typed_errors_are_handled() -> None:
    """builder / exhaustive returns output when typed errors are handled"""
    handled = (
        async_result.builder(async_result.fail(NotFoundError(resource="user")))
        .on_error_tag(NotFoundError, lambda error, _: f"missing:{error.resource}")
        .on_defect(lambda _defect, _result: "failure")
        .on_interrupt(lambda _ids, _result: "interrupt")
        .exhaustive()
    )
    assert handled == "missing:user"
