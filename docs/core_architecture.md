# SceneIO core architecture (nanobind)

How the compiled core is organized, and **how to add a codec** — the two
things that keep this expansible as the format list from
`formats_survey.md` grows.

## Layering

```
sceneio (Python)                     public, stable surface
  read() / write() / inspect()       format-dispatched I/O + metadata-only probes
  detect()
  io.registry                        one entry per format (ext · magic · reader · writer · optional inspector)
  Reconstruction, GaussianCloud, …   re-exported record types
  errors                             C++ faults mapped to SceneIO exceptions
        │  (thin wrappers over)
sceneio._core (C++ / nanobind)
  records/     SoA in-memory types + zero-copy views + **convention metadata**
  codecs/      one file per format: read_<fmt>() / write_<fmt>()
  io/          format-agnostic helpers: endian, byte reader/writer, gzip
  module.cpp   registers records first, then codecs
```

**Separation of concerns**
- A **record** (e.g. `Reconstruction`, `GaussianCloud`) is a memory
  representation. It owns contiguous SoA buffers, hands out zero-copy
  ndarray views (numpy default; torch/cupy via DLPack), and **carries its
  conventions as machine-readable metadata** (quaternion order, pose
  direction, scale/opacity space) — never only in comments. A record is
  registered **once** and reused by every codec that produces it (SPZ and
  PLY both yield `GaussianCloud`).
- A **codec** is pure I/O for one format: `read_<fmt>(bytes|path) -> Record`
  and `write_<fmt>(Record) -> bytes|path`. It depends on `records/` and
  `io/`, never on another codec.
- The **Python `io` layer** is the UX + extensibility seam: a registry maps
  a format id to its extensions, magic sniff, reader, writer, optional
  third-party inspector, record type,
  and DataType; `read()`/`write()`/`inspect()`/`detect()` dispatch through it and map
  errors. Adding a format touches the registry in exactly one place.

## Conventions are data, not comments

The survey's #1 bug class is silent convention mismatch. Every record
exposes them:
- `Reconstruction.quaternion_order == "wxyz"`, `.pose_convention == "world_to_camera"`
- `GaussianCloud.quaternion_order == "wxyz"`, `.scale_space == "log"`,
  `.opacity_space == "logit"`, `.sh_layout == "channel_grouped"`

## Adding a codec — the recipe

1. **Record** — if the format needs a new in-memory type, add
   `records/<name>.hpp` (the SoA struct + conventions) and
   `records/<name>.cpp` (`register_<name>()` binding zero-copy views +
   convention properties). Reuse an existing record otherwise.
2. **Codec** — add `codecs/<fmt>.cpp` implementing `read_<fmt>()` /
   `write_<fmt>()` over `records/` + `io/`, plus a `register_<fmt>()` that
   `m.def(...)`s them. Map malformed input to a thrown `std::invalid_argument`.
3. **Wire C++** — add the `register_*` call to `module.cpp` (records before
   codecs) and the source to `CMakeLists.txt`.
4. **Register in Python** — one `Codec(...)` entry in `sceneio/io/registry.py`
   (id, extensions, magic bytes, reader, writer, record, datatype).
5. **Inspect metadata** — add the built-in parser and `inspect_path()` dispatch
   branch, or provide the optional `Codec.inspect` hook for a third-party
   codec. Match the reader's supported header grammar and return an
   `Inspection`.
6. **Parity test** — `tests/codecs/test_<fmt>.py` using
   `sceneio.testing.assert_codec_parity(...)` against the reference oracle
   (pycolmap / gsply / plyfile / imageio / …). Cover: cross-impl equality,
   round-trip identity, a convention pin, and numpy↔torch.

Everything else — dispatch, error mapping, public API wiring, and DataType
binding — is handled by the layer.

## Metadata-only inspection

`sceneio.inspect(path, format=None)` returns a frozen `Inspection`:

- `shape`, `dtype`, and `channels` describe the primary decoded array;
- `count` describes repeated points, Gaussians, views/images, or tensors;
- `arrays` carries per-member shape/dtype for NPZ;
- `metadata` is a read-only mapping for scalar details such as reconstruction
  camera/image/point counts, SH degree, LAS point format, or Netpbm maxval;
- `byte_size` is the encoded file or directory size.

Binary formats stop at their public headers. NPY/NPZ read only array headers,
legacy gzip SPZ inflates only its 16-byte metadata prefix, and COLMAP binary
reads the three leading counts. Headerless text formats stream their records;
XYZ and COLMAP text use GIL-released compiled scans. The JSON scene formats use
bounded nlohmann SAX passes and do not construct a document DOM or record
arrays; individual metadata tokens are capped at 1 MiB and JSON nesting at 256
levels. Bounded text scanners enforce their line/token limit before searching
farther into the mapping, so malformed no-newline inputs do not fault the whole
file into RSS. Inspection reports structural metadata and is not a substitute
for decoding and validating every payload sample.
