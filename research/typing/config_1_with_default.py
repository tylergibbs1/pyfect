"""Can ``Config[A].with_default(x)`` keep ``A`` when ``x`` is an ``A`` (a literal config
keeps its literal), and still widen to ``A | B`` otherwise?

``Config`` is covariant, so ``default: A_co`` (Flag's fix: Flag is invariant) is not
allowed. A first overload with a self type, ``(self: Config[B], default: B) -> Config[B]``,
binds ``B`` from the receiver, so a literal default is checked against the literal; a
second overload ``(default: B) -> Config[A_co | B]`` widens otherwise. pyright calls the
second one unreachable (``reportOverlappingOverload``) but still picks it when the first
fails, as below.

The self type puts the receiver's type in ``default``'s parameter, so a receiver that is
partially ``Unknown`` makes the method partially unknown: ``config.all_dict({})`` and
``config.all(*iter(()))`` were ``Config[dict[Unknown, Unknown]]`` / ``Config[tuple[Unknown,
...]]`` (the two ported test_config.py lines). TypeVar defaults (``[K = Never]``) do not
apply to ``{}``; an overload taking ``Mapping[Never, Config[Never]]`` / ``*Config[Never]``
first gives ``Never`` instead.
"""

from typing import Literal, Never, assert_type

from pyfect import config

env: config.Config[Literal["dev", "prod"]] = config.literal("dev", "prod", name="ENV")
assert_type(env.with_default("dev"), config.Config[Literal["dev", "prod"]])
assert_type(env.with_default(None), config.Config[Literal["dev", "prod"] | None])
assert_type(env.with_default("staging"), config.Config[str])
assert_type(config.integer("n").with_default("auto"), config.Config[int | str])
assert_type(config.string("s").with_default("x"), config.Config[str])
assert_type(config.integer("n").with_default(3000), config.Config[int])

assert_type(config.all_dict({}), config.Config[dict[Never, Never]])
assert_type(config.all(*iter(())), config.Config[tuple[Never, ...]])
assert_type(config.all_dict({}).with_default("x"), config.Config[dict[Never, Never] | str])
assert_type(config.all_dict({"a": config.integer()}), config.Config[dict[str, int]])
