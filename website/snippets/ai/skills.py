import tempfile
from pathlib import Path

import pyfect as fx
from pyfect import schema as S
from pyfect import stream
from pyfect.ai import language_model, prompt, skill
from pyfect.ai.language_model import LanguageModel, ProviderOptions
from pyfect.errors import IllegalArgumentError

# A skill is data: frontmatter, instructions and the files they refer to.
refunds = skill.make(
    frontmatter={"name": "refunds", "description": "Process customer refunds"},
    instructions="Read references/policy.md before issuing a refund.\n",
    files={
        "references/policy.md": "Refunds over $100 need approval.\n",
        "assets/logo.png": bytes([0x89, 0x50, 0x4E, 0x47]),
    },
)

# As files, it is a SKILL.md and its supporting files, ready to write to a directory.
files = skill.to_files(refunds)
print(files["SKILL.md"])

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory) / "refunds"
    for path, content in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            (root / path).write_text(content)
        else:
            (root / path).write_bytes(content)
    # Reading a directory back: every file as bytes, SKILL.md included.
    on_disk = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    loaded = fx.run_blocking(skill.from_files(on_disk).or_die())

print(loaded.frontmatter, sorted(loaded.files))

# A bad name fails with IllegalArgumentError, as untrusted input should.
bad = skill.from_files({"SKILL.md": "---\nname: Refunds!\ndescription: x\n---\n"})
rejected = bad.map(lambda _: "loaded").pipe(
    fx.catch_tag(IllegalArgumentError, lambda error: fx.succeed(type(error).__name__))
)
print(fx.run_blocking(rejected))

# Its JSON form keeps text and bytes apart.
encoded = S.encode_sync(S.to_codec_json(skill.Skill))(refunds)
assert isinstance(encoded, dict)
print(encoded["files"])


# A local agent: the skill's instructions go in the system prompt.
@fx.fn
def agent():
    conversation = prompt.make("Refund order 1042, $80.").set_system(refunds.instructions)
    reply = yield from language_model.generate_text(conversation)
    print(reply.text)


# A scripted model that answers with the system prompt it was given.
def answer(options: ProviderOptions):
    [system, *_] = options.prompt.content
    text = f"system prompt: {system.content!r}"
    usage = {"inputTokens": {"total": 9}, "outputTokens": {"total": 4}}
    return fx.succeed(
        [{"type": "text", "text": text}, {"type": "finish", "reason": "stop", "usage": usage}]
    )


Scripted = fx.layer.effect(
    LanguageModel, language_model.make(generate_text=answer, stream_text=lambda _: stream.empty)
)
fx.run_main(agent().pipe(fx.provide(Scripted)))
