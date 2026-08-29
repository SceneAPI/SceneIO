"""Independent providers for path-native 3D-CV containers."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import numpy as np

H5PY_AVAILABLE = importlib.util.find_spec("h5py") is not None
ZARR_AVAILABLE = importlib.util.find_spec("zarr") is not None
PYE57_AVAILABLE = importlib.util.find_spec("pye57") is not None
PYARROW_AVAILABLE = importlib.util.find_spec("pyarrow") is not None
TINYVDB_AVAILABLE = importlib.util.find_spec("tinyvdb") is not None
TINYUSDZ_AVAILABLE = importlib.util.find_spec("tinyusdz") is not None


def _h5py():
    if not H5PY_AVAILABLE:
        raise RuntimeError(
            "HDF5 benchmark providers require the optional h5py package"
        )
    import h5py

    return h5py


def _zarr():
    if not ZARR_AVAILABLE:
        raise RuntimeError(
            "Zarr benchmark providers require the optional zarr package"
        )
    import zarr

    return zarr


def _pye57():
    if not PYE57_AVAILABLE:
        raise RuntimeError(
            "E57 benchmark providers require the optional pye57 package"
        )
    import pye57

    return pye57


def _pyarrow():
    if not PYARROW_AVAILABLE:
        raise RuntimeError(
            "columnar benchmark providers require the optional pyarrow package"
        )
    import pyarrow as pa
    import pyarrow.ipc as ipc
    import pyarrow.parquet as pq

    return pa, ipc, pq


def _tinyvdb():
    if not TINYVDB_AVAILABLE:
        raise RuntimeError(
            "OpenVDB benchmark providers require the optional tinyvdb package"
        )
    import tinyvdb

    return tinyvdb


def _tinyusdz():
    if not TINYUSDZ_AVAILABLE:
        raise RuntimeError(
            "USD benchmark providers require the optional tinyusdz package"
        )
    import tinyusdz

    return tinyusdz


def _hdf5_oracle_write(payload, path: str | Path) -> None:
    h5py = _h5py()
    with h5py.File(path, "w") as handle:
        for name, value in payload["attrs"].items():
            handle.attrs[name] = value
        for name, value in payload["arrays"].items():
            handle.create_dataset(name, data=value)


def _hdf5_oracle_read(path: str | Path):
    h5py = _h5py()
    arrays = {}
    with h5py.File(path, "r") as handle:
        handle.visititems(
            lambda name, value: (
                arrays.__setitem__(name, np.asarray(value[...]))
                if isinstance(value, h5py.Dataset)
                else None
            )
        )
        attrs = {
            str(name): str(value)
            for name, value in handle.attrs.items()
            if str(name) not in {"sceneio_format", "sceneio_schema_version"}
        }
    return {"arrays": arrays, "attrs": attrs}


def _hloc_features_oracle_write(payload, path: str | Path) -> None:
    h5py = _h5py()
    with h5py.File(path, "w", libver="latest") as handle:
        for name, values in payload.items():
            group = handle.create_group(name)
            keypoints = group.create_dataset(
                "keypoints",
                data=values["keypoints"],
            )
            if values["uncertainty"] is not None:
                keypoints.attrs["uncertainty"] = values["uncertainty"]
            group.create_dataset(
                "descriptors",
                data=np.ascontiguousarray(values["descriptors"].T),
            )
            group.create_dataset("scores", data=values["scores"])
            group.create_dataset("image_size", data=values["image_size"])


def _hloc_features_oracle_read(path: str | Path):
    h5py = _h5py()
    result = {}
    with h5py.File(path, "r", libver="latest") as handle:
        for name, group in handle.items():
            if not isinstance(group, h5py.Group):
                continue
            result[name] = {
                "keypoints": np.asarray(group["keypoints"][...]),
                "descriptors": np.ascontiguousarray(
                    np.asarray(group["descriptors"][...]).T
                ),
                "scores": np.asarray(group["scores"][...]),
                "image_size": np.asarray(group["image_size"][...]),
                "uncertainty": float(
                    group["keypoints"].attrs["uncertainty"]
                ),
            }
    return result


def _hloc_matches_oracle_write(payload, path: str | Path) -> None:
    h5py = _h5py()
    with h5py.File(path, "w", libver="latest") as handle:
        for (name0, name1), values in payload.items():
            group = handle.create_group(f"{name0}/{name1}")
            group.create_dataset("matches0", data=values["matches0"])
            if values["matching_scores0"] is not None:
                group.create_dataset(
                    "matching_scores0",
                    data=values["matching_scores0"],
                )


def _hloc_matches_oracle_read(path: str | Path):
    h5py = _h5py()
    result = {}
    with h5py.File(path, "r", libver="latest") as handle:
        pair_groups = []

        def visit(name, value):
            if isinstance(value, h5py.Group) and "matches0" in value:
                pair_groups.append((name, value))

        handle.visititems(visit)
        for storage_name, group in pair_groups:
            name0 = str(group.attrs.get("name0", storage_name.split("/")[0]))
            name1 = str(group.attrs.get("name1", storage_name.split("/")[1]))
            result[(name0, name1)] = {
                "matches0": np.asarray(group["matches0"][...]),
                "matching_scores0": (
                    np.asarray(group["matching_scores0"][...])
                    if "matching_scores0" in group
                    else None
                ),
            }
    return result


def _zarr_oracle_write(payload, path: str | Path) -> None:
    zarr = _zarr()
    group = zarr.open_group(
        path,
        mode="w",
        zarr_format=3,
        attributes=payload["attrs"],
    )
    for name, value in payload["arrays"].items():
        group.create_array(name, data=value)


def _zarr_oracle_read(path: str | Path):
    zarr = _zarr()
    group = zarr.open_group(path, mode="r", use_consolidated=None)
    arrays = {
        name: np.asarray(value[...])
        for name, value in group.members(max_depth=None)
        if isinstance(value, zarr.Array)
    }
    return {"arrays": arrays, "attrs": dict(group.attrs)}


def _e57_oracle_write(payload, path: str | Path) -> None:
    pye57 = _pye57()
    positions = payload["positions"]
    colors = payload["colors"]
    data = {
        "cartesianX": positions[:, 0],
        "cartesianY": positions[:, 1],
        "cartesianZ": positions[:, 2],
        "colorRed": colors[:, 0],
        "colorGreen": colors[:, 1],
        "colorBlue": colors[:, 2],
        "intensity": payload["intensity"],
    }
    viewpoint = payload["viewpoint"]
    with pye57.E57(str(path), mode="w") as destination:
        destination.write_scan_raw(
            data,
            translation=viewpoint[:3],
            rotation=viewpoint[3:],
        )


def _e57_oracle_read(path: str | Path):
    pye57 = _pye57()
    with pye57.E57(str(path)) as source:
        raw = source.read_scan_raw(0)
        header = source.get_header(0)
        positions = np.column_stack(
            (
                raw["cartesianX"],
                raw["cartesianY"],
                raw["cartesianZ"],
            )
        ).astype(np.float32, copy=False)
        colors = np.column_stack(
            (
                raw["colorRed"],
                raw["colorGreen"],
                raw["colorBlue"],
            )
        ).astype(np.uint8, copy=False)
        viewpoint = np.concatenate(
            (
                np.asarray(header.translation, dtype=np.float64),
                np.asarray(header.rotation, dtype=np.float64),
            )
        )
        return {
            "positions": positions,
            "colors": colors,
            "intensity": np.asarray(raw["intensity"], dtype=np.float32),
            "viewpoint": viewpoint,
        }


def _arrow_table(payload):
    pa, _ipc, _pq = _pyarrow()
    columns = {}
    for name, value in payload["arrays"].items():
        if value.ndim == 1:
            columns[name] = pa.array(value)
        else:
            columns[name] = pa.FixedSizeListArray.from_arrays(
                pa.array(value.reshape(-1)),
                value.shape[1],
            )
    metadata = {b"sceneio.schema": b"sceneio.numeric_table.v1"}
    metadata.update(
        {
            b"sceneio.attr." + name.encode(): value.encode()
            for name, value in payload["attrs"].items()
        }
    )
    return pa.table(columns).replace_schema_metadata(metadata)


def _columnar_oracle_write(
    payload, path: str | Path, *, format_id: str
) -> None:
    pa, ipc, pq = _pyarrow()
    table = _arrow_table(payload)
    if format_id == "parquet":
        pq.write_table(
            table,
            path,
            compression="zstd",
            use_dictionary=False,
            write_statistics=True,
        )
        return
    with (
        pa.OSFile(str(path), "wb") as sink,
        ipc.new_file(sink, table.schema) as writer,
    ):
        writer.write_table(table)


def _columnar_oracle_read(path: str | Path, *, format_id: str):
    pa, ipc, pq = _pyarrow()
    if format_id == "parquet":
        table = pq.read_table(path, memory_map=True, use_threads=True)
    else:
        with pa.memory_map(str(path), "r") as source:
            table = ipc.open_file(source).read_all()
    arrays = {}
    for name in table.column_names:
        column = table[name].combine_chunks()
        if pa.types.is_fixed_size_list(column.type):
            arrays[name] = column.values.to_numpy(
                zero_copy_only=False
            ).reshape(len(column), column.type.list_size)
        else:
            arrays[name] = column.to_numpy(zero_copy_only=False)
    metadata = table.schema.metadata or {}
    attrs = {
        key.removeprefix(b"sceneio.attr.").decode(): value.decode()
        for key, value in metadata.items()
        if key.startswith(b"sceneio.attr.")
    }
    return {"arrays": arrays, "attrs": attrs}


def _openvdb_oracle_write(payload, path: str | Path) -> None:
    tinyvdb = _tinyvdb()
    from sceneio.io import _openvdb

    source = tinyvdb.open(str(_openvdb._TEMPLATE))
    try:
        source.read_grids()
        source.replace_grid_from_sparse(
            0,
            payload["arrays"]["coords"],
            payload["arrays"]["values"],
            payload["attrs"]["name"],
            0.0,
        )
        source.save(
            str(path),
            compression=tinyvdb.COMPRESS_ZIP
            | tinyvdb.COMPRESS_ACTIVE_MASK,
        )
    finally:
        source.close()


def _openvdb_oracle_read(path: str | Path):
    tinyvdb = _tinyvdb()
    source = tinyvdb.open(str(path))
    try:
        source.read_grids()
        grid = source.grid(0)
        sparse = grid.to_sparse()
        count = int(sparse["count"])
        return {
            "arrays": {
                "coords": np.frombuffer(
                    sparse["coords"], dtype=np.int32
                ).reshape(count, 3).copy(),
                "values": np.frombuffer(
                    sparse["values"], dtype=np.float32
                ).copy(),
            },
            "attrs": {"name": str(grid.name)},
        }
    finally:
        source.close()


def _usd_source(payload) -> str:
    arrays = payload["arrays"]
    output = io.StringIO()
    output.write(
        '#usda 1.0\n(\n    upAxis = "Y"\n    metersPerUnit = 1\n)\n'
        f'def Mesh "{payload["attrs"]["node_name"]}"\n{{\n'
    )

    def rows(name, type_name, *, usd_name=None, interpolation=None):
        values = arrays[name]
        output.write(f"    {type_name} {usd_name or name} = [")
        output.write(
            ", ".join(
                "("
                + ", ".join(format(float(value), ".9g") for value in row)
                + ")"
                for row in values
            )
        )
        output.write("]")
        if interpolation is not None:
            output.write(
                ' (\n        interpolation = "'
                + interpolation
                + '"\n    )'
            )
        output.write("\n")

    rows("positions", "point3f[]", usd_name="points")
    counts = np.diff(arrays["face_offsets"])
    output.write(
        "    int[] faceVertexCounts = ["
        + ", ".join(str(int(value)) for value in counts)
        + "]\n"
    )
    output.write(
        "    int[] faceVertexIndices = ["
        + ", ".join(str(int(value)) for value in arrays["face_indices"])
        + "]\n"
    )
    rows(
        "vertex_normals",
        "normal3f[]",
        usd_name="normals",
        interpolation="vertex",
    )
    rows(
        "vertex_uvs",
        "texCoord2f[]",
        usd_name="primvars:st",
        interpolation="vertex",
    )
    return (
        output.getvalue()
        + '    uniform token subdivisionScheme = "none"\n}\n'
    )


def _usd_oracle_write(payload, path: str | Path) -> None:
    tinyusdz = _tinyusdz()
    stage = tinyusdz.loads(_usd_source(payload))
    stage.save(str(path))


def _usd_oracle_read(path: str | Path):
    tinyusdz = _tinyusdz()
    stage = tinyusdz.load(str(path))
    meshes = [
        prim for prim in tinyusdz.traverse(stage) if prim.type_name == "Mesh"
    ]
    if len(meshes) != 1:
        raise AssertionError("USD benchmark oracle expected one mesh")
    mesh = meshes[0]
    counts = np.asarray(
        mesh.get_attribute("faceVertexCounts").value, dtype=np.int32
    )
    return {
        "arrays": {
            "positions": np.asarray(
                mesh.get_attribute("points").value, dtype=np.float32
            ),
            "face_offsets": np.concatenate(
                (
                    np.zeros(1, dtype=np.uint64),
                    np.cumsum(counts, dtype=np.uint64),
                )
            ),
            "face_indices": np.asarray(
                mesh.get_attribute("faceVertexIndices").value,
                dtype=np.uint64,
            ),
            "vertex_normals": np.asarray(
                mesh.get_attribute("normals").value, dtype=np.float32
            ),
            "vertex_uvs": np.asarray(
                mesh.get_attribute("primvars:st").value, dtype=np.float32
            ),
        },
        "attrs": {"node_name": str(mesh.name)},
    }


__all__ = [
    "H5PY_AVAILABLE",
    "PYARROW_AVAILABLE",
    "PYE57_AVAILABLE",
    "TINYUSDZ_AVAILABLE",
    "TINYVDB_AVAILABLE",
    "ZARR_AVAILABLE",
    "_columnar_oracle_read",
    "_columnar_oracle_write",
    "_e57_oracle_read",
    "_e57_oracle_write",
    "_hdf5_oracle_read",
    "_hdf5_oracle_write",
    "_hloc_features_oracle_read",
    "_hloc_features_oracle_write",
    "_hloc_matches_oracle_read",
    "_hloc_matches_oracle_write",
    "_openvdb_oracle_read",
    "_openvdb_oracle_write",
    "_usd_oracle_read",
    "_usd_oracle_write",
    "_zarr_oracle_read",
    "_zarr_oracle_write",
]
