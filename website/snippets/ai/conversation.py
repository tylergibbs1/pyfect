import pyfect as fx
from pyfect import stream
from pyfect.ai import language_model, prompt
from pyfect.ai.language_model import LanguageModel, ProviderOptions


# A conversation is a Prompt that grows: each reply is added back to it.
@fx.fn
def program():
    history = prompt.make("My name is Ada.").set_system("Answer in one line.")
    for question in ["Hello!", "What is my name?"]:
        history = history.concat(question)
        reply = yield from language_model.generate_text(history)
        history = history.concat(prompt.from_response_parts(reply.content))
        print(f"> {question}\n< {reply.text}")
    print([message.role for message in history.content])


# A scripted model that says how much of the conversation it was sent.
def answer(options: ProviderOptions):
    text = f"I was sent {len(options.prompt.content)} messages"
    return fx.succeed([{"type": "text", "text": text}])


Scripted = fx.layer.effect(
    LanguageModel, language_model.make(generate_text=answer, stream_text=lambda _: stream.empty)
)

fx.run_main(program().pipe(fx.provide(Scripted)))
