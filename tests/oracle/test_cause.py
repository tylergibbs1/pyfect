"""Ports of Effect's ``Cause.test.ts``.

Omitted, with the reason:

- runtime JSON / Node inspection, ``TypeId``, ``ReasonTypeId`` and the
  ``*TypeId`` constants: JS runtime branding; ``isinstance`` and the
  dataclass ``repr`` are Python's forms.
- ``isCause``, ``isReason``, ``isFailReason``, ``isDieReason``,
  ``isInterruptReason`` "returns false for non-... values" and the
  ``make*Reason`` constructors: ``Cause``, ``Fail``, ``Die`` and
  ``Interrupt`` are classes, so ``isinstance`` and the class itself are the
  guard and the constructor. The positive cases are ported with
  ``isinstance``.
- data-last (pipeable) forms of ``map`` and ``combine``: pyfect spells them
  as the ``map`` method and ``+``.
- ``findErrorOption``: ``find_error`` already returns ``Ok`` / ``Err``.
- ``prettyErrors`` "preserves falsy Error causes" and "restores
  Error.stackTraceLimit": JS ``Error.cause`` / ``stackTraceLimit`` quirks.
- ``pretty`` "cuts the stack ... internal frame" and the two
  "does not render internal frames" cases: ported in
  ``tests/test_cause_pretty.py`` where they apply.
- ``annotate`` "works in data-last (pipeable) form": ``annotate`` is a
  method. ``StackTrace`` and ``InterruptorStackTrace`` are tags in
  ``pyfect.tracer``, next to the stack frames they hold.
- ``isNoSuchElementError``: ``isinstance`` is the guard.
- ``isUnknownError`` and the ``*TypeId`` constants of the error classes:
  ``isinstance`` is the guard. ``UnknownError``'s cause is the ``Exception``
  that was raised (Python only raises exceptions), so it is ported with one.
- ``TimeoutError``: pyfect's ``TimeoutException`` always carries the
  ``duration`` that ran out (``tests/test_concurrency.py``), so it has no
  message-only constructor to port.
- ``isDone`` "returns true for Done values" / "returns false for other
  values" and ``DoneTypeId``: ``isinstance(x, fx.Done)`` is the guard.
- ``IllegalArgumentError``, ``ExceededCapacityError``: not ported yet; no
  v4 queue strategy raises ``ExceededCapacityError``.
"""

import traceback

import pyfect as fx
from pyfect import cause
from pyfect.cause import Cause, Die, EmptyCauseError, Fail, Interrupt, UnhandledError
from pyfect.result import Err, Ok
from pyfect.tracer import InterruptorStackTrace, StackTrace


def _reason(c: Cause[object]) -> object:
    return c.reasons[0]


# isCause / isReason / is*Reason


def test_returns_true_for_cause_values() -> None:
    """returns true for Cause values"""
    for c in (cause.empty, cause.fail("error"), cause.die(ValueError()), cause.interrupt(1)):
        assert isinstance(c, Cause)


def test_returns_true_for_reasons_extracted_from_a_cause() -> None:
    """returns true for reasons extracted from a cause"""
    assert isinstance(cause.fail("error").reasons[0], Fail | Die | Interrupt)


def test_narrows_fail_reasons() -> None:
    """narrows Fail reasons"""
    assert isinstance(_reason(cause.fail("error")), Fail)


def test_narrows_die_reasons() -> None:
    """narrows Die reasons"""
    assert isinstance(_reason(cause.die(ValueError())), Die)


def test_narrows_interrupt_reasons() -> None:
    """narrows Interrupt reasons"""
    assert isinstance(_reason(cause.interrupt(1)), Interrupt)


def test_rejects_die_and_interrupt_reasons() -> None:
    """rejects Die and Interrupt reasons"""
    assert not isinstance(_reason(cause.die(ValueError())), Fail)
    assert not isinstance(_reason(cause.interrupt(1)), Fail)


def test_rejects_fail_and_interrupt_reasons() -> None:
    """rejects Fail and Interrupt reasons"""
    assert not isinstance(_reason(cause.fail("error")), Die)
    assert not isinstance(_reason(cause.interrupt(1)), Die)


