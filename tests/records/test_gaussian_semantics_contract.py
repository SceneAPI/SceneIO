from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "tests/contracts/gaussian_semantics_v1.toml"
CONTRACT = tomllib.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_gaussian_semantics_contract_covers_every_carrier_once():
    assert CONTRACT["schema_version"] == 1
    assert CONTRACT["record"] == "sceneio.GaussianCloud"
    carriers = CONTRACT["carriers"]
    assert tuple(row["id"] for row in carriers) == (
        "gaussian_ply",
        "compressed_ply",
        "sog",
        "ksplat",
        "spz",
        "splat",
        "usd_gaussian",
    )
    assert len({row["id"] for row in carriers}) == len(carriers)

    vocabulary = CONTRACT["vocabulary"]
    for row in carriers:
        for field in (
            "quaternion_norm",
            "sh_basis",
            "sh_phase",
            "sh_coefficient_order",
            "color_space",
            "scale_to_meters_source",
        ):
            assert row[field] in vocabulary[field], (row["id"], field)
        coordinate = row["coordinate_frame"]
        assert coordinate == "file_declared" or coordinate in vocabulary[
            "coordinate_frame"
        ]
        assert row["quaternion_order"] in {"wxyz", "xyzw"}
        assert row["degrees"] == sorted(set(row["degrees"]))
        assert set(row["degrees"]) <= {0, 1, 2, 3}
        assert row["evidence"]
        for item in row["evidence"]:
            if item.startswith("tests/"):
                assert (ROOT / item).is_file(), (row["id"], item)
            else:
                assert item.startswith("https://github.com/"), item


def test_gaussian_semantics_contract_pins_exact_3dgs_basis_equations():
    sh = CONTRACT["spherical_harmonics"]
    assert sh == {
        "basis": "3dgs_real",
        "normalization": "orthonormal",
        "phase": "3dgs",
        "coefficient_order": "degree_then_m_neg_to_pos",
        "dc_equation": "rgb = 0.5 + 0.28209479177387814 * sh_dc",
        "degree_one_equation": (
            "rgb = dc - C1*y*c_1n1 + C1*z*c_10 - C1*x*c_1p1"
        ),
        "reference": (
            "https://github.com/graphdeco-inria/gaussian-splatting/"
            "blob/54c035f7834b564019656c3e3fcc3646292f727d/"
            "utils/sh_utils.py"
        ),
    }


def test_native_and_usd_readers_map_the_frozen_semantic_fields():
    native_expectations = {
        "compressed_ply.cpp": 'cloud.quaternion_norm = "unit"',
        "sog.cpp": 'cloud.quaternion_norm = "unit"',
        "ksplat.cpp": 'cloud.quaternion_norm = "unit"',
        "spz.cpp": 'g.quaternion_norm = "unit"',
        "splat.cpp": 'g.quaternion_norm = "unit"',
    }
    native_root = ROOT / "src/cpp/codecs/splats"
    for filename, marker in native_expectations.items():
        assert marker in (native_root / filename).read_text(encoding="utf-8")

    usd_source = (ROOT / "src/sceneio/io/_usd/gaussians.py").read_text(
        encoding="utf-8"
    )
    for marker in (
        '"quaternion_norm": "unit"',
        '"sh_basis": "3dgs_real"',
        '"sh_phase": "3dgs"',
        '"sh_coefficient_order": "degree_then_m_neg_to_pos"',
        '"scale_to_meters_source": (',
    ):
        assert marker in usd_source
