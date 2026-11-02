"""A ``Config`` is an ``Effect`` (as in Effect v4), so it inherits every
``Effect`` method. Where Effect's ``Config`` module has a combinator of the
same name, the two mean different things (``Config.option`` keeps invalid
data failing, ``Effect.option`` turns it into ``None``: DOGFOOD B3). Effect
tells them apart by module (``config.pipe(Config.option)``); pyfect's methods
cannot, so ``Config`` must define each such method itself with the
``Config`` meaning.
"""

from pyfect import config
from pyfect._core import Effect
from pyfect.config import Config

# The combinators of Effect v4's ``Config.ts`` (``packages/effect/src/Config.ts``),
# snake_cased; ``pyfect.config``'s own functions are added below.
_EFFECT_CONFIG_COMBINATORS = frozenset(
    {
        "all",
        "fail",
        "flat_map",
        "map",
        "map_effect",
        "nested",
        "option",
        "or_else",
        "parse",
        "schema",
        "succeed",
        "unwrap",
        "with_default",
    }
)


def _inherited_effect_methods() -> set[str]:
    return {name for name in dir(Effect) if not name.startswith("_")}


def test_every_effect_method_named_like_a_config_combinator_has_the_config_meaning():
    config_names = _EFFECT_CONFIG_COMBINATORS | set(config.__all__)
    colliding = _inherited_effect_methods() & config_names
    assert colliding, "the walk found no Effect method at all"
    missing = sorted(name for name in colliding if name not in vars(Config))
    assert missing == [], (
        f"Config inherits Effect's {missing}, whose meaning differs from Effect's "
        "Config combinator of that name: override it on Config"
    )


def test_the_walk_sees_the_known_collisions():
    # Guard the guard: if these stop being Effect methods, the list above is stale.
    assert {"map", "flat_map", "option"} <= _inherited_effect_methods()
    assert {"map", "flat_map", "option"} <= set(vars(Config))
