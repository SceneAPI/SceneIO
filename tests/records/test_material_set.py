"""Canonical MaterialSet construction, validation, views, and lifetime."""

from __future__ import annotations

import copy
import gc
import pickle

import numpy as np
import pytest

import sceneio
from sceneio import _core


def _full_materials():
    return _core.material_set(
        ["matte", "金属"],
        base_colors=np.array(
            [[0.2, 0.3, 0.4, 1.0], [0.8, 0.7, 0.6, 0.5]],
            np.float32,
        ),
        emissive_colors=np.array(
            [[0.0, 0.1, 0.0], [2.0, 1.0, 0.5]], np.float32
        ),
        metallic=np.array([0.0, 1.0], np.float32),
        roughness=np.array([0.9, 0.1], np.float32),
        alpha_modes=["opaque", "blend"],
        alpha_cutoffs=np.array([0.5, 0.25], np.float32),
        texture_materials=np.array([0, 1, 1], np.uint64),
        texture_semantics=["base_color", "normal", "emissive"],
        texture_paths=["textures/albedo.png", "normal.png", "发光.exr"],
        texture_uv_sets=np.array([0, 2, 1], np.uint32),
        texture_wrap_s=["repeat", "clamp", "mirrored_repeat"],
        texture_wrap_t=["clamp", "repeat", "mirrored_repeat"],
        texture_min_filters=[
            "linear_mipmap_linear",
            "nearest",
            "unspecified",
        ],
        texture_mag_filters=["linear", "nearest", "unspecified"],
    )


def test_public_export_defaults_and_repr():
    assert sceneio.MaterialSet is _core.MaterialSet
    materials = _core.material_set([])
    assert materials.num_materials == 0
    assert materials.num_textures == 0
    assert materials.names == []
    assert materials.texture_paths == []
    assert materials.base_colors.shape == (0, 4)
    assert materials.emissive_colors.shape == (0, 3)
    assert materials.metallic.shape == (0,)
    assert materials.roughness.shape == (0,)
    assert materials.alpha_modes == []
    assert materials.alpha_cutoffs.shape == (0,)
    assert materials.name_offsets.tolist() == [0]
    assert materials.texture_path_offsets.tolist() == [0]
    assert repr(materials) == "<MaterialSet materials=0 textures=0>"

    one = _core.material_set(["default"])
    np.testing.assert_array_equal(one.base_colors, [[1, 1, 1, 1]])
    np.testing.assert_array_equal(one.emissive_colors, [[0, 0, 0]])
    np.testing.assert_array_equal(one.metallic, [0])
    np.testing.assert_array_equal(one.roughness, [1])
    assert one.alpha_modes == ["opaque"]
    np.testing.assert_array_equal(one.alpha_cutoffs, [0.5])


def test_full_fields_and_utf8_tables_are_exact():
    materials = _full_materials()
    assert materials.num_materials == 2
    assert materials.num_textures == 3
    assert materials.names == ["matte", "金属"]
    assert bytes(materials.name_utf8) == "matte金属".encode()
    assert materials.name_offsets.tolist() == [
        0,
        len(b"matte"),
        len("matte金属".encode()),
    ]
    assert materials.alpha_modes == ["opaque", "blend"]
    assert materials.alpha_mode_codes.tolist() == [0, 2]
    assert materials.texture_semantics == [
        "base_color",
        "normal",
        "emissive",
    ]
    assert materials.texture_semantic_codes.tolist() == [0, 4, 7]
    assert materials.texture_paths == [
        "textures/albedo.png",
        "normal.png",
        "发光.exr",
    ]
    assert materials.texture_materials.tolist() == [0, 1, 1]
    assert materials.texture_uv_sets.tolist() == [0, 2, 1]
    assert materials.texture_wrap_s_codes.tolist() == [0, 1, 2]
    assert materials.texture_wrap_t_codes.tolist() == [1, 0, 2]
    assert materials.texture_min_filter_codes.tolist() == [6, 1, 0]
    assert materials.texture_mag_filter_codes.tolist() == [2, 1, 0]


@pytest.mark.parametrize(
    "name",
    [
        "base_colors",
        "emissive_colors",
        "metallic",
        "roughness",
        "alpha_mode_codes",
        "alpha_cutoffs",
        "texture_materials",
        "texture_semantic_codes",
        "texture_uv_sets",
        "texture_wrap_s_codes",
        "texture_wrap_t_codes",
        "texture_min_filter_codes",
        "texture_mag_filter_codes",
    ],
)
def test_numeric_views_are_zero_copy_writable_and_keep_parent_alive(name):
    materials = _full_materials()
    view = getattr(materials, name)
    pointer = view.__array_interface__["data"][0]
    assert pointer == getattr(materials, name).__array_interface__["data"][0]
    mirror = np.from_dlpack(view)
    assert np.shares_memory(view, mirror)

    del materials
    gc.collect()
    assert view.__array_interface__["data"][0] == pointer
    if view.size:
        original = view.reshape(-1)[0].item()
        view.reshape(-1)[0] = original


@pytest.mark.parametrize(
    "name",
    [
        "name_offsets",
        "name_utf8",
        "texture_path_offsets",
        "texture_path_utf8",
    ],
)
def test_string_table_views_are_zero_copy_read_only_and_keep_parent_alive(name):
    materials = _full_materials()
    view = getattr(materials, name)
    assert not view.flags.writeable
    pointer = view.__array_interface__["data"][0]
    del materials
    gc.collect()
    assert view.__array_interface__["data"][0] == pointer
    if view.size:
        with pytest.raises(ValueError):
            view[0] = 1


