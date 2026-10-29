import pyfect as fx
from pyfect import stream
from pyfect.ai import chat, language_model
from pyfect.ai.language_model import LanguageModel, ProviderOptions
from pyfect.persistence import persistence


# A chat keeps the history: each call sends it and adds the reply to it.
@fx.fn
def program():
    chats = yield from chat.Persistence()
    session = yield from chats.get_or_create("ada")
    for question in ["My name is Ada.", "What is my name?"]:
        reply = yield from session.generate_text(question)
        print(f"> {question}\n< {reply.text}")
    # The store has the chat, so it can be opened again later.
    reopened = yield from chats.get("ada")
    history = yield from reopened.history.get()
    print([message.role for message in history.content])


def answer(options: ProviderOptions):
    text = f"I was sent {len(options.prompt.content)} messages"
    return fx.succeed([{"type": "text", "text": text}])


Scripted = fx.layer.effect(
    LanguageModel, language_model.make(generate_text=answer, stream_text=lambda _: stream.empty)
)
Chats = chat.layer_persisted(store_id="chats").pipe(
    fx.layer.provide(persistence.layer_backing_memory)
)

fx.run_main(program().pipe(fx.provide(Scripted)).pipe(fx.provide(Chats)))
