"""Data models shared by the SceneIO I/O benchmark facade."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class Spec:
    """One buffer-backed codec benchmark definition."""

    id: str
    make: Callable
    w: Callable  # record -> bytes
    r: Callable  # bytes -> record
    ow: Callable | None  # oracle: payload -> bytes
    orr: Callable | None  # oracle: bytes -> object
    nbytes: Callable  # (record, payload) -> logical payload bytes


@dataclass
class DirectorySpec:
    """One directory-backed codec benchmark definition."""

    id: str
    make: Callable
    w: Callable
    r: Callable
    nbytes: Callable
