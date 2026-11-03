"""Reuse cases for the layer combinators and the core services: each run
must see a resource its own build opened (and nothing a previous run
recorded)."""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from datetime import UTC
from typing import Any

import pyfect as fx
from layer_cases._case import AnyEffect, AnyLayer, Case
from pyfect import (
    config,
    config_provider,
    crypto,
    date_time,
    error_reporter,
    file_system,
    logger,
    metric,
    path,
    platform,
    process,
    stdio,
    terminal,
    testing,
)
from pyfect import layer as L
from pyfect.cli import cli_config, cli_output, terminal_capabilities
from pyfect.context import Context, Tag
from pyfect.layer_map import LayerMapService
from pyfect.layer_ref import LayerRefService


class _Resource:
    def __init__(self) -> None:
        self.open = True

    def close(self) -> None:
        self.open = False


class Res(Tag[_Resource], key="layer_cases/core/Res"):
    pass


class Other(Tag[int], key="layer_cases/core/Other"):
    pass


def _expect(found: object, wanted: object) -> AnyEffect:
    if found == wanted:
        return fx.void
    return fx.die(AssertionError(f"expected {wanted!r}, got {found!r}"))


def _acquire() -> fx.Effect[_Resource, Any, Any]:
    return fx.acquire_release(fx.sync(_Resource), lambda r, _exit: fx.sync(r.close))


def _resource() -> AnyLayer:
    return L.effect(Res, _acquire())


def _open() -> AnyEffect:
    return Res().flat_map(lambda r: _expect(r.open, True))


def _get(tag: Any) -> AnyEffect:
    return tag().map(lambda _: None)


def _fails() -> AnyLayer:
    return L.effect(Res, fx.fail("no"))


class _ResMap(LayerMapService[str, Res]): ...


class _ResRef(LayerRefService[Res]): ...


def _from_map() -> AnyEffect:
    return fx.scoped(
        _ResMap.context_effect("a").flat_map(lambda ctx: _expect(ctx.get(Res).open, True))
    )


def _from_ref() -> AnyEffect:
    return fx.scoped(
        _ResRef.context_effect().flat_map(lambda ctx: _expect(ctx.get(Res).open, True))
    )


def _echo_through_spawner() -> AnyEffect:
    @fx.fn
    def run():
        handle = yield from process.make("echo", ["hi"])
        output = yield from handle.stdout.run_bytes().map(bytes.decode)
        return (yield from _expect(output, "hi\n"))

    return run()


def _with_file_system(f: Any) -> AnyEffect:
    return file_system.FileSystem().flat_map(f)


def _write_then_read(fs: Any) -> AnyEffect:
    @fx.fn
    def run():
        directory = yield from fs.make_temp_directory_scoped()
        target = f"{directory}/x.txt"
        yield from fs.write_file_string(target, "hi")
        return (yield from fs.read_file_string(target).flat_map(lambda t: _expect(t, "hi")))

    return run()


def _join(service: Any) -> AnyEffect:
    return _expect(service.join("a", "b").replace("\\", "/"), "a/b")


def _sleep_on_test_clock() -> AnyEffect:
    @fx.fn
    def run():
        fiber = yield from fx.sleep(10).fork()
        yield from testing.adjust(10)
        return (yield from fiber.join())

    return run()


def _console_log_once() -> AnyEffect:
    @fx.fn
    def run():
        yield from fx.console.log("hi")
        return (yield from testing.log_lines.flat_map(lambda lines: _expect(lines, ["hi"])))

    return run()


def _seeded_draw() -> AnyEffect:
    return crypto.Crypto().flat_map(lambda c: c.random_bytes(4)).map(lambda _: None)


@fx.fn
def _read_config():
    value = yield from config.string("A")
    return (yield from _expect(value, "1"))


def _now_in_zone() -> AnyEffect:
    return date_time.now_in_current_zone().map(lambda _: None)


_reports: list[object] = []


def _logged() -> AnyEffect:
    return fx.log_info("hi")


def _stdout_written() -> AnyEffect:
    return stdio.Stdio().flat_map(lambda s: s.args).map(lambda _: None)


