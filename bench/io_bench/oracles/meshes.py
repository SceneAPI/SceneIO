"""Independent library-backed oracles for mesh benchmark codecs."""

from __future__ import annotations

import io

try:
    import trimesh
except Exception:
    trimesh = None


def _trimesh_ply_w(payload):
    mesh = trimesh.Trimesh(
        vertices=payload["positions"],
        faces=payload["faces"],
        vertex_normals=payload["vertex_normals"],
        vertex_colors=payload["vertex_colors"],
        process=False,
    )
    return trimesh.exchange.ply.export_ply(
        mesh, encoding="binary_little_endian"
    )


def _trimesh_ply_r(data):
    return trimesh.load(
        io.BytesIO(data),
        file_type="ply",
        process=False,
        maintain_order=True,
        force="mesh",
    )


def _trimesh_obj_w(payload):
    mesh = trimesh.Trimesh(
        vertices=payload["positions"],
        faces=payload["faces"],
        vertex_normals=payload["vertex_normals"],
        vertex_colors=payload["vertex_colors"],
        process=False,
    )
    return trimesh.exchange.obj.export_obj(
        mesh,
        include_normals=True,
        include_color=True,
    ).encode()


def _trimesh_obj_r(data):
    return trimesh.load(
        io.BytesIO(data),
        file_type="obj",
        process=False,
        maintain_order=True,
        force="mesh",
    )


def _trimesh_stl_w(payload):
    mesh = trimesh.Trimesh(
        vertices=payload["positions"],
        faces=payload["faces"],
        process=False,
    )
    return trimesh.exchange.stl.export_stl(mesh)


def _trimesh_stl_r(data):
    return trimesh.load(
        io.BytesIO(data),
        file_type="stl",
        process=False,
        maintain_order=True,
        force="mesh",
    )


def _trimesh_off_w(payload):
    mesh = trimesh.Trimesh(
        vertices=payload["positions"],
        faces=payload["faces"],
        process=False,
    )
    exported = mesh.export(file_type="off")
    return exported.encode() if isinstance(exported, str) else exported


def _trimesh_off_r(data):
    return trimesh.load(
        io.BytesIO(data),
        file_type="off",
        process=False,
        maintain_order=True,
        force="mesh",
    )


def _trimesh_glb_w(payload):
    mesh = trimesh.Trimesh(
        vertices=payload["positions"],
        faces=payload["faces"],
        vertex_normals=payload["normals"],
        vertex_colors=payload["colors"],
        process=False,
    )
    return trimesh.exchange.gltf.export_glb(
        trimesh.Scene(mesh)
    )


def _trimesh_glb_r(data):
    return trimesh.load(
        io.BytesIO(data),
        file_type="glb",
        process=False,
        maintain_order=True,
        force="scene",
    )


def _trimesh_gltf_w(payload):
    mesh = trimesh.Trimesh(
        vertices=payload["positions"],
        faces=payload["faces"],
        vertex_normals=payload["normals"],
        vertex_colors=payload["colors"],
        process=False,
    )
    return trimesh.exchange.gltf.export_gltf(
        trimesh.Scene(mesh)
    )


def _trimesh_gltf_r(files):
    document = next(
        name for name in files if name.endswith(".gltf")
    )
    return trimesh.load(
        io.BytesIO(files[document]),
        file_type="gltf",
        resolver=files,
        process=False,
        maintain_order=True,
        force="scene",
    )


__all__ = [
    "_trimesh_glb_r",
    "_trimesh_glb_w",
    "_trimesh_gltf_r",
    "_trimesh_gltf_w",
    "_trimesh_obj_r",
    "_trimesh_obj_w",
    "_trimesh_off_r",
    "_trimesh_off_w",
    "_trimesh_ply_r",
    "_trimesh_ply_w",
    "_trimesh_stl_r",
    "_trimesh_stl_w",
    "trimesh",
]
