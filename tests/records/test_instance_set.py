from __future__ import annotations

import copy
import gc
import pickle
import tracemalloc

import numpy as np
import pytest

from sceneio import _core


def _instances(**changes):
    values = {
        "prototype_nodes": np.array([3, 7], np.uint64),
        "prototype_indices": np.array([0, 1, 0], np.uint64),
        "translations": np.arange(9, dtype=np.float32).reshape(3, 3),
        "orientations": np.array(
            [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]],
            np.float32,
        ),
        "scales": np.array(
            [[1, 1, 1], [2, 1, -1], [0.5, 0.5, 0.5]],
            np.float32,
        ),
        "ids": np.array([10, 20, 30], np.int64),
        "invisible_ids": np.array([20], np.int64),
        "attributes": _core.tensor_dict(
            {"temperature": np.array([1.5, 2.5, 3.5], np.float32)}
        ),
    }
    values.update(changes)
    return _core.instance_set(**values)


def test_instance_set_surface_and_owner_retaining_views():
    instances = _instances()

    assert repr(instances) == "<InstanceSet instances=3 prototypes=2>"
    assert instances.num_instances == 3
    assert instances.num_prototypes == 2
    assert instances.quaternion_order == "wxyz"
    assert instances.has_attributes
    np.testing.assert_array_equal(instances.prototype_nodes, [3, 7])
    np.testing.assert_array_equal(instances.prototype_indices, [0, 1, 0])
    np.testing.assert_array_equal(instances.ids, [10, 20, 30])
    np.testing.assert_array_equal(instances.invisible_ids, [20])
    np.testing.assert_array_equal(instances.invisible_mask, [0, 1, 0])
    np.testing.assert_array_equal(
        instances.attributes["temperature"], [1.5, 2.5, 3.5]
    )

    translations = instances.translations
    mask = instances.invisible_mask
    attributes = instances.attributes
    temperature = attributes["temperature"]
    del instances
    gc.collect()

    np.testing.assert_array_equal(translations[:, 0], [0, 3, 6])
    np.testing.assert_array_equal(mask, [0, 1, 0])
    np.testing.assert_array_equal(temperature, [1.5, 2.5, 3.5])
    assert not translations.flags.writeable
    assert not mask.flags.writeable


def test_instance_set_defaults_and_factory_copy_inputs():
    prototype_indices = np.array([0, 0], np.uint64)
    translations = np.zeros((2, 3), np.float32)
    instances = _core.instance_set(
        np.array([4], np.uint64),
        prototype_indices,
        translations,
        quaternion_order="xyzw",
    )
    prototype_indices[:] = 99
    translations[:] = 99

    np.testing.assert_array_equal(instances.prototype_indices, [0, 0])
    np.testing.assert_array_equal(instances.ids, [0, 1])
    np.testing.assert_array_equal(
        instances.orientations,
        [[0, 0, 0, 1], [0, 0, 0, 1]],
    )
    np.testing.assert_array_equal(instances.scales, np.ones((2, 3)))
    assert not instances.has_attributes
    assert len(instances.attributes) == 0

    count = 100_000
    large = _core.instance_set(
        np.array([0], np.uint64),
        np.zeros(count, np.uint64),
        np.zeros((count, 3), np.float32),
    )
    tracemalloc.start()
    first = large.translations
    second = large.translations
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert np.shares_memory(first, second)
    assert peak < 256 * 1024


@pytest.mark.parametrize("operation", [copy.copy, copy.deepcopy, pickle.dumps])
def test_instance_set_copy_and_pickle_policy_is_explicit_rejection(operation):
    with pytest.raises(TypeError):
        operation(_instances())


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"prototype_indices": np.array([0, 2, 0], np.uint64)},
            "prototype index",
        ),
        (
            {"prototype_nodes": np.array([3, 3], np.uint64)},
            "prototype node",
        ),
        ({"ids": np.array([1, 1, 2], np.int64)}, "ids must be unique"),
        (
            {"invisible_ids": np.array([99], np.int64)},
            "subset of ids",
        ),
        (
            {"invisible_ids": np.array([20, 20], np.int64)},
            "invisible ids must be unique",
        ),
        (
            {
                "orientations": np.zeros((3, 4), np.float32),
            },
            "quaternions must be nonzero",
        ),
        (
            {
                "attributes": lambda: _core.tensor_dict(
                    {"bad": np.ones((2, 1), np.float32)}
                ),
            },
            "N leading rows",
        ),
        ({"quaternion_order": "real_first"}, "quaternion_order"),
    ],
)
def test_instance_set_validation(changes, message):
    changes = dict(changes)
    if callable(changes.get("attributes")):
        changes["attributes"] = changes["attributes"]()
    with pytest.raises(ValueError, match=message):
        _instances(**changes)


def test_instance_set_shape_guards_run_before_shape_access():
    with pytest.raises(ValueError, match=r"translations.*\(N,3\)"):
        _core.instance_set(
            np.array([0], np.uint64),
            np.array([0], np.uint64),
            np.array(0, np.float32),
        )
    with pytest.raises(ValueError, match="prototype_nodes"):
        _core.instance_set(
            np.array(0, np.uint64),
            np.array([], np.uint64),
            np.empty((0, 3), np.float32),
        )
    with pytest.raises(ValueError, match="attribute names"):
        _core.instance_set(
            np.array([0], np.uint64),
            np.array([0], np.uint64),
            np.zeros((1, 3), np.float32),
            attributes=_core.tensor_dict(
                {"bad\0name": np.ones(1, np.float32)}
            ),
        )
