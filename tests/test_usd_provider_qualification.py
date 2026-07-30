from __future__ import annotations

import base64
import hashlib
import importlib.metadata
from pathlib import Path

import numpy as np
import tinyusdz

# Unmodified Apache-2.0 fixture bytes from AOUSD Core Specification
# Supplemental 1.0.1.post0, peeled release commit c15ae0cad3ed:
# releases/1.0.1/file_formats/tests/assets/binary/gen_timesamples.usdc
_AOUSD_CRATE_10_TIMESAMPLES = (
    "UFhSLVVTREMACgAAAAAAAJkCAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAwAAAAEAAAAAAAAABgAAAGgA"
    "AAAAAAAACwAAAAAAAAAAAAAAAAAAAAAAAAAAAPA/AAAAAAAAAEAAAAAAAAAIQAAAAAAAABBAAAAA"
    "AAAAFEAAAAAAAAAYQAAAAAAAABxAAAAAAAAAIEAAAAAAAAAiQAAAAAAAACZAeAAAAAAAMAAIAAAA"
    "AAAAAAsAAAAAAAAAAAAAAAAACEAAAIA/AAAIQAAAAEAAAAhAAABAQAAACEAAAIBAAAAIQAAAoEAA"
    "AAhAAADAQAAACEAAAOBAAAAIQAAAAEEAAAhAAAAQQQAACEAAAAAAAAAzQAoAAAAAAAAAUAAAAAAA"
    "AABTAAAAAAAAAADwQTstKQAAcHJpbUNoaWxkcmVuAHJvb3QAc3BlY2lmaWVyAHByb3BlcnRpZXMA"
    "YW5pbWF0ZWQAdHlwZU5hbWUAZmxvYXQAdGltZVNhbXBsZXMAAAAAAAAAAAAFAAAAAAAAAAkAAAAA"
    "AAAAAHACAAAAEAABJAAAAAAAAAAAIFgAAQAQKQUAYQAAACpAZAgAMSkACAgAoAtAcAAAAAAALgAI"
    "AAAAAAAAAA4AAAAAAAAAAMABAAAAFUUA/wL9BPsDAAAAAAAAAAMAAAAAAAAACAAAAAAAAAAAYAEA"
    "AAABAAkAAAAAAAAAAHACAAAAEQH3CAAAAAAAAAAAYP////8EAAMAAAAAAAAACAAAAAAAAAAAYAEA"
    "AAABAAkAAAAAAAAAAHADAAAABQACCQAAAAAAAAAAcAcAAAAU//sGAAAAAAAAAFRPS0VOUwAAAAAA"
    "AAAAAABIAQAAAAAAAGsAAAAAAAAAU1RSSU5HUwAAAAAAAAAAALMBAAAAAAAACAAAAAAAAABGSUVM"
    "RFMAAAAAAAAAAAAAuwEAAAAAAABFAAAAAAAAAEZJRUxEU0VUUwAAAAAAAAAAAgAAAAAAAB4AAAAA"
    "AAAAUEFUSFMAAAAAAAAAAAAAAB4CAAAAAAAAQQAAAAAAAABTUEVDUwAAAAAAAAAAAAAAXwIAAAAA"
    "AAA6AAAAAAAAAA=="
)

_GAUSSIAN_USDA = """#usda 1.0
def ParticleField3DGaussianSplat "GSplat"
{
    point3f[] positions = [(0, 0, 0), (1, 2, 3)]
    quatf[] orientations = [(1, 0.25, 0.5, 0.75), (0.5, -0.25, -0.5, -0.75)]
    float3[] scales = [(1, 1, 1), (2, 3, 4)]
    float[] opacities = [1, 0.5]
    uniform int radiance:sphericalHarmonicsDegree = 0
    float3[] radiance:sphericalHarmonicsCoefficients = [
        (1, 0, 0), (0, 1, 0)
    ]
    uniform token projectionModeHint = "perspective"
    uniform token sortingModeHint = "zDepth"
}
"""


def test_aousd_crate_10_timesamples_exposes_provider_boundary(tmp_path):
    raw = base64.b64decode(_AOUSD_CRATE_10_TIMESAMPLES, validate=True)
    assert hashlib.sha256(raw).hexdigest() == (
        "0155f5e4e9b8839a685728131c6c35d32981fcc74b8cb23cb8abead8a49cd420"
    )
    assert raw[:10] == b"PXR-USDC\x00\x0a"
    path = tmp_path / "aousd-timesamples.usdc"
    path.write_bytes(raw)

    prim = tinyusdz.load(str(path)).root_prims()[0]
    assert (prim.name, prim.type_name, prim.property_names()) == (
        "root",
        "Model",
        ["animated"],
    )
    samples = prim.get_attribute_timesamples("animated")
    assert [time for time, _ in samples] == [
        0.0,
        1.0,
        2.0,
        3.0,
        4.0,
        5.0,
        6.0,
        7.0,
        8.0,
        9.0,
        11.0,
    ]
    assert all("[invalid]" in repr(value) for _, value in samples)


