"""Executable OpenUSD oracle for SceneIO's bounded Gaussian USDA/USDZ profile.

The normal test environment intentionally does not install OpenUSD.  The
focused oracle workflow installs the pinned ``usd-core`` release and runs this
module, while local runs without that provider are reported as skips.
"""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip(
    "pxr",
    reason=(
        "OpenUSD oracle is optional; install usd-core==26.8 for this suite"
    ),
)

try:
    _USD_CORE_VERSION = importlib.metadata.version("usd-core")
except importlib.metadata.PackageNotFoundError:
    pytest.skip(
        "OpenUSD oracle requires the usd-core distribution",
        allow_module_level=True,
    )
if _USD_CORE_VERSION != "26.8":
    pytest.skip(
        "OpenUSD oracle suite is pinned to usd-core==26.8; "
        f"found {_USD_CORE_VERSION}",
        allow_module_level=True,
    )

from pxr import Gf, Sdf, Usd, UsdUtils

import sceneio
from sceneio import _core

_PROFILE = "usd-3dcv-1"
_GAUSSIAN_TYPE = "ParticleField3DGaussianSplat"
_COUNT = 2
_DEGREE = 1

_MEANS = np.array([[1.0, 2.0, 3.0], [-4.0, 5.0, -6.0]], np.float32)
_SCALES = np.array([[1.0, 0.5, 2.0], [0.25, 4.0, 1.0]], np.float32)
_QUATERNIONS = np.array(
    [
        [0.82956135, 0.20739034, 0.31108552, 0.41478068],
        [0.72199490, -0.20628425, 0.41256850, -0.51571060],
    ],
    np.float32,
)
_OPACITIES = np.array([0.25, 0.75], np.float32)
_SH_DC = np.array([[-0.5, 0.0, 0.5], [0.25, -0.25, 0.75]], np.float32)
_SH_REST = (
    np.arange(_COUNT * ((_DEGREE + 1) ** 2 - 1) * 3, dtype=np.float32)
    .reshape(_COUNT, ((_DEGREE + 1) ** 2 - 1) * 3)
    / 16.0
    - 1.0
)


def _cloud():
    return _core.gaussian_cloud(
        _MEANS,
        _SCALES,
        _QUATERNIONS,
        _OPACITIES,
        _SH_DC,
        _SH_REST,
        scale_space="linear",
        opacity_space="linear",
        sh_layout="coefficient_rgb",
        source_precision="float32",
        projection_mode_hint="tangential",
        sorting_mode_hint="rayHitDistance",
    )


def _scene():
    return _core.scene_graph(
        ["Cloud"],
        node_payload_kinds=["gaussian_cloud"],
        node_payload_indices=np.array([0], np.uint64),
        gaussian_clouds=[_cloud()],
        up_axis="y",
        meters_per_unit=1.0,
        source_representation="usda",
        default_prim=0,
    )


def _attr(prim, name: str, type_name: str):
    attribute = prim.GetAttribute(name)
    assert attribute, f"missing OpenUSD attribute {name!r}"
    assert str(attribute.GetTypeName()) == type_name, name
    return attribute


def _assert_stage_profile(stage) -> None:
    assert stage.GetMetadata("upAxis") == "Y"
    assert stage.GetMetadata("metersPerUnit") == 1.0
    assert stage.GetDefaultPrim().GetPath() == Sdf.Path("/Cloud")
    prim = stage.GetPrimAtPath("/Cloud")
    assert prim and prim.GetTypeName() == _GAUSSIAN_TYPE

    positions = _attr(prim, "positions", "point3f[]").Get()
    scales = _attr(prim, "scales", "float3[]").Get()
    opacities = _attr(prim, "opacities", "float[]").Get()
    orientations = _attr(prim, "orientations", "quatf[]").Get()
    coefficients = _attr(
        prim,
        "radiance:sphericalHarmonicsCoefficients",
        "float3[]",
    ).Get()
    degree = _attr(
        prim,
        "radiance:sphericalHarmonicsDegree",
        "int",
    ).Get()
    projection = _attr(prim, "projectionModeHint", "token").Get()
    sorting = _attr(prim, "sortingModeHint", "token").Get()
    extent = _attr(prim, "extent", "float3[]").Get()

    np.testing.assert_array_equal(np.asarray(positions), _MEANS)
    np.testing.assert_array_equal(np.asarray(scales), _SCALES)
    np.testing.assert_array_equal(np.asarray(opacities), _OPACITIES)
    # Vt.QuatfArray exposes imaginary XYZ followed by the real component;
    # checking this explicitly catches an XYZW/WXYZ interchange.
    np.testing.assert_allclose(
        np.asarray(orientations),
        _QUATERNIONS[:, [1, 2, 3, 0]],
        atol=2e-6,
        rtol=0,
    )
    coefficients_expected = np.empty((_COUNT, (_DEGREE + 1) ** 2, 3), np.float32)
    coefficients_expected[:, 0] = _SH_DC
    coefficients_expected[:, 1:] = _SH_REST.reshape(_COUNT, -1, 3)
    np.testing.assert_array_equal(
        np.asarray(coefficients), coefficients_expected.reshape(-1, 3)
    )
    assert degree == _DEGREE
    assert projection == "tangential"
    assert sorting == "rayHitDistance"
    assert np.asarray(extent).shape == (2, 3)
    assert np.isfinite(np.asarray(extent)).all()

    coefficient_attribute = _attr(
        prim,
        "radiance:sphericalHarmonicsCoefficients",
        "float3[]",
    )
    assert coefficient_attribute.GetMetadata("interpolation") == "vertex"
    assert coefficient_attribute.GetMetadata("elementSize") == (_DEGREE + 1) ** 2


