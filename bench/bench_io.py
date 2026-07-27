"""Compatible command-line and helper facade for the SceneIO I/O benchmark."""

from __future__ import annotations

import importlib as _importlib
import sys
import types as _types
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.io_bench import runner as _runner

if globals().get("_FACADE_INITIALIZED", False):
    _runner = _importlib.reload(_runner)

_COMPAT_EXPORTS = tuple(
    name for name in vars(_runner) if not name.startswith("__")
)

for _name in _COMPAT_EXPORTS:
    globals()[_name] = getattr(_runner, _name)
del _name


class _FacadeModule(_types.ModuleType):
    """Keep historical facade rebinding visible to runner functions."""

    def __setattr__(self, name, value):
        if name in self._COMPAT_EXPORTS:
            setattr(self._runner, name, value)
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if name in self._COMPAT_EXPORTS:
            delattr(self._runner, name)
        super().__delattr__(name)


_facade_module = sys.modules.get(__name__)
if _facade_module is not None:
    _facade_module.__class__ = _FacadeModule

_FACADE_INITIALIZED = True


if __name__ == "__main__":
    _runner.main()
