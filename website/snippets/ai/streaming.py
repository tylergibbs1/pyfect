import pyfect as fx
from pyfect import stream
from pyfect.ai import language_model, response
from pyfect.ai.language_model import EncodedPart, LanguageModel, ProviderOptions


# Print the text as it arrives; the stream ends with a finish part.
def show(part: response.StreamPart[str, object]) -> fx.Effect[None]:
    if isinstance(part, response.TextDeltaPart):
        return fx.sync(lambda: print(part.delta, end="", flush=True))
    if isinstance(part, response.FinishPart):
        return fx.sync(lambda: print(f"\n[{part.reason}]"))
    return fx.void


program = language_model.stream_text("Count to three.").run_for_each(show)


# A scripted model that streams three deltas.
def deltas(_options: ProviderOptions):
    words = ["one, ", "two, ", "three"]
    usage = {"inputTokens": {"total": 5}, "outputTokens": {"total": 3}}
    parts: list[EncodedPart] = [
        {"type": "text-start", "id": "t"},
        *({"type": "text-delta", "id": "t", "delta": word} for word in words),
        {"type": "text-end", "id": "t"},
        {"type": "finish", "reason": "stop", "usage": usage},
    ]
    return stream.from_iterable(parts)


Scripted = fx.layer.effect(
    LanguageModel,
    language_model.make(generate_text=lambda _: fx.succeed([]), stream_text=deltas),
)

fx.run_main(program.pipe(fx.provide(Scripted)))