@pytest.mark.parametrize("suffix", [".usda", ".usdz"])
def test_sceneio_writer_is_readable_by_official_openusd(tmp_path, suffix):
    path = tmp_path / f"sceneio-output{suffix}"
    sceneio.write_scene(_scene(), path, profile=_PROFILE)

    stage = Usd.Stage.Open(str(path))
    assert stage, path
    _assert_stage_profile(stage)


def _author_openusd_stage(path: Path):
    stage = Usd.Stage.CreateNew(str(path))
    assert stage
    stage.SetMetadata("upAxis", "Y")
    stage.SetMetadata("metersPerUnit", 1.0)
    prim = stage.DefinePrim("/Cloud", _GAUSSIAN_TYPE)
    stage.SetDefaultPrim(prim)

    def set_attribute(name: str, type_name, value):
        attribute = prim.CreateAttribute(name, type_name)
        attribute.Set(value)
        return attribute

    set_attribute(
        "positions",
        Sdf.ValueTypeNames.Point3fArray,
        [Gf.Vec3f(*map(float, row)) for row in _MEANS],
    )
    set_attribute(
        "orientations",
        Sdf.ValueTypeNames.QuatfArray,
        [Gf.Quatf(float(row[0]), Gf.Vec3f(*map(float, row[1:]))) for row in _QUATERNIONS],
    )
    set_attribute(
        "scales",
        Sdf.ValueTypeNames.Float3Array,
        [Gf.Vec3f(*map(float, row)) for row in _SCALES],
    )
    set_attribute("opacities", Sdf.ValueTypeNames.FloatArray, _OPACITIES)
    set_attribute(
        "radiance:sphericalHarmonicsDegree",
        Sdf.ValueTypeNames.Int,
        _DEGREE,
    )
    coefficients = np.empty((_COUNT, (_DEGREE + 1) ** 2, 3), np.float32)
    coefficients[:, 0] = _SH_DC
    coefficients[:, 1:] = _SH_REST.reshape(_COUNT, -1, 3)
    coefficient_attribute = set_attribute(
        "radiance:sphericalHarmonicsCoefficients",
        Sdf.ValueTypeNames.Float3Array,
        [
            Gf.Vec3f(*map(float, row))
            for row in coefficients.reshape(-1, 3)
        ],
    )
    coefficient_attribute.SetMetadata("interpolation", "vertex")
    coefficient_attribute.SetMetadata("elementSize", (_DEGREE + 1) ** 2)
    set_attribute("projectionModeHint", Sdf.ValueTypeNames.Token, "perspective")
    set_attribute("sortingModeHint", Sdf.ValueTypeNames.Token, "zDepth")
    assert stage.GetRootLayer().Save()
    return stage


def _assert_sceneio_cloud(scene) -> None:
    cloud = scene.gaussian_cloud_at(0)
    np.testing.assert_array_equal(np.asarray(cloud.means), _MEANS)
    np.testing.assert_array_equal(np.asarray(cloud.scales), _SCALES)
    np.testing.assert_allclose(
        np.asarray(cloud.quaternions), _QUATERNIONS, atol=2e-6, rtol=0
    )
    np.testing.assert_array_equal(np.asarray(cloud.opacities), _OPACITIES)
    np.testing.assert_array_equal(np.asarray(cloud.sh_dc), _SH_DC)
    np.testing.assert_array_equal(np.asarray(cloud.sh_rest), _SH_REST)
    assert cloud.sh_degree == _DEGREE
    assert cloud.scale_space == "linear"
    assert cloud.opacity_space == "linear"
    assert cloud.sh_layout == "coefficient_rgb"
    assert cloud.source_precision == "float32"
    assert cloud.projection_mode_hint == "perspective"
    assert cloud.sorting_mode_hint == "zDepth"


@pytest.mark.parametrize("suffix", [".usda", ".usdz"])
def test_official_openusd_writer_is_readable_by_sceneio(tmp_path, suffix):
    source = tmp_path / "openusd-source.usda"
    _author_openusd_stage(source)
    path = source
    if suffix == ".usdz":
        path = tmp_path / "openusd-source.usdz"
        assert UsdUtils.CreateNewUsdzPackage(
            Sdf.AssetPath(str(source)), str(path)
        )

    scene = sceneio.read_scene(path)
    _assert_sceneio_cloud(scene)
