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
    w: Callable | None
    r: Callable
    nbytes: Callable
    path_read: Callable | None = None
    partial: Callable | None = None
    assert_read: Callable | None = None
    assert_partial: Callable | None = None


@dataclass
class PathSpec:
    """One path-native codec benchmark with an independent path provider."""

    id: str
    extension: str
    make: Callable
    w: Callable
    r: Callable
    ow: Callable | None
    orr: Callable | None
    nbytes: Callable
    assert_native: Callable
    assert_oracle: Callable
    partial: Callable | None = None
    assert_partial: Callable | None = None
    oracle_inspect: Callable | None = None
    assert_oracle_inspect: Callable | None = None
    oracle_partial: Callable | None = None
    assert_oracle_partial: Callable | None = None
