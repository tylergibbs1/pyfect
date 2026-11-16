"""A bare number given as a duration is milliseconds, as in Effect, so ``fx.sleep(2)`` sleeps
2 ms. That stays (a stricter type is 0.7.0 material), but ``PYFECT_WARN_BARE_DURATIONS=1``
makes every bare number warn with ``BareNumberDurationWarning``, pointing at the caller's
line and suggesting the unit, so a project can find them, or fail on them with
``PYFECT_WARN_BARE_DURATIONS=error``. Off by default: a default-ignored
category would still raise for every project running with ``filterwarnings = error``."""

import warnings

import pytest

import pyfect as fx
from pyfect import duration
from pyfect.duration import BareNumberDurationWarning


@pytest.fixture
def opted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYFECT_WARN_BARE_DURATIONS", "1")


@pytest.mark.usefixtures("opted_in")
def test_a_bare_number_warns_at_the_caller_s_line_and_suggests_seconds():
    with pytest.warns(BareNumberDurationWarning) as caught:
        fx.sleep(2)
    [warning] = caught.list
    message = str(warning.message)
    assert "2 milliseconds" in message
    assert '"2 seconds"' in message
    assert '"2 millis"' in message
    assert warning.filename == __file__


@pytest.mark.usefixtures("opted_in")
def test_one_is_one_millisecond_and_suggests_one_second():
    with pytest.warns(BareNumberDurationWarning) as caught:
        fx.sleep(1)
    message = str(caught.list[0].message)
    assert "read as 1 millisecond;" in message
    assert '"1 second"' in message
    assert "1 milliseconds" not in message
    assert '"1 seconds"' not in message


@pytest.mark.usefixtures("opted_in")
def test_a_float_suggests_its_own_text():
    with pytest.warns(BareNumberDurationWarning, match=r'"1\.5 seconds"'):
        fx.succeed(1).timeout(1.5)


@pytest.mark.usefixtures("opted_in")
def test_it_can_be_made_an_error():
    with warnings.catch_warnings():
        warnings.simplefilter("error", BareNumberDurationWarning)
        with pytest.raises(BareNumberDurationWarning):
            fx.sleep(2)


@pytest.mark.usefixtures("opted_in")
@pytest.mark.parametrize("value", [0, 0.0, float("inf"), "2 seconds", duration.seconds(2)])
def test_unambiguous_inputs_do_not_warn(value: duration.Input):
    with warnings.catch_warnings():
        warnings.simplefilter("error", BareNumberDurationWarning)
        fx.sleep(value)


def test_off_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PYFECT_WARN_BARE_DURATIONS", raising=False)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert fx.run_blocking(fx.sleep(1).as_("done")) == "done"


def test_zero_in_the_variable_turns_it_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PYFECT_WARN_BARE_DURATIONS", "0")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        fx.sleep(2)


def test_an_empty_variable_is_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PYFECT_WARN_BARE_DURATIONS", "")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        fx.sleep(2)


def test_error_in_the_variable_raises_it_as_an_error(monkeypatch: pytest.MonkeyPatch):
    # Python resolves `-W` / PYTHONWARNINGS categories before pyfect is imported, so they
    # cannot name BareNumberDurationWarning; the variable can.
    monkeypatch.setenv("PYFECT_WARN_BARE_DURATIONS", "error")
    with pytest.raises(BareNumberDurationWarning, match=r'"2 seconds"'):
        fx.sleep(2)


def test_error_in_the_variable_leaves_unambiguous_inputs_alone(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PYFECT_WARN_BARE_DURATIONS", "error")
    fx.sleep(0)
    fx.sleep("2 seconds")