def test_tinyusdz_usd_forwarding_and_asset_value_boundary(tmp_path):
    (tmp_path / "payload.bin").write_bytes(b"fixture")
    path = tmp_path / "asset.usd"
    path.write_text(
        """#usda 1.0
def Scope "Root"
{
    asset source = @payload.bin@
}
""",
        encoding="utf-8",
    )

    assert tinyusdz.detect_format(str(path)) == "usda"
    prim = tinyusdz.load(str(path)).root_prims()[0]
    assert (prim.name, prim.type_name, prim.property_names()) == (
        "Root",
        "Scope",
        ["source"],
    )
    assert "[invalid]" in repr(prim.get_attribute("source").value)


def test_tinyusdz_version_and_official_gaussian_schema_probe():
    assert importlib.metadata.version("tinyusdz") == "0.9.4"

    prim = tinyusdz.loads(_GAUSSIAN_USDA).root_prims()[0]

    assert prim.type_name == "ParticleField3DGaussianSplat"
    assert prim.property_names() == [
        "opacities",
        "orientations",
        "positions",
        "projectionModeHint",
        "radiance:sphericalHarmonicsCoefficients",
        "radiance:sphericalHarmonicsDegree",
        "scales",
        "sortingModeHint",
    ]
    np.testing.assert_array_equal(
        np.asarray(prim.get_attribute("positions").value),
        np.array([[0, 0, 0], [1, 2, 3]], np.float32),
    )
    # TinyUSDZ exposes Gf quaternion storage as imaginary XYZ followed by real.
    np.testing.assert_array_equal(
        np.asarray(prim.get_attribute("orientations").value),
        np.array(
            [[0.25, 0.5, 0.75, 1], [-0.25, -0.5, -0.75, 0.5]],
            np.float32,
        ),
    )


def test_tinyusdz_usdc_writer_probe_is_not_current_writer_qualification(
    tmp_path,
):
    path = tmp_path / "probe.usdc"
    stage = tinyusdz.loads(_GAUSSIAN_USDA)

    stage.save(str(path))
    raw = path.read_bytes()

    assert raw.startswith(b"PXR-USDC\x00")
    assert raw[9] == 8  # locally observed crate 0.8
    assert tinyusdz.detect_format(str(path)) == "usdc"
    decoded = tinyusdz.load(str(path)).root_prims()[0]
    assert decoded.type_name == "ParticleField3DGaussianSplat"


def _write_composition_inputs(root: Path) -> dict[str, Path]:
    (root / "base.usda").write_text(
        """#usda 1.0
def Xform "World"
{
    def Mesh "Surface"
    {
        point3f[] points = [(0, 0, 0)]
        int[] faceVertexCounts = []
        int[] faceVertexIndices = []
    }
}
""",
        encoding="utf-8",
    )
    values = {
        "sublayer": """#usda 1.0
(
    subLayers = [@base.usda@]
)
""",
        "reference": """#usda 1.0
def Xform "Root"
{
    def Xform "Arc" (
        references = @base.usda@</World>
    )
    {
    }
}
""",
        "payload": """#usda 1.0
def Xform "Root"
{
    def Xform "Arc" (
        payload = @base.usda@</World>
    )
    {
    }
}
""",
        "variant": """#usda 1.0
def Xform "Root" (
    variants = {
        string model = "A"
    }
    prepend variantSets = "model"
)
{
    variantSet "model" = {
        "A" {
            def Xform "Chosen" {
            }
        }
        "B" {
            def Xform "Other" {
            }
        }
    }
}
""",
    }
    result = {}
    for name, text in values.items():
        path = root / f"{name}.usda"
        path.write_text(text, encoding="utf-8")
        result[name] = path
    return result


def test_tinyusdz_load_is_raw_not_evaluated_composition(tmp_path):
    paths = _write_composition_inputs(tmp_path)

    assert list(tinyusdz.traverse(tinyusdz.load(str(paths["sublayer"])))) == []
    for name in ("reference", "payload"):
        prims = list(tinyusdz.traverse(tinyusdz.load(str(paths[name]))))
        assert [(prim.name, prim.type_name) for prim in prims] == [
            ("Root", "Xform"),
            ("Arc", "Xform"),
        ]
    variants = list(
        tinyusdz.traverse(tinyusdz.load(str(paths["variant"])))
    )
    assert [(prim.name, prim.type_name) for prim in variants] == [
        ("Root", "Xform")
    ]
