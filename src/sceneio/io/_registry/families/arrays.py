"""Built-in array, tensor, depth, and flow codec definitions."""

from __future__ import annotations

from sceneio import _core
from sceneio.io._registry.adapters import (
    _array_window_reader,
    _file_sink_writer,
    _mmap_reader,
    _mmap_selector_reader,
    _mmap_view_reader,
)
from sceneio.io._registry.model import Codec


def build_array_codecs(
    _canon,
    _prepare_tensor_dict,
) -> tuple[Codec, ...]:
    """Build the array family with facade-owned preparation callbacks."""

    return (
        Codec(
            "pfm",
            (".pfm",),
            _mmap_reader(_core.read_pfm),
            _file_sink_writer(_core.write_pfm, prepare=_canon),
            record=None,
            datatype="depth_map",
            magic=(b"PF", b"Pf"),
            read_window=_mmap_selector_reader(_core.read_pfm_window),
            supported_features=(
                "grayscale",
                "rgb",
                "float32",
                "little_endian",
                "big_endian",
                "typed_depth_adapter",
            ),
            unsupported_features=("native_positive_stride_mmap_view",),
        ),
        Codec(
            "npy",
            (".npy",),
            _mmap_view_reader(_core.read_npy_view, _core.read_npy),
            _file_sink_writer(_core.write_npy, prepare=_canon),
            record=None,
            datatype="tensor",
            magic=(b"\x93NUMPY",),
            supported_features=("v1", "c_order", "native_endian_mmap_view"),
            unsupported_features=("fortran_order", "object_dtype"),
        ),
        Codec(
            "npz",
            (".npz",),
            _mmap_reader(_core.read_npz),
            _file_sink_writer(_core.write_npz, prepare=_prepare_tensor_dict),
            record=_core.TensorDict,
            datatype="tensor_dict",
            supported_features=("stored", "deflate", "numeric_dtypes"),
            unsupported_features=("object_dtype",),
        ),
        Codec(
            "safetensors",
            (".safetensors",),
            _mmap_view_reader(
                _core.read_safetensors_view,
                _core.read_safetensors,
            ),
            _file_sink_writer(
                _core.write_safetensors,
                prepare=_prepare_tensor_dict,
            ),
            record=_core.TensorDict,
            datatype="tensor_dict",
            read_tensors=_mmap_view_reader(
                _core.read_safetensors_tensors_view,
                _core.read_safetensors_tensors,
            ),
            read_slices=_mmap_view_reader(
                _core.read_safetensors_slices_view,
                _core.read_safetensors_slices,
            ),
            supported_features=(
                "metadata",
                "bool",
                "signed_integers",
                "unsigned_integers",
                "float16",
                "float32",
                "float64",
                "mmap_views",
                "leading_axis_slices",
            ),
            unsupported_features=(
                "bfloat16",
                "float8",
                "complex64",
                "sub_byte_dtypes",
                "strided_tensors",
            ),
        ),
        Codec(
            "flo",
            (".flo",),
            _mmap_view_reader(_core.read_flo_view, _core.read_flo),
            _file_sink_writer(_core.write_flo, prepare=_canon),
            record=None,
            datatype="flow",
            magic=(b"PIEH",),
            read_window=_array_window_reader(
                _mmap_view_reader(_core.read_flo_view, _core.read_flo)
            ),
            supported_features=(
                "float32",
                "native_endian_mmap_view",
                "typed_flow_adapter",
            ),
        ),
        Codec(
            "dmb",
            (".dmb",),
            _mmap_reader(_core.read_dmb),
            _file_sink_writer(_core.write_dmb),
            record=_core.DepthMap,
            datatype="depth_map",
            read_window=_mmap_selector_reader(_core.read_dmb_window),
            supported_features=(
                "scalar_float32",
                "little_endian",
                "zero_invalid",
                "pixel_windows",
            ),
            unsupported_features=(
                "normal_maps",
                "confidence",
                "embedded_scale",
            ),
        ),
    )