def test_inputs_are_copied_and_canonicalize_noncontiguous_foreign_dtypes():
    base = np.ones((2, 4), np.float32)
    materials = _core.material_set(["a", "b"], base_colors=base)
    base[:] = 0
    np.testing.assert_array_equal(materials.base_colors, np.ones((2, 4)))

    noncontiguous = np.zeros((2, 8), np.float32)[:, ::2]
    assert not noncontiguous.flags.c_contiguous
    converted = _core.material_set(
        ["a", "b"],
        base_colors=noncontiguous,
        metallic=np.array([0, 1], np.float64),
    )
    assert converted.base_colors.dtype == np.float32
    assert converted.base_colors.flags.c_contiguous
    assert converted.metallic.dtype == np.float32
    np.testing.assert_array_equal(converted.base_colors, noncontiguous)
    np.testing.assert_array_equal(converted.metallic, [0, 1])


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"base_colors": np.ones((2, 3), np.float32)}, "base_colors"),
        ({"emissive_colors": np.ones((2, 4), np.float32)}, "emissive"),
        ({"metallic": np.ones(3, np.float32)}, "metallic"),
        ({"roughness": np.ones((2, 1), np.float32)}, "roughness"),
        ({"alpha_modes": ["opaque"]}, "alpha_modes"),
        ({"alpha_modes": ["opaque", "invalid"]}, "alpha mode"),
        ({"alpha_cutoffs": np.ones(3, np.float32)}, "alpha_cutoffs"),
    ],
)
def test_material_domain_shape_and_enum_validation(kwargs, message):
    with pytest.raises((TypeError, ValueError), match=message):
        _core.material_set(["a", "b"], **kwargs)


@pytest.mark.parametrize(
    ("field", "values", "message"),
    [
        ("base_colors", [[-0.1, 0, 0, 1]], "base color"),
        ("base_colors", [[0, 0, 0, 1.1]], "base color"),
        ("emissive_colors", [[0, -0.1, 0]], "emissive"),
        ("metallic", [1.1], "metallic"),
        ("roughness", [-0.1], "roughness"),
        ("alpha_cutoffs", [np.nan], "alpha cutoff"),
    ],
)
def test_factor_ranges_and_nonfinite_values_reject(field, values, message):
    array = np.asarray(values, np.float32)
    with pytest.raises(ValueError, match=message):
        _core.material_set(["a"], **{field: array})


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "texture_semantics": ["base_color"],
                "texture_paths": ["a.png"],
            },
            "texture_materials is required",
        ),
        (
            {
                "texture_materials": np.array([0], np.uint64),
                "texture_semantics": [],
                "texture_paths": ["a.png"],
            },
            "same length",
        ),
        (
            {
                "texture_materials": np.array([0, 0], np.uint64),
                "texture_semantics": ["base_color"],
                "texture_paths": ["a.png"],
            },
            "texture_materials",
        ),
        (
            {
                "texture_materials": np.array([1], np.uint64),
                "texture_semantics": ["base_color"],
                "texture_paths": ["a.png"],
            },
            "out of range",
        ),
        (
            {
                "texture_materials": np.array([0], np.uint64),
                "texture_semantics": ["unknown"],
                "texture_paths": ["a.png"],
            },
            "unsupported texture semantic",
        ),
        (
            {
                "texture_materials": np.array([0, 0], np.uint64),
                "texture_semantics": ["base_color", "base_color"],
                "texture_paths": ["a.png", "b.png"],
            },
            "only once",
        ),
        (
            {
                "texture_materials": np.array([0], np.uint64),
                "texture_semantics": ["base_color"],
                "texture_paths": ["a.png"],
                "texture_wrap_s": ["invalid"],
            },
            "texture wrap",
        ),
        (
            {
                "texture_materials": np.array([0], np.uint64),
                "texture_semantics": ["base_color"],
                "texture_paths": ["a.png"],
                "texture_mag_filters": ["linear_mipmap_linear"],
            },
            "magnification",
        ),
    ],
)
def test_texture_domain_validation(kwargs, message):
    with pytest.raises((TypeError, ValueError), match=message):
        _core.material_set(["a"], **kwargs)


@pytest.mark.parametrize(
    "names",
    [
        ["nul\0name"],
        pytest.param(["x" * (1024 * 1024 + 1)], id="oversized"),
    ],
)
def test_material_name_validation(names):
    with pytest.raises(ValueError, match=r"name|unique|MiB|NUL"):
        _core.material_set(names)


def test_empty_and_duplicate_material_names_are_preserved():
    materials = _core.material_set(["", "same", "same"])

    assert materials.names == ["", "same", "same"]


@pytest.mark.parametrize(
    "path",
    [
        "",
        "nul\0.png",
        pytest.param("x" * (1024 * 1024 + 1), id="oversized"),
    ],
)
def test_texture_path_validation(path):
    with pytest.raises(ValueError, match=r"path|MiB|NUL"):
        _core.material_set(
            ["a"],
            texture_materials=np.array([0], np.uint64),
            texture_semantics=["base_color"],
            texture_paths=[path],
        )


@pytest.mark.parametrize("operation", [copy.copy, copy.deepcopy, pickle.dumps])
def test_copy_and_pickle_policy_is_explicit_rejection(operation):
    with pytest.raises(TypeError):
        operation(_full_materials())
