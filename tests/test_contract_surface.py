"""Asserts the public contract surface of ``sceneapi_io``.

Every name in ``sceneapi_io.__all__`` must be importable off the package,
and the shared error base must be a plain ``Exception`` subclass.
"""

from __future__ import annotations

import importlib

import sceneapi_io
from sceneapi_io import SceneIoError


def test_all_names_are_importable() -> None:
    for name in sceneapi_io.__all__:
        assert hasattr(sceneapi_io, name), f"{name} listed in __all__ but not present"


def test_star_import_exposes_all() -> None:
    ns: dict[str, object] = {}
    exec("from sceneapi_io import *", ns)
    for name in sceneapi_io.__all__:
        if name == "__version__":
            continue
        assert name in ns, f"{name} not exported by `from sceneapi_io import *`"


def test_version_is_020() -> None:
    assert sceneapi_io.__version__ == "0.2.0"


def test_sceneio_error_is_an_exception() -> None:
    assert issubclass(SceneIoError, Exception)
    assert isinstance(SceneIoError("boom"), Exception)


def test_key_contract_modules_import_clean() -> None:
    for mod in (
        "sceneapi_io.errors",
        "sceneapi_io.points_binary",
        "sceneapi_io.mapping_input",
        "sceneapi_io.blobstore",
        "sceneapi_io.imagesource",
        "sceneapi_io.colmap_db",
    ):
        assert importlib.import_module(mod) is not None
