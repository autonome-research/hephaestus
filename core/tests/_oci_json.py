"""Narrow mutable, deliberately adversarial JSON fixtures without claiming admission."""

from typing import cast


def record(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in cast(dict[object, object], value))
    return cast(dict[str, object], value)


def array(value: object) -> list[object]:
    assert isinstance(value, list)
    return cast(list[object], value)


def text(value: object) -> str:
    assert isinstance(value, str)
    return value


def integer(value: object) -> int:
    assert type(value) is int
    return value
