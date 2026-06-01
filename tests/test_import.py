import sceneio


def test_import_exposes_version() -> None:
    assert isinstance(sceneio.__version__, str)
