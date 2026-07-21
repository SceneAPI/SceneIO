"""Asserts the public contract surface of ``sceneio``.

Every name in ``sceneio.__all__`` must be importable off the package,
and the shared error base must be a plain ``Exception`` subclass.
"""

from __future__ import annotations

import importlib

import sceneio
from sceneio import SceneIoError


def test_all_names_are_importable() -> None:
    for name in sceneio.__all__:
        assert hasattr(sceneio, name), f"{name} listed in __all__ but not present"


def test_star_import_exposes_all() -> None:
    ns: dict[str, object] = {}
    exec("from sceneio import *", ns)
    for name in sceneio.__all__:
        if name == "__version__":
            continue
        assert name in ns, f"{name} not exported by `from sceneio import *`"


def test_version_is_020() -> None:
    assert sceneio.__version__ == "0.2.0"


def test_sceneio_error_is_an_exception() -> None:
    assert issubclass(SceneIoError, Exception)
    assert isinstance(SceneIoError("boom"), Exception)


def test_key_contract_modules_import_clean() -> None:
    for mod in (
        "sceneio.errors",
        "sceneio.points_binary",
        "sceneio.mapping_input",
        "sceneio.blobstore",
        "sceneio.imagesource",
        "sceneio.colmap_db",
    ):
        assert importlib.import_module(mod) is not None
