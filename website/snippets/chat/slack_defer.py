import pyfect as fx
from pyfect import layer, testing
from pyfect.chat import chat_interaction as ci
from pyfect.chat import chat_test
from pyfect.chat.chat import Chat
from pyfect.chat.chat_test import ChatTest

report = ci.command("report", description="Builds the weekly report")


# Stands in for slow work: a summary is quick, the full report takes 5 seconds.
def build_report(text: str) -> fx.Effect[str]:
    took = "5 seconds" if text == "full" else "100 millis"
    return fx.sleep(took).as_(f"Weekly report ({text}): 42 deploys, 0 rollbacks")


@fx.gen
def handlers():
    # The layer's scope. Work forked into it outlives the handler, which is
    # interrupted at Slack's deadline, and stops when the app shuts down.
    scope = yield from fx.Scope()
    chat = yield from Chat()

    def on_report(command: ci.CommandInvoked) -> fx.Effect[ci.Respond | ci.Defer]:
        @fx.gen
        def answer():
            # start_immediately runs the work up to its first wait before going on.
            work = yield from build_report(command.text).fork_in(scope, start_immediately=True)
            # Two of Slack's three seconds go to the work; the rest is the reply's.
            done = yield from work.join().timeout_option("2 seconds")
            if isinstance(done, fx.Some):
                return ci.respond(markdown=done.value)
            # Too slow: answer now, and send the report through the command's
            # response_url once the work is done.
            deferred = ci.defer(command)
            yield from (
                work.join()
                .flat_map(lambda text: chat.follow_up(deferred, markdown=text))
                .ignore(log=True, message="the report's follow-up failed")
                .fork_in(scope)
            )
            return deferred

        return answer

    return [report.handler(on_report)]


interactions = ci.group(report).to_layer(handlers)


# The test platform answers commands as Slack would, with a 3 second deadline
# on the test clock, so the 5 second report takes no real time.
@fx.gen
def program():
    test = yield from ChatTest()
    thread = yield from test.make_thread()
    for text, wait in [("summary", "100 millis"), ("full", "2 seconds")]:
        command = yield from test.command(thread, "report", text=text)
        asked = yield from test.interact(command).fork()
        yield from testing.adjust(wait)
        print(f"/report {text}:", type((yield from asked.join())).__name__)
    yield from testing.adjust("3 seconds")
    for call in (yield from test.calls):
        print(call.op, call.outcome, repr(call.markdown))


layers = interactions.pipe(layer.provide_merge(ci.layer())).pipe(
    layer.provide_merge(chat_test.layer())
)
testing.run_test(program.pipe(fx.provide(layers)).or_die())
