"""``RunnerAddress``: where a runner listens (Effect's ``RunnerAddress``)."""

from __future__ import annotations

from pyfect import schema as S


class RunnerAddress(S.Class, identifier="~effect/cluster/RunnerAddress"):
    host: str
    port: int

    def primary_key(self) -> str:
        return f"{self.host}:{self.port}"

    def __str__(self) -> str:
        return f"RunnerAddress({self.host}:{self.port})"


def make(host: str, port: int) -> RunnerAddress:
    return S.new(RunnerAddress, disable_checks=True)(host=host, port=port)


__all__ = ["RunnerAddress", "make"]
