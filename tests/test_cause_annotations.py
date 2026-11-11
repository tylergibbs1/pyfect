"""Annotations on a cause's reasons: what ``annotate`` keeps or replaces,
that electing defects keeps them, and that a change adding nothing gives
the same cause back."""

import pyfect as fx
from pyfect import cause
from pyfect.cause import Die, Fail, reason_annotations
from pyfect.context import Context, Tag
from pyfect.errors import Done


class Label(Tag[str]):
    pass


def _label(c: cause.Cause[object]) -> list[str]:
    return [reason_annotations(r).get(Label) for r in c.reasons]


def test_annotate_keeps_a_key_a_reason_already_has_unless_told_to_overwrite():
    labelled = cause.fail("e").annotate(Context.make(Label, "first"))
    relabel = Context.make(Label, "second")
    assert _label(labelled.annotate(relabel)) == ["first"]
    assert _label(labelled.annotate(relabel, overwrite=True)) == ["second"]
    (reason,) = labelled.reasons
    assert reason_annotations(reason.annotate(relabel)).get(Label) == "first"
    assert reason_annotations(reason.annotate(relabel, overwrite=True)).get(Label) == "second"


def test_annotating_with_nothing_new_gives_the_same_cause_and_reason():
    ctx = Context.make(Label, "same")
    labelled = cause.fail("e").annotate(ctx)
    (reason,) = labelled.reasons
    assert labelled.annotate(ctx) is labelled
    assert labelled.annotate(ctx, overwrite=True) is labelled
    assert reason.annotate(ctx) is reason


def test_adding_interrupts_already_recorded_gives_the_same_cause():
    interrupted = cause.fail("e") + cause.interrupt(1)
    assert interrupted.add_interrupts(cause.interrupt(1)) is interrupted
    assert interrupted.add_interrupts(cause.interrupt(2)).interruptors == {1, 2}


def test_electing_defects_keeps_each_failures_annotations():
    ctx = Context.make(Label, "kept")
    elected = (cause.fail("e").annotate(ctx) + cause.die("d")).elect_defects()
    assert elected.reasons == (Die("e", annotations=ctx.map_unsafe), Die("d"))
    assert reason_annotations(elected.reasons[0]).get(Label) == "kept"


def test_done_fails_with_done_holding_the_value():
    assert fx.run_sync_exit(cause.done(5)) == fx.Failure(cause.Cause((Fail(Done(5)),)))