def test_rejects_fail_and_die_reasons() -> None:
    """rejects Fail and Die reasons"""
    assert not isinstance(_reason(cause.fail("error")), Interrupt)
    assert not isinstance(_reason(cause.die(ValueError())), Interrupt)


# empty


def test_has_no_reasons() -> None:
    """has no reasons"""
    assert cause.empty.reasons == ()


def test_empty_is_a_cause() -> None:
    """is a Cause"""
    assert isinstance(cause.empty, Cause)


# fail / die / interrupt


def test_creates_a_cause_with_a_single_fail_reason() -> None:
    """creates a cause with a single Fail reason"""
    assert cause.fail("error").reasons == (Fail("error"),)


def test_preserves_the_error_value() -> None:
    """preserves the error value"""
    assert cause.fail("error").failures == ("error",)


def test_works_with_various_error_types() -> None:
    """works with various error types"""
    obj = {"key": "value"}
    assert cause.fail(obj).failures[0] is obj


def test_creates_a_cause_with_a_single_die_reason() -> None:
    """creates a cause with a single Die reason"""
    defect = ValueError("defect")
    assert cause.die(defect).reasons == (Die(defect),)


def test_preserves_the_defect_value() -> None:
    """preserves the defect value"""
    defect = ValueError("defect")
    assert cause.die(defect).defects[0] is defect


def test_works_with_error_instances() -> None:
    """works with Error instances"""
    err = RuntimeError("boom")
    assert cause.die(err).defects == (err,)


def test_creates_a_cause_with_a_single_interrupt_reason() -> None:
    """creates a cause with a single Interrupt reason"""
    assert cause.interrupt(123).reasons == (Interrupt(123),)


def test_preserves_the_fiber_id() -> None:
    """preserves the fiber ID"""
    match _reason(cause.interrupt(42)):
        case Interrupt(fiber_id=fid):
            assert fid == 42
        case other:
            raise AssertionError(other)


def test_allows_undefined_fiber_id() -> None:
    """allows undefined fiber ID"""
    assert cause.interrupt().reasons == (Interrupt(None),)


# fromReasons


def test_creates_a_cause_from_an_array_of_reasons() -> None:
    """creates a cause from an array of reasons"""
    assert len(cause.from_reasons([Fail("err1"), Fail("err2")]).reasons) == 2


def test_creates_empty_cause_from_empty_array() -> None:
    """creates empty cause from empty array"""
    assert cause.from_reasons([]).reasons == ()


def test_supports_mixed_reason_types() -> None:
    """supports mixed reason types"""
    c = cause.from_reasons([Fail("error"), Die(ValueError()), Interrupt(1)])
    assert len(c.reasons) == 3


# hasFails / hasDies / hasInterrupts / hasInterruptsOnly


def test_returns_true_when_cause_has_fail_reasons() -> None:
    """returns true when cause has Fail reasons"""
    assert cause.fail("error").has_fails


def test_returns_false_when_cause_has_no_fail_reasons() -> None:
    """returns false when cause has no Fail reasons"""
    assert not cause.die(ValueError()).has_fails
    assert not cause.interrupt(1).has_fails
    assert not cause.empty.has_fails


def test_returns_true_for_combined_cause_with_at_least_one_fail() -> None:
    """returns true for combined cause with at least one Fail"""
    assert (cause.die(ValueError()) + cause.fail("error")).has_fails


def test_returns_true_when_cause_has_die_reasons() -> None:
    """returns true when cause has Die reasons"""
    assert cause.die(ValueError()).has_dies


def test_returns_false_when_cause_has_no_die_reasons() -> None:
    """returns false when cause has no Die reasons"""
    assert not cause.fail("error").has_dies
    assert not cause.interrupt(1).has_dies
    assert not cause.empty.has_dies


def test_returns_true_when_cause_has_interrupt_reasons() -> None:
    """returns true when cause has Interrupt reasons"""
    assert cause.interrupt(1).has_interrupts


def test_returns_false_when_cause_has_no_interrupt_reasons() -> None:
    """returns false when cause has no Interrupt reasons"""
    assert not cause.fail("error").has_interrupts
    assert not cause.die(ValueError()).has_interrupts
    assert not cause.empty.has_interrupts


