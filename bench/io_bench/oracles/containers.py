"""Independent h5py providers for HDF5 and documented hloc layouts."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

H5PY_AVAILABLE = importlib.util.find_spec("h5py") is not None


def _h5py():
    if not H5PY_AVAILABLE:
        raise RuntimeError(
            "HDF5 benchmark providers require the optional h5py package"
        )
    import h5py

    return h5py


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


__all__ = [
    "H5PY_AVAILABLE",
    "_hdf5_oracle_read",
    "_hdf5_oracle_write",
    "_hloc_features_oracle_read",
    "_hloc_features_oracle_write",
    "_hloc_matches_oracle_read",
    "_hloc_matches_oracle_write",
]
