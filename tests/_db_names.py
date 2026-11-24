"""Names for the tables a test makes in a database other tests of its process share.

``fresh_name(kind)`` is ``kind_<pid>_<n>``, with one counter for the whole process, so no two
calls return the same name whichever module makes them. Each module counting on its own made
``legacy_<pid>_0`` twice, once for event log tables and once for runner tables, and a test
listing its tables found the other's (flake hunt run 45306276279).
``tests/test_db_names.py`` bans building such a name anywhere else.

Tables are named ``<name>_<suffix>``; to find a name's tables, match ``<name>_``, never the
bare name, which is a prefix of later names (``x_1`` of ``x_16``): ``owns_table``.
"""

import itertools
import os

_counter = itertools.count()


def fresh_name(kind: str) -> str:
    return f"{kind}_{os.getpid()}_{next(_counter)}"


def owns_table(name: str, table: str) -> bool:
    """Whether ``table`` is one of the tables named under ``name``."""
    return table.lower().startswith(f"{name.lower()}_")