def test_returns_true_when_all_reasons_are_interrupts() -> None:
    """returns true when all reasons are Interrupts"""
    assert cause.interrupt(1).has_interrupts_only
    assert (cause.interrupt(1) + cause.interrupt(2)).has_interrupts_only


def test_returns_false_for_empty_cause() -> None:
    """returns false for empty cause"""
    assert not cause.empty.has_interrupts_only


def test_returns_false_when_mixed_with_other_reason_types() -> None:
    """returns false when mixed with other reason types"""
    assert not (cause.interrupt(1) + cause.fail("error")).has_interrupts_only


# squash


def test_returns_the_first_fail_even_after_an_interrupt_and_a_defect() -> None:
    """returns the first Fail even after an interrupt and a defect"""
    c = cause.from_reasons(
        [Interrupt(1), Die(RuntimeError("defect")), Fail("first"), Fail("second")]
    )
    squashed = c.squash()
    assert isinstance(squashed, UnhandledError)
    assert squashed.error == "first"
    first = ValueError("first")
    assert cause.from_reasons([Die(RuntimeError("defect")), Fail(first)]).squash() is first


def test_returns_the_first_die_when_there_are_no_fails() -> None:
    """returns the first Die when there are no Fails"""
    first = RuntimeError("first")
    c = cause.from_reasons([Interrupt(1), Die(first), Die(RuntimeError("second"))])
    assert c.squash() is first


def test_reports_an_interrupt_only_cause() -> None:
    """reports an interrupt-only cause"""
    err = cause.interrupt(1).squash()
    assert isinstance(err, fx.Interrupted)
    assert str(err) == "All fibers interrupted without error"


def test_reports_an_empty_cause() -> None:
    """reports an empty cause"""
    err = cause.empty.squash()
    assert isinstance(err, EmptyCauseError)
    assert str(err) == "Empty cause"


# findFail / findError / findDie / findDefect / findInterrupt


def test_returns_success_with_the_first_fail_reason() -> None:
    """returns success with the first Fail reason"""
    assert cause.fail("error").find_fail() == Fail("error")


def test_find_fail_returns_failure_when_no_fail_reason_exists() -> None:
    """returns failure when no Fail reason exists"""
    defect = cause.die(ValueError())
    assert defect.find_fail() == defect


def test_returns_failure_for_empty_cause() -> None:
    """returns failure for empty cause"""
    assert cause.empty.find_fail() == cause.empty


def test_returns_success_with_the_error_value() -> None:
    """returns success with the error value"""
    assert cause.fail("error").find_error() == Ok("error")


def test_find_error_returns_failure_when_no_fail_reason_exists() -> None:
    """returns failure when no Fail reason exists"""
    defect = cause.die(ValueError())
    assert defect.find_error() == Err(defect)


def test_returns_success_with_the_first_die_reason() -> None:
    """returns success with the first Die reason"""
    defect = ValueError("defect")
    assert cause.die(defect).find_die() == Die(defect)


def test_find_die_returns_failure_when_no_die_reason_exists() -> None:
    """returns failure when no Die reason exists"""
    assert cause.fail("error").find_die() is None


def test_returns_success_with_the_defect_value() -> None:
    """returns success with the defect value"""
    defect = ValueError("defect")
    assert cause.die(defect).find_defect() is defect


def test_find_defect_returns_failure_when_no_die_reason_exists() -> None:
    """returns failure when no Die reason exists"""
    assert cause.fail("error").find_defect() is None


def test_returns_success_with_the_first_interrupt_reason() -> None:
    """returns success with the first Interrupt reason"""
    assert cause.interrupt(42).find_interrupt() == Interrupt(42)


def test_returns_failure_when_no_interrupt_reason_exists() -> None:
    """returns failure when no Interrupt reason exists"""
    assert cause.fail("error").find_interrupt() is None


# interruptors / filterInterruptors


def test_returns_a_set_of_fiber_ids() -> None:
    """returns a set of fiber IDs"""
    assert (cause.interrupt(1) + cause.interrupt(2)).interruptors == {1, 2}


