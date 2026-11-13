from dataclasses import dataclass
from types import MappingProxyType

import pyfect as fx
from pyfect import error_reporter


@dataclass
class CardDeclined(fx.TaggedError):
    # An expected failure: reporters skip it.
    report_ignored = True


@dataclass
class LedgerOutOfSync(fx.TaggedError):
    report_severity = fx.LogLevel.ERROR
    report_attributes = MappingProxyType({"team": "payments"})


reports: list[str] = []


def send(report: error_reporter.Report) -> None:
    # Hand the report to Sentry, a log pipeline, ... Here: keep a line.
    reports.append(f"{report.severity}: {report.error!r} {dict(report.attributes)}")


reporting = error_reporter.layer([error_reporter.make(send)])


def charge(card: str) -> fx.Effect[None, CardDeclined | LedgerOutOfSync]:
    if card == "declined":
        return fx.fail(CardDeclined())
    if card == "ledger":
        return fx.fail(LedgerOutOfSync())
    return fx.die(ValueError(f"bad card {card!r}"))


@fx.fn
def program():
    for card in ["declined", "ledger", "garbage"]:
        # with_error_reporting reports the failure, then fails with it as before.
        yield from charge(card).with_error_reporting().ignore_cause()


fx.run_blocking(program().pipe(fx.provide(reporting)))
print("\n".join(reports))
