"""Codec registry — the single place a format is wired into ``sceneio.io``.

Each :class:`Codec` binds a format id to its file extensions, a magic-byte
sniff, a reader, an optional writer, the record type it yields, and the
DataType it serializes. ``read()`` / ``write()`` / ``detect()`` dispatch
through this registry, so **adding a format is one** :func:`register` call
(plus the compiled codec). See ``docs/core_architecture.md``.
"""

from __future__ import annotations

import mmap
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sceneio import _core
from sceneio.errors import SceneIoError


class FormatError(SceneIoError):
    """A file could not be detected, read, or written in its format."""


@dataclass(frozen=True)
class Codec:
    """One format's binding into the I/O layer."""

    id: str
    extensions: tuple[str, ...]
    read: Callable[[str], object]  # (path) -> record
    write: Callable[[object, str], None] | None  # (record, path) -> None
    record: type | None  # record type produced, for write dispatch
    datatype: str  # the DataType id this format serializes
    magic: tuple[bytes, ...] = ()  # leading-byte signatures (single-file formats)
    filenames: tuple[
        str, ...
    ] = ()  # exact filenames that identify the format (e.g. transforms.json)
    is_directory: bool = False  # reads/writes a directory (e.g. COLMAP)
    dir_marker: str = "cameras.bin"  # the file whose presence identifies a directory format
    inspect: Callable[[str], object] | None = None  # optional metadata-only extension hook
    read_window: Callable[[str, int, int, int, int], object] | None = None
    read_points: Callable[[str, int, int], object] | None = None
    read_image: Callable[[str, int], object] | None = None
    streams_read: bool = True
    streams_write: bool = True
    lossy: bool = False
    requires_features: tuple[str, ...] = ()
    supported_features: tuple[str, ...] = ()
    unsupported_features: tuple[str, ...] = ()
    container_kind: str | None = None

    def __post_init__(self) -> None:
        kind = self.container_kind or ("directory" if self.is_directory else "file")
        if kind not in {"file", "directory", "multi_file"}:
            raise ValueError(
                "container_kind must be 'file', 'directory', or 'multi_file'"
            )
        if self.is_directory != (kind == "directory"):
            raise ValueError("is_directory and container_kind disagree")
        object.__setattr__(self, "container_kind", kind)
        for field_name in (
            "extensions",
            "magic",
            "filenames",
            "requires_features",
            "supported_features",
            "unsupported_features",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        for field_name in (
            "requires_features",
            "supported_features",
            "unsupported_features",
        ):
            values = getattr(self, field_name)
            if any(not isinstance(value, str) or not value for value in values):
                raise ValueError(f"{field_name} entries must be non-empty strings")
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} entries must be unique")
        overlap = set(self.supported_features) & set(self.unsupported_features)
        if overlap:
            raise ValueError(
                "supported_features and unsupported_features overlap: "
                + ", ".join(sorted(overlap))
            )

    def capabilities(self) -> CodecCapabilities:
        """Return the immutable public capability snapshot for this codec."""

        selectors = []
        if self.read_window is not None:
            selectors.append("window")
        if self.read_points is not None:
            selectors.append("points")
        if self.read_image is not None:
            selectors.append("image_id")
        return CodecCapabilities(
            format=self.id,
            datatype=self.datatype,
            record_type=self.record.__name__ if self.record is not None else None,
            extensions=self.extensions,
            filenames=self.filenames,
            container_kind=self.container_kind,
            available=True,
            can_read=True,
            can_write=self.write is not None,
            can_inspect=True,
            partial_selectors=tuple(selectors),
            streams_read=self.streams_read,
            streams_write=self.write is not None and self.streams_write,
            lossy=self.lossy,
            requires_features=self.requires_features,
            supported_features=self.supported_features,
            unsupported_features=self.unsupported_features,
        )


@dataclass(frozen=True)
class CodecCapabilities:
    """Stable, immutable discovery metadata for one registered format.

    ``streams_read`` means the public path avoids a whole-file Python
    ``bytes`` allocation through mmap or native directory I/O. ``streams_write``
    means it uses a direct native file sink instead of an output-sized Python
    ``bytes`` object. These flags do not claim that a compression library itself
    is incremental.
    """

    format: str
    datatype: str
    record_type: str | None
    extensions: tuple[str, ...]
    filenames: tuple[str, ...]
    container_kind: str
    available: bool
    can_read: bool
    can_write: bool
    can_inspect: bool
    partial_selectors: tuple[str, ...]
    streams_read: bool
    streams_write: bool
    lossy: bool
    requires_features: tuple[str, ...]
    supported_features: tuple[str, ...]
    unsupported_features: tuple[str, ...]


