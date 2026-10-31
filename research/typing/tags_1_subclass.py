"""Question: a tag class subclassing another (``class ReplicaDb(Db)``): does
providing ``Db`` remove ``ReplicaDb`` from ``R``?

Run: ``uv run pyright -p research/typing research/typing/tags_1_subclass.py``.

Answer: yes. ``R`` holds tag classes and ``provide`` removes by union
matching, which counts a subclass as its parent; the runtime looks a service
up by its own class, so the program would die with ``MissingServiceError``.
No signature can stop the match, so ``Tag`` rejects the subclass when the
class is made (``TypeError``) unless the parent is declared a base
(``class Family(Tag[A], base=True)``, read or provided only through its
subclasses).
"""

from typing import Never, assert_type

import pyfect as fx


class Db(fx.Tag[str]): ...


class ReplicaDb(Db): ...  # a TypeError at run time


def program() -> fx.Effect[str, Never, ReplicaDb]:
    return ReplicaDb()


assert_type(program().pipe(fx.provide_service(Db, "db")), fx.Effect[str, Never, Never])