def test_returns_empty_set_for_non_interrupt_causes() -> None:
    """returns empty set for non-interrupt causes"""
    assert cause.fail("error").interruptors == frozenset()
    assert cause.empty.interruptors == frozenset()


def test_excludes_undefined_fiber_ids_from_set() -> None:
    """excludes undefined fiber IDs from set"""
    assert cause.interrupt().interruptors == frozenset()


def test_returns_success_with_fiber_id_set_when_interrupts_exist() -> None:
    """returns success with fiber ID set when interrupts exist"""
    assert cause.interrupt(1).filter_interruptors() == {1}
    assert cause.interrupt().filter_interruptors() == frozenset()


def test_returns_failure_when_no_interrupts_exist() -> None:
    """returns failure when no interrupts exist"""
    assert cause.fail("error").filter_interruptors() is None


# map


def test_transforms_error_values_in_fail_reasons_data_first() -> None:
    """transforms error values in Fail reasons (data-first)"""
    assert cause.fail("error").map(str.upper) == cause.fail("ERROR")


def test_does_not_affect_die_reasons() -> None:
    """does not affect Die reasons"""
    c = cause.die(ValueError())
    assert c.map(lambda _: "should not appear") == c


def test_does_not_affect_interrupt_reasons() -> None:
    """does not affect Interrupt reasons"""
    c = cause.interrupt(1)
    assert c.map(lambda _: "should not appear") == c


def test_maps_empty_cause_to_empty_cause() -> None:
    """maps empty cause to empty cause"""
    assert cause.empty.map(lambda _: "x") == cause.empty


# combine


class Collision:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return 0

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Collision) and self.value == other.value


def test_preserves_unequal_reasons_with_colliding_hashes_while_removing_duplicates() -> None:
    """preserves unequal reasons with colliding hashes while removing duplicates"""
    first = Fail(Collision("first"))
    second = Fail(Collision("second"))
    duplicate = Fail(Collision("first"))
    assert hash(first) == hash(second)
    assert first != second

    combined = cause.from_reasons([first, second, first]) + cause.from_reasons([duplicate, second])
    assert len(combined.reasons) == 2
    assert combined.reasons[0] is first
    assert combined.reasons[1] is second
    assert combined + cause.from_reasons([duplicate]) is combined


def test_merges_two_causes_data_first() -> None:
    """merges two causes (data-first)"""
    assert len((cause.fail("a") + cause.fail("b")).reasons) == 2


def test_combining_with_empty_returns_the_other_cause() -> None:
    """combining with empty returns the other cause"""
    c = cause.fail("error")
    assert c + cause.empty is c
    assert cause.empty + c is c


def test_combines_mixed_reason_types() -> None:
    """combines mixed reason types"""
    combined = cause.fail("error") + (cause.die(ValueError()) + cause.interrupt(1))
    assert len(combined.reasons) == 3


# prettyErrors


def test_converts_fail_with_error_to_array_of_errors() -> None:
    """converts Fail with Error to array of Errors"""
    errors = cause.fail(ValueError("boom")).pretty_errors()
    assert len(errors) == 1
    assert "boom" in str(errors[0])


def test_converts_fail_with_string_to_error() -> None:
    """converts Fail with string to Error"""
    errors = cause.fail("string error").pretty_errors()
    assert len(errors) == 1
    assert isinstance(errors[0], UnhandledError)
    assert errors[0].error == "string error"


def test_converts_die_to_error() -> None:
    """converts Die to Error"""
    defect = RuntimeError("defect")
    assert cause.die(defect).pretty_errors() == (defect,)


def test_returns_interrupterror_for_interrupt_only_cause() -> None:
    """returns InterruptError for interrupt-only cause"""
    errors = cause.interrupt(1).pretty_errors()
    assert len(errors) == 1
    assert isinstance(errors[0], fx.Interrupted)
    assert errors[0].__notes__ == ["interrupted by fiber #1"]


def test_handles_empty_cause() -> None:
    """handles empty cause"""
    assert cause.empty.pretty_errors() == ()


def test_stops_at_a_cyclic_error_cause() -> None:
    """stops at a cyclic Error cause"""
    a = ValueError("a")
    b = ValueError("b")
    b.__cause__ = a
    a.__cause__ = b
    (error,) = cause.fail(a).pretty_errors()
    assert error is a
    rendered = "".join(traceback.format_exception(error))
    assert "ValueError: a" in rendered
    assert "ValueError: b" in rendered