@dataclass(frozen=True)
class NativeFeatureCapabilities:
    """Build-time state for one optional native integration.

    ``available`` is derived from the feature names exported by the compiled
    extension. Keeping unavailable integrations in this manifest lets callers
    distinguish a known build option from an unknown feature name without
    importing an optional Python package.
    """

    name: str
    build_option: str
    available: bool
    formats: tuple[str, ...]


_NATIVE_FEATURE_FORMATS = {
    "arrow": ("parquet",),
    "avif": ("avif",),
    "draco": ("gltf", "glb"),
    "e57": ("e57",),
    "hdf5": ("hdf5", "hloc_features", "hloc_matches"),
    "jxl": ("jpeg_xl",),
    "openvdb": ("openvdb",),
    "tiff": ("tiff",),
    "usd": ("usd", "usdz"),
}


def native_feature_capabilities(
    name: str | None = None,
) -> NativeFeatureCapabilities | dict[str, NativeFeatureCapabilities]:
    """Return immutable compiled-state metadata for optional native features."""

    compiled = frozenset(getattr(_core, "__native_features__", ()))
    unknown_compiled = compiled - _NATIVE_FEATURE_FORMATS.keys()
    if unknown_compiled:
        raise RuntimeError(
            "compiled extension reports unknown native features: "
            + ", ".join(sorted(unknown_compiled))
        )

    def snapshot(feature_name: str) -> NativeFeatureCapabilities:
        try:
            formats = _NATIVE_FEATURE_FORMATS[feature_name]
        except KeyError:
            raise FormatError(f"unknown native feature {feature_name!r}") from None
        return NativeFeatureCapabilities(
            name=feature_name,
            build_option=f"SCENEIO_WITH_{feature_name.upper()}",
            available=feature_name in compiled,
            formats=formats,
        )

    if name is not None:
        return snapshot(name)
    return {
        feature_name: snapshot(feature_name)
        for feature_name in sorted(_NATIVE_FEATURE_FORMATS)
    }


REGISTRY: dict[str, Codec] = {}


def register(codec: Codec) -> Codec:
    if codec.id in REGISTRY:
        raise ValueError(f"codec id already registered: {codec.id!r}")
    REGISTRY[codec.id] = codec
    return codec


def get(format_id: str) -> Codec:
    try:
        return REGISTRY[format_id]
    except KeyError:
        raise FormatError(f"unknown format id {format_id!r}") from None


def detect(path) -> str:
    """Return the format id for ``path`` (directory check, then extension,
    then a magic-byte sniff for extensionless files)."""
    p = Path(path)
    if p.is_dir():
        for c in REGISTRY.values():
            if c.is_directory and (p / c.dir_marker).exists():
                return c.id
        raise FormatError(f"no directory format matches {str(path)!r}")
    for c in REGISTRY.values():
        if p.name in c.filenames:
            return c.id
    ext = p.suffix.lower()
    for c in REGISTRY.values():
        if ext in c.extensions:
            return c.id
    try:
        with p.open("rb") as stream:
            head = stream.read(16)
    except OSError:
        head = b""
    for c in REGISTRY.values():
        if any(head.startswith(m) for m in c.magic):
            return c.id
    raise FormatError(f"cannot detect a format for {str(path)!r} (ext {ext!r})")


# --- adapters: give every _core function a uniform (path) signature -------
def _bytes_reader(fn: Callable[[bytes], object]) -> Callable[[str], object]:
    def read(path: str):
        return fn(Path(path).read_bytes())

    return read


def _mmap_reader(fn: Callable[[object], object]) -> Callable[[str], object]:
    """Decode a file through a read-only mmap without materializing its bytes.

    Empty files cannot be mapped portably (notably on Windows), and a few
    filesystems do not support mmap. Those cases read from the same already-open
    stream as a compatibility fallback, preserving file identity across rename
    races. The current O1 decoders copy their payload into record-owned storage
    before returning, so the mapping can close here. Callers must not truncate a
    file or aliased backing storage during a read: changing bytes races the
    GIL-released decoder, and POSIX delivers SIGBUS for a shrunken live map.
    """

    def read(path: str):
        p = Path(path)
        with p.open("rb") as stream:
            try:
                mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
            except (OSError, ValueError):
                stream.seek(0)
                return fn(stream.read())
            with mapped:
                return fn(mapped)

    return read


