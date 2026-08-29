"""Generate FC5 provider-qualification vectors with official OpenVDB Python.

This script intentionally depends on the upstream ``pyopenvdb`` bindings and
is not part of SceneIO's runtime or normal test dependencies. Ubuntu 24.04's
``python3-openvdb`` 10.0.1 package is one reproducible oracle environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    import pyopenvdb as openvdb
except ModuleNotFoundError:
    raise SystemExit(
        "install the official pyopenvdb bindings (for Ubuntu: apt install python3-openvdb)"
    ) from None


AFFINE_MATRIX = (
    (0.5, 0.125, 0.0, 0.0),
    (0.0, 1.5, 0.25, 0.0),
    (0.0, 0.0, 2.0, 0.0),
    (10.0, -2.0, 3.0, 1.0),
)


def _float_grid(
    name: str,
    *,
    background: float,
    values: tuple[tuple[tuple[int, int, int], float], ...],
    transform=None,
    grid_class: str = "fog volume",
):
    grid = openvdb.FloatGrid(background)
    grid.name = name
    grid.gridClass = grid_class
    grid.updateMetadata({"sceneio.fixture.role": name})
    if transform is not None:
        grid.transform = transform
    accessor = grid.getAccessor()
    for coordinate, value in values:
        accessor.setValueOn(coordinate, value)
    return grid


def _vector_grid(name: str):
    grid = openvdb.Vec3SGrid((1.0, -2.0, 3.0))
    grid.name = name
    grid.gridClass = "staggered"
    grid.transform = openvdb.createLinearTransform(0.25)
    grid.updateMetadata({"sceneio.fixture.role": name})
    accessor = grid.getAccessor()
    accessor.setValueOn((-4, 2, 7), (0.5, -1.25, 2.0))
    accessor.setValueOn((9, -3, 1), (-4.0, 8.0, 16.0))
    return grid


def _bool_grid(name: str):
    grid = openvdb.BoolGrid(False)
    grid.name = name
    grid.updateMetadata({"sceneio.fixture.role": name})
    grid.getAccessor().setValueOn((-1, 0, 1), True)
    return grid


def generate(output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    density = _float_grid(
        "density",
        background=0.0,
        values=(
            ((-17, 4, 2), 1.25),
            ((0, 0, 0), -2.5),
            ((130, -9, 31), 3.75),
        ),
    )
    temperature = _float_grid(
        "temperature",
        background=-273.15,
        values=(
            ((-8, -7, -6), 12.5),
            ((5, 4, 3), 99.0),
        ),
        transform=openvdb.createLinearTransform(AFFINE_MATRIX),
        grid_class="unknown",
    )
    empty = _float_grid(
        "empty",
        background=4.5,
        values=(),
        transform=openvdb.createLinearTransform(2.0),
        grid_class="unknown",
    )
    empty_zero_background = _float_grid(
        "empty_zero_background",
        background=0.0,
        values=(),
        transform=openvdb.createLinearTransform(2.0),
        grid_class="unknown",
    )
    level_set = _float_grid(
        "surface",
        background=3.0,
        values=(((0, 0, 0), -0.5), ((1, 0, 0), 0.5)),
        grid_class="level set",
    )
    velocity = _vector_grid("velocity")
    mask = _bool_grid("mask")
    duplicate_a = _float_grid(
        "duplicate",
        background=0.0,
        values=(((1, 2, 3), 4.0),),
    )
    duplicate_b = _float_grid(
        "duplicate",
        background=1.0,
        values=(((-1, -2, -3), -4.0),),
    )

    cases = {
        "multi_scalar_transformed.vdb": [density, temperature, empty],
        "scalar_transformed.vdb": [temperature],
        "empty_transformed_zero_background.vdb": [empty_zero_background],
        "level_set.vdb": [level_set],
        "vector_velocity.vdb": [velocity],
        "mixed_types.vdb": [density, velocity, mask],
        "duplicate_names.vdb": [duplicate_a, duplicate_b],
    }
    result: dict[str, object] = {
        "schema_version": "openvdb-provider-vectors-v1",
        "oracle": "pyopenvdb 10.0.1",
        "cases": {},
    }
    for filename, grids in cases.items():
        path = output / filename
        openvdb.write(
            str(path),
            grids=grids,
            metadata={"sceneio.fixture": filename},
        )
        payload = path.read_bytes()
        result["cases"][filename] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "grids": [grid.name for grid in grids],
            "types": [grid.valueTypeName for grid in grids],
        }
    manifest = output / "manifest.json"
    manifest.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(generate(args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["AFFINE_MATRIX", "generate"]