# pretty


def test_renders_a_fail_cause_as_a_string() -> None:
    """renders a Fail cause as a string"""
    assert "something went wrong" in cause.fail("something went wrong").pretty()


def test_renders_a_die_cause_as_a_string() -> None:
    """renders a Die cause as a string"""
    assert "unexpected" in cause.die(RuntimeError("unexpected")).pretty()


def test_returns_a_string_for_empty_cause() -> None:
    """returns a string for empty cause"""
    assert cause.empty.pretty() == ""


# NoSuchElementError (pyfect: NoSuchElementException)


def test_creates_an_error_with_tag_and_message() -> None:
    """creates an error with _tag and message"""
    assert str(fx.NoSuchElementException("not found")) == "not found"


def test_creates_an_error_without_message() -> None:
    """creates an error without message"""
    assert str(fx.NoSuchElementException()) == ""


def test_is_an_instance_of_error() -> None:
    """is an instance of Error"""
    assert isinstance(fx.NoSuchElementException(), Exception)


# UnknownError


def test_creates_an_error_with_cause_and_message() -> None:
    """creates an error with cause and message"""
    original = ValueError("original")
    error = fx.UnknownError(original, "wrapper message")
    assert error.message == "wrapper message"
    assert str(error) == "wrapper message"


def test_stores_the_original_cause() -> None:
    """stores the original cause"""
    original = ValueError("raw")
    error = fx.UnknownError(original)
    assert error.cause is original
    assert error.__cause__ is original


def test_unknown_error_is_an_instance_of_error() -> None:
    """is an instance of Error"""
    assert isinstance(fx.UnknownError(ValueError("x")), Exception)


# Done


def test_creates_a_done_signal_without_value() -> None:
    """creates a Done signal without value"""
    done = fx.Done()
    assert isinstance(done, fx.Done)
    assert done.value is None


def test_creates_a_done_signal_with_a_value() -> None:
    """creates a Done signal with a value"""
    done = fx.Done(42)
    assert isinstance(done, fx.Done)
    assert done.value == 42


def test_annotate_attaches_annotations_to_a_cause_data_first():
    """attaches annotations to a cause (data-first)"""
    annotated = cause.fail("error").annotate(fx.Context.empty())
    assert isinstance(annotated, Cause)
    assert len(annotated.reasons) == 1


def test_annotate_does_not_mutate_the_original_cause():
    """does not mutate the original cause"""

    class RequestId(fx.Tag[str]): ...

    original = cause.fail("error")
    original.annotate(fx.Context.make(RequestId, "req-1"))
    assert len(original.reasons) == 1
    assert original.annotations.get_option(RequestId) is None


def test_reason_annotations_returns_annotations_from_a_reason():
    """returns annotations from a reason"""

    class RequestId(fx.Tag[str]): ...

    reason = Fail("error").annotate(fx.Context.make(RequestId, "req-1"))
    assert cause.reason_annotations(reason).get_unsafe(RequestId) == "req-1"
    assert cause.reason_annotations(Fail("error")) == fx.Context.empty()


def test_annotations_returns_merged_annotations_from_a_cause():
    """returns merged annotations from a cause"""

    class RequestId(fx.Tag[str]): ...

    class UserId(fx.Tag[str]): ...

    annotated = (cause.fail("a") + cause.die(ValueError("b"))).annotate(
        fx.Context.make(RequestId, "req-1")
    ) + cause.fail("c").annotate(fx.Context.make(UserId, "user-1"))
    anns = annotated.annotations
    assert anns.get_unsafe(RequestId) == "req-1"
    assert anns.get_unsafe(UserId) == "user-1"
    assert cause.fail("error").annotations == fx.Context.empty()


def test_stack_trace_is_a_context_service():
    """is a Context.Service"""
    assert issubclass(StackTrace, fx.Tag)


def test_interruptor_stack_trace_is_a_context_service():
    """is a Context.Service"""
    assert issubclass(InterruptorStackTrace, fx.Tag)