def _mmap_selector_reader(fn: Callable[..., object]) -> Callable[..., object]:
    """Call a compiled partial decoder over a temporary read-only mapping."""

    def read(path: str, *selector):
        p = Path(path)
        with p.open("rb") as stream:
            try:
                mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
            except (OSError, ValueError):
                stream.seek(0)
                return fn(stream.read(), *selector)
            with mapped:
                return fn(mapped, *selector)

    return read


def _mmap_view_reader(
    view_fn: Callable[[object], object],
    fallback_fn: Callable[[object], object],
) -> Callable[[str], object]:
    """Return a raw ndarray view whose owner keeps the mmap export alive.

    The compiled view reader pins the mmap's buffer export into the returned
    ndarray, so this adapter deliberately does not close a successful mapping.
    It is released automatically when the last array view is collected. Empty
    files and filesystems without mmap support use the established copy reader.
    The mapped file must not be modified or truncated for the lifetime of the
    returned array and all derived views; atomic replacement of the path is safe.
    A private copy-on-write mapping is presented to C++ through a read-only
    memoryview so consumers that disregard NumPy's flag still cannot alter disk.
    """

    def read(path: str):
        p = Path(path)
        with p.open("rb") as stream:
            try:
                # ACCESS_COPY is demand-paged like ACCESS_READ but supplies a
                # private writable backing as a last-resort safeguard for
                # consumers (notably torch.from_numpy) that ignore NumPy's
                # WRITEABLE=False flag. Present only a read-only memoryview to
                # the compiled parser; writes never reach the source file.
                mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_COPY)
            except (OSError, ValueError):
                stream.seek(0)
                return fallback_fn(stream.read())
            readonly = None
            try:
                readonly = memoryview(mapped).toreadonly()
                return view_fn(readonly)
            except BaseException:
                # Do not let the chained FormatError traceback retain a live
                # mapping (and Windows file lock) after a failed decode.
                if readonly is not None:
                    readonly.release()
                mapped.close()
                raise

    return read


def _array_window_reader(reader: Callable[[str], object]) -> Callable[..., object]:
    """Slice a mapped raw raster while retaining its ndarray mapping owner."""

    def read(path: str, row_start: int, row_stop: int, col_start: int, col_stop: int):
        value = reader(path)
        if value.ndim < 2:
            raise ValueError("pixel-window reads require an array with at least two axes")
        height, width = value.shape[:2]
        if (
            row_start < 0
            or row_start >= row_stop
            or row_stop > height
            or col_start < 0
            or col_start >= col_stop
            or col_stop > width
        ):
            message = (
                f"window {(row_start, row_stop, col_start, col_stop)!r} "
                f"is outside raster shape {(height, width)!r}"
            )
            # The mapped ndarray owns the mmap. Remove this reference before
            # raising so a retained traceback cannot pin its Windows file lock.
            del value
            raise ValueError(message)
        return value[row_start:row_stop, col_start:col_stop, ...]

    return read


def _file_sink_writer(
    fn: Callable[[object], bytes],
    prepare: Callable[[object], object] | None = None,
) -> Callable[[object, str], None]:
    def write(obj, path: str):
        # Preparation must finish before the C++ sink becomes active: NumPy,
        # DLPack, and mapping protocols are arbitrary Python callbacks and may
        # re-enter an encoder.  Only direct compiled encoders receive the
        # prepared value inside _write_to_file.
        if prepare is not None:
            obj = prepare(obj)
        _core._write_to_file(fn, obj, path)

    return write


# --- npy/npz adapters: the compiled writers require C-contiguous, native-endian
# input, and .npz accepts either a TensorDict or a plain {name: array} dict.
def _canon(a):
    a = np.ascontiguousarray(a)
    if a.dtype.byteorder == ">":
        a = a.astype(a.dtype.newbyteorder("="))
    return a


def _prepare_npz(obj):
    if isinstance(obj, _core.TensorDict):
        return obj
    return _core.tensor_dict({k: _canon(v) for k, v in dict(obj).items()})


