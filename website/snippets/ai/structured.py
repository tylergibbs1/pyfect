from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import stream
from pyfect.ai import language_model
from pyfect.ai.language_model import JsonFormat, LanguageModel, ProviderOptions


class Contact(TypedDict):
    name: str
    email: str


@fx.fn
def program():
    reply = yield from language_model.generate_object(
        "Ada Lovelace, ada@example.com", schema=S.Struct(Contact), object_name="contact"
    )
    contact = reply.value  # a Contact, decoded by the schema
    print(contact["name"], contact["email"])


# A scripted model: it is asked for JSON matching the schema, and answers with it.
def answer(options: ProviderOptions):
    if isinstance(options.response_format, JsonFormat):
        print("asked for", options.response_format.object_name)
    text = '{"name": "Ada Lovelace", "email": "ada@example.com"}'
    return fx.succeed([{"type": "text", "text": text}])


Scripted = fx.layer.effect(
    LanguageModel, language_model.make(generate_text=answer, stream_text=lambda _: stream.empty)
)

fx.run_main(program().pipe(fx.provide(Scripted)))
