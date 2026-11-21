from decimal import Decimal

import pyfect as fx
from pyfect import stream
from pyfect.ai import budget, language_model
from pyfect.ai.language_model import LanguageModel, ProviderOptions


def price(tokens: budget.Tokens) -> Decimal:
    return tokens.input * Decimal("0.000003") + tokens.output * Decimal("0.000015")


limits = budget.Limits(
    total_tokens=5_000,
    cost=budget.Cost(Decimal("0.05"), price),
    max_output_tokens=1_000,  # the provider's max_tokens: each request reserves it
)
shared = budget.Budget(limits)


def answer(options: ProviderOptions):
    # While the request runs, the budget holds its worst case.
    held = shared.held().map(lambda held: print("held during the call:", held.total_tokens))
    usage = {"inputTokens": {"total": 40}, "outputTokens": {"total": 120}}
    reply = [{"type": "text", "text": "Hi!"}, {"type": "finish", "reason": "stop", "usage": usage}]
    return held.as_(reply)


Scripted = fx.layer.effect(
    LanguageModel, language_model.make(generate_text=answer, stream_text=lambda _: stream.empty)
)


@fx.gen
def main():
    yield from language_model.generate_text("Say hi").pipe(budget.provide(shared))
    spent = yield from shared.spent()
    print("spent:", spent.total_tokens, "tokens,", spent.cost)
    print("still held:", (yield from shared.held()).total_tokens)
    # A long prompt's worst case (5,000 estimated input tokens plus 1,000 output) does
    # not fit what is left, so it fails before the provider is called.
    error = yield from (
        language_model.generate_text("x" * 20_000).pipe(budget.provide(shared)).flip()
    )
    print(error)
    assert (yield from shared.spent()).requests == 1


fx.run_main(main.pipe(fx.provide(Scripted)))