CASES: dict[str, Case] = {
    # --- combinators over a scoped resource
    "pyfect.layer.effect": Case(layer=_resource, use=_open),
    "pyfect.layer.effect_context": Case(
        layer=lambda: L.effect_context(_acquire().map(lambda r: Context({Res: r}))), use=_open
    ),
    "pyfect.layer.effect_discard": Case(
        layer=lambda: L.effect_discard(_acquire()).pipe(L.provide_merge(_resource())), use=_open
    ),
    "pyfect.layer.fresh": Case(layer=lambda: L.fresh(_resource()), use=_open),
    "pyfect.layer.merge": Case(
        layer=lambda: L.merge(_resource(), L.succeed(Other, 1)),
        use=lambda: _open().flat_map(lambda _: _get(Other)),
    ),
    "pyfect.layer.suspend": Case(layer=lambda: L.suspend(_resource), use=_open),
    "pyfect.layer.unwrap": Case(layer=lambda: L.unwrap(fx.sync(_resource)), use=_open),
    "pyfect.layer.succeed": Case(layer=lambda: L.succeed(Other, 1), use=lambda: _get(Other)),
    "pyfect.layer.succeed_context": Case(
        layer=lambda: L.succeed_context(Context({Other: 1})), use=lambda: _get(Other)
    ),
    "pyfect.layer.sync": Case(layer=lambda: L.sync(Res, _Resource), use=_open),
    "pyfect.layer.sync_context": Case(
        layer=lambda: L.sync_context(lambda: Context({Res: _Resource()})), use=_open
    ),
    "pyfect.layer.mock": Case(layer=lambda: L.mock(Res, open=True), use=_open),
    "pyfect.layer.empty": Case(layer=lambda: L.empty),
    "pyfect.layer.span": Case(layer=lambda: L.span("reuse"), use=lambda: fx.log_info("in span")),
    "pyfect.layer.parent_span": Case(
        layer=lambda: L.unwrap(fx.make_span("parent").map(L.parent_span)),
        use=lambda: fx.log_info("under parent"),
    ),
    "pyfect.Layer.catch_all": Case(
        layer=lambda: _fails().catch_all(lambda _: _resource()), use=_open
    ),
    "pyfect.Layer.catch_cause": Case(
        layer=lambda: _fails().catch_cause(lambda _: _resource()), use=_open
    ),
    "pyfect.Layer.flat_map": Case(
        layer=lambda: L.succeed(Other, 1).flat_map(lambda _: _resource()), use=_open
    ),
    "pyfect.Layer.or_die": Case(layer=lambda: _resource().or_die(), use=_open),
    "pyfect.Layer.tap": Case(layer=lambda: _resource().tap(lambda _: fx.void), use=_open),
    "pyfect.Layer.tap_cause": Case(
        layer=lambda: _resource().tap_cause(lambda _: fx.void), use=_open
    ),
    "pyfect.Layer.tap_error": Case(
        layer=lambda: _resource().tap_error(lambda _: fx.void), use=_open
    ),
    "pyfect.Layer.update_service": Case(
        layer=lambda: L.succeed(Other, 1).update_service(Res, lambda r: r),
        needs=_resource,
        use=lambda: _open().flat_map(lambda _: _get(Other)),
    ),
    "pyfect.Layer.with_span": Case(layer=lambda: _resource().with_span("reuse"), use=_open),
    "pyfect.Layer.with_parent_span": Case(
        layer=lambda: L.unwrap(fx.make_span("parent").map(_resource().with_parent_span)),
        use=_open,
    ),
    "pyfect.LayerMapService.layer": Case(
        layer=lambda: _ResMap.layer(lambda _key: _resource()), use=_from_map
    ),
    "pyfect.LayerMapService.layer_from_record": Case(
        layer=lambda: _ResMap.layer_from_record({"a": _resource()}), use=_from_map
    ),
    "pyfect.LayerMapService.get": Case(
        layer=lambda: _ResMap.get("a"),
        needs=lambda: _ResMap.layer(lambda _key: _resource()),
        use=_open,
    ),
    "pyfect.LayerMap.get": Case(
        layer=lambda: L.unwrap(
            fx.LayerMap.make(lambda _key: _resource()).map(lambda m: m.get("a"))
        ),
        use=_open,
    ),
    "pyfect.LayerRefService.layer": Case(layer=lambda: _ResRef.layer(_resource()), use=_from_ref),
    "pyfect.LayerRefService.get": Case(
        layer=_ResRef.get, needs=lambda: _ResRef.layer(_resource()), use=_open
    ),
    "pyfect.LayerRef.get": Case(
        layer=lambda: L.unwrap(fx.LayerRef.make(_resource()).map(lambda r: r.get())),
        use=_open,
    ),
    # --- platform services
    "pyfect.file_system.layer": Case(
        layer=lambda: file_system.layer, use=lambda: _with_file_system(_write_then_read)
    ),
    "pyfect.file_system.layer_noop": Case(
        layer=file_system.layer_noop,
        use=lambda: _with_file_system(lambda fs: fs.exists("/nowhere").map(lambda _: None)),
    ),
    "pyfect.path.layer": Case(layer=lambda: path.layer, use=lambda: path.Path().flat_map(_join)),
    "pyfect.path.layer_win32": Case(
        layer=lambda: path.layer_win32, use=lambda: path.Path().flat_map(_join)
    ),
    "pyfect.platform.layer": Case(layer=lambda: platform.layer, use=_echo_through_spawner),
    "pyfect.process.layer": Case(
        layer=lambda: process.layer,
        needs=lambda: L.merge(file_system.layer, path.layer),
        use=_echo_through_spawner,
    ),
    "pyfect.terminal.layer": Case(
        layer=lambda: terminal.layer,
        use=lambda: terminal.Terminal().flat_map(lambda t: t.columns).map(lambda _: None),
    ),
    "pyfect.stdio.layer": Case(layer=lambda: stdio.layer, use=_stdout_written),
    "pyfect.stdio.layer_test": Case(layer=stdio.layer_test, use=_stdout_written),
    "pyfect.crypto.layer": Case(layer=lambda: crypto.layer, use=_seeded_draw),
    "pyfect.testing.TestCrypto.layer": Case(
        layer=lambda: testing.TestCrypto.layer("seed"), needs=lambda: crypto.layer, use=_seeded_draw
    ),
    "pyfect.testing.TestClock.layer": Case(layer=testing.TestClock.layer, use=_sleep_on_test_clock),
    "pyfect.testing.TestConsole.layer": Case(
        layer=testing.TestConsole.layer, use=_console_log_once
    ),
    "pyfect.config_provider.layer": Case(
        layer=lambda: config_provider.layer(config_provider.from_env_record({"A": "1"})),
        use=_read_config,
    ),
    "pyfect.config_provider.layer_add": Case(
        layer=lambda: config_provider.layer_add(
            config_provider.from_env_record({"A": "1"}), as_primary=True
        ),
        use=_read_config,
    ),
    "pyfect.date_time.layer_current_zone": Case(
        layer=lambda: date_time.layer_current_zone(UTC), use=_now_in_zone
    ),
    "pyfect.date_time.layer_current_zone_local": Case(
        layer=date_time.layer_current_zone_local, use=_now_in_zone
    ),
    "pyfect.date_time.layer_current_zone_named": Case(
        layer=lambda: date_time.layer_current_zone_named("Europe/London"), use=_now_in_zone
    ),
    "pyfect.date_time.layer_current_zone_offset": Case(
        layer=lambda: date_time.layer_current_zone_offset(3600), use=_now_in_zone
    ),
    "pyfect.error_reporter.layer": Case(
        layer=lambda: error_reporter.layer([error_reporter.make(_reports.append)]),
        use=lambda: fx.fail("reported").ignore(),
    ),
    "pyfect.logger.layer": Case(
        layer=lambda: logger.layer([logger.Logger.make(lambda _options: None)]), use=_logged
    ),
    "pyfect.metric.enable_runtime_metrics_layer": Case(
        layer=lambda: metric.enable_runtime_metrics_layer, use=_logged
    ),
    "pyfect.metric.disable_runtime_metrics_layer": Case(
        layer=lambda: metric.disable_runtime_metrics_layer, use=_logged
    ),
    "pyfect.cli.cli_config.layer": Case(
        layer=cli_config.layer, use=lambda: _get(cli_config.CliConfig)
    ),
    "pyfect.cli.cli_output.layer": Case(
        layer=lambda: cli_output.layer(cli_output.default_formatter()),
        use=lambda: _get(cli_output.CurrentFormatter),
    ),
    "pyfect.cli.cli_output.layer_presenter": Case(
        layer=lambda: cli_output.layer_presenter(cli_output.default_presenter),
        use=lambda: _get(cli_output.CurrentPresenter),
    ),
    "pyfect.cli.terminal_capabilities.layer": Case(
        layer=lambda: terminal_capabilities.layer,
        needs=stdio.layer_test,
        use=lambda: _get(terminal_capabilities.TerminalCapabilities),
    ),
}

SKIPPED: dict[str, str] = {
    "pyfect.layer.from_build": "the layer primitive: the build function given is the state",
    "pyfect.layer.from_build_memo": "the layer primitive: the build function given is the state",
}
