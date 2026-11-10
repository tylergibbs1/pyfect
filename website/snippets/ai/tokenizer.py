import pyfect as fx
from pyfect.ai import prompt as P
from pyfect.ai import tokenizer
from pyfect.ai.tokenizer import Tokenizer


# A stand-in tokenizer: one token per word of every text part.
def count_words(prompt: P.Prompt):
    words = [
        word
        for message in prompt.content
        for part in (message.content if isinstance(message.content, tuple) else ())
        if isinstance(part, P.TextPart)
        for word in part.text.split()
    ]
    return fx.succeed(list(range(len(words))))


Words = fx.layer.succeed(Tokenizer, tokenizer.make(tokenize=count_words))

history = [
    {"role": "user", "content": "Plan a three day trip to Lisbon in spring"},
    {"role": "assistant", "content": "Day one: Alfama and the castle"},
    {"role": "user", "content": "Add a day trip"},
]


@fx.fn
def program():
    tokens = yield from Tokenizer()
    total = yield from tokens.tokenize(history)
    print("tokens:", len(total))
    # Keep the latest messages that fit in a budget of 12 tokens.
    kept = yield from tokens.truncate(history, 12)
    print("kept:", [message.role for message in kept.content])
    assert len(total) == 19
    assert [message.role for message in kept.content] == ["assistant", "user"]


fx.run_main(program().pipe(fx.provide(Words)))