# --- built-in codecs (the compiled `_core` functions, uniformly wrapped) ---
register(
    Codec(
        "pfm",
        (".pfm",),
        _mmap_reader(_core.read_pfm),
        _file_sink_writer(_core.write_pfm, prepare=_canon),
        record=None,
        datatype="depth_map",
        magic=(b"PF", b"Pf"),
        read_window=_mmap_selector_reader(_core.read_pfm_window),
        supported_features=("grayscale", "rgb", "float32", "little_endian", "big_endian"),
        unsupported_features=("native_positive_stride_mmap_view",),
    )
)
register(
    Codec(
        "colmap_sparse",
        (),
        _core.read_colmap_sparse,
        _core.write_colmap_sparse,
        record=_core.Reconstruction,
        datatype="sparse_model",
        is_directory=True,
        read_image=_core.read_colmap_sparse_image,
        supported_features=("cameras", "images", "points3D", "tracks"),
    )
)
register(
    Codec(
        "gaussian_ply",
        (".ply",),
        _mmap_reader(_core.read_gaussian_ply),
        _file_sink_writer(_core.write_gaussian_ply),
        record=_core.GaussianCloud,
        datatype="splat",
        magic=(b"ply",),
        read_points=_mmap_selector_reader(_core.read_gaussian_ply_points),
    )
)
register(
    Codec(
        "spz",
        (".spz",),
        _mmap_reader(_core.read_spz),
        _file_sink_writer(_core.write_spz),
        record=_core.GaussianCloud,
        datatype="splat",
        magic=(b"\x1f\x8b", b"NGSP"),
        lossy=True,
        supported_features=("v1_read", "v2_read", "v3_read_write", "v4_read_write"),
    )
)
# Camera-pose formats -> PosedViewSet. `datatype` here is informational; a
# vocabulary id is pending, like `splat` (see formats/datatypes.py). TUM/KITTI
# claim no extension (`.txt` is ambiguous) so they are explicit-`format=` only.
register(
    Codec(
        "transforms_json",
        (),
        _mmap_reader(_core.read_transforms_json),
        _file_sink_writer(_core.write_transforms_json),
        record=_core.PosedViewSet,
        datatype="posed_views",
        filenames=("transforms.json",),
    )
)
register(
    Codec(
        "tum",
        (),
        _mmap_reader(_core.read_tum),
        _file_sink_writer(_core.write_tum),
        record=_core.PosedViewSet,
        datatype="posed_views",
    )
)
register(
    Codec(
        "kitti",
        (),
        _mmap_reader(_core.read_kitti),
        _file_sink_writer(_core.write_kitti),
        record=_core.PosedViewSet,
        datatype="posed_views",
    )
)
# Array / tensor + raster-image formats (Tier-1, zero-dep). datatype ids are
# informational (vocabulary registration is Phase-C, like posed_views).
register(
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
    )
)
register(
    Codec(
        "npz",
        (".npz",),
        _mmap_reader(_core.read_npz),
        _file_sink_writer(_core.write_npz, prepare=_prepare_npz),
        record=_core.TensorDict,
        datatype="tensor_dict",
        supported_features=("stored", "deflate", "numeric_dtypes"),
        unsupported_features=("object_dtype",),
    )
)
register(
    Codec(
        "netpbm",
        (".ppm", ".pgm", ".pnm"),
        _mmap_reader(_core.read_netpbm),
        _file_sink_writer(_core.write_netpbm),
        record=_core.Image,
        datatype="image",
        magic=(b"P2", b"P3", b"P5", b"P6"),
        read_window=_mmap_selector_reader(_core.read_netpbm_window),
        supported_features=("p2", "p3", "p5", "p6", "uint8", "uint16"),
        unsupported_features=("ascii_window",),
    )
)
# PNG via vendored lodepng -> Image. gray/RGB/RGBA at 8/16-bit + palette; the
# 8-byte signature is unambiguous. 16-bit PNG is the depth-map workhorse.
register(
    Codec(
        "png",
        (".png",),
        _mmap_reader(_core.read_png),
        _file_sink_writer(_core.write_png),
        record=_core.Image,
        datatype="image",
        magic=(b"\x89PNG\r\n\x1a\n",),
        supported_features=("grayscale", "rgb", "rgba", "palette", "uint8", "uint16"),
    )
)
# JPEG (vendored stb) -> Image. Lossy 8-bit gray/RGB; the SOI+marker prefix is
# the standard signature. write uses the default quality (95); io.save can't pass
# a quality knob yet, so callers wanting other qualities use _core.write_jpeg.
register(
    Codec(
        "jpeg",
        (".jpg", ".jpeg"),
        _mmap_reader(_core.read_jpeg),
        _file_sink_writer(_core.write_jpeg),
        record=_core.Image,
        datatype="image",
        magic=(b"\xff\xd8\xff",),
        lossy=True,
        supported_features=("baseline", "progressive", "grayscale_read", "rgb"),
        unsupported_features=("cmyk_write", "rgba_write"),
    )
)
# Radiance RGBE (vendored stb) -> Image (float32 linear RGB). The HDR float twin
# of the integer image codecs; both ASCII signature variants.
register(
    Codec(
        "hdr",
        (".hdr",),
        _mmap_reader(_core.read_hdr),
        _file_sink_writer(_core.write_hdr),
        record=_core.Image,
        datatype="image",
        magic=(b"#?RADIANCE", b"#?RGBE"),
        lossy=True,
        supported_features=("rgbe", "rle", "float32_rgb"),
    )
)
# OpenEXR (vendored tinyexr, reuses our miniz) -> Image (float32 linear). The
# 4-byte magic 0x76 0x2f 0x31 0x01 is the EXR signature.
register(
    Codec(
        "exr",
        (".exr",),
        _mmap_reader(_core.read_exr),
        _file_sink_writer(_core.write_exr),
        record=_core.Image,
        datatype="image",
        magic=(b"\x76\x2f\x31\x01",),
    )
)
# WebP (libwebp) -> Image (uint8 sRGB). Ext-only: the WEBP tag sits at byte 8 of
# the RIFF container, which detect()'s startswith sniff can't match without a bare
# b"RIFF" that would also claim .wav/.avi.
register(
    Codec(
        "webp",
        (".webp",),
        _mmap_reader(_core.read_webp),
        _file_sink_writer(_core.write_webp),
        record=_core.Image,
        datatype="image",
        read_window=_mmap_selector_reader(_core.read_webp_window),
        lossy=True,
        supported_features=("lossless", "lossy", "rgb", "rgba"),
        unsupported_features=("animation", "lossy_window"),
    )
)
# COLMAP text sparse (cameras.txt/images.txt/points3D.txt) — the text twin of
# colmap_sparse; a directory format distinguished by its cameras.txt marker.
register(
    Codec(
        "colmap_sparse_txt",
        (),
        _core.read_colmap_txt,
        _core.write_colmap_txt,
        record=_core.Reconstruction,
        datatype="sparse_model",
        is_directory=True,
        dir_marker="cameras.txt",
        read_image=_core.read_colmap_txt_image,
        supported_features=("cameras", "images", "points3D", "tracks"),
    )
)
register(
    Codec(
        "xyz",
        (".xyz",),
        _mmap_reader(_core.read_xyz),
        _file_sink_writer(_core.write_xyz),
        record=_core.PointCloud,
        datatype="point_cloud",
        read_points=_mmap_selector_reader(_core.read_xyz_points),
    )
)
# ASPRS LAS (hand-parsed binary, no library) -> PointCloud. The "LASF" signature
# is unambiguous; LAZ (compressed) is deferred (needs laz-perf).
register(
    Codec(
        "las",
        (".las",),
        _mmap_reader(_core.read_las),
        _file_sink_writer(_core.write_las),
        record=_core.PointCloud,
        datatype="point_cloud",
        magic=(b"LASF",),
        read_points=_mmap_selector_reader(_core.read_las_points),
        lossy=True,
        supported_features=("point_formats_0_3", "point_formats_6_8", "rgb16", "georef"),
        unsupported_features=("point_formats_4_5", "point_formats_9_10", "laz"),
    )
)
register(
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
        supported_features=("float32", "native_endian_mmap_view"),
    )
)
# SfM pose formats -> Reconstruction (convention-converted to WXYZ/world_to_camera).
register(
    Codec(
        "bundler",
        (".out",),
        _mmap_reader(_core.read_bundler),
        _file_sink_writer(_core.write_bundler),
        record=_core.Reconstruction,
        datatype="sparse_model",
        magic=(b"# Bundle file",),
    )
)
register(
    Codec(
        "nvm",
        (".nvm",),
        _mmap_reader(_core.read_nvm),
        _file_sink_writer(_core.write_nvm),
        record=_core.Reconstruction,
        datatype="sparse_model",
        magic=(b"NVM_V3",),
    )
)
register(
    Codec(
        "openmvg",
        (),
        _mmap_reader(_core.read_openmvg),
        _file_sink_writer(_core.write_openmvg),
        record=_core.Reconstruction,
        datatype="sparse_model",
        filenames=("sfm_data.json",),
    )
)
# antimatter15 .splat -> GaussianCloud. Headerless (no magic), so ext-only; a
# down-converted, web-viewer sibling of spz (both carry the `splat` datatype).
register(
    Codec(
        "splat",
        (".splat",),
        _mmap_reader(_core.read_splat),
        _file_sink_writer(_core.write_splat),
        record=_core.GaussianCloud,
        datatype="splat",
        read_points=_mmap_selector_reader(_core.read_splat_points),
        lossy=True,
        supported_features=("rgb8", "opacity8", "scale8", "quaternion8"),
        unsupported_features=("spherical_harmonics",),
    )
)
