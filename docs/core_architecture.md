# SceneIO core architecture (nanobind)

How the compiled core is organized, and **how to add a codec** — the two
things that keep this expansible as the format list from
`formats_survey.md` grows.

## Layering

```
sceneio (Python)                     public, stable surface
  read() / write() / inspect()       format-dispatched I/O + metadata-only probes
  read_partial()                     bounded pixel/point/tensor/COLMAP-image reads
  detect()
  io.registry                        one entry per format + optional inspect/partial hooks
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
  third-party inspector, partial readers, record type, and DataType;
  `read()`/`write()`/`inspect()`/`read_partial()`/`detect()` dispatch through it
  and map errors. Adding a format touches the registry in exactly one place.

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

BAL inspection reads only the three header counts. Full BAL decoding maps
zero-based observations and angle-axis camera blocks into a `Reconstruction`,
using the explicit self-inverse `diag(1,-1,-1)` camera-frame transform and a
Y-coordinate sign flip for centered observations. Its writer accepts only the
lossless canonical subset (one zero-dimension RADIAL camera per image, no
names/colors/errors/principal point or untracked observations) and refuses
unsupported record fields. The unambiguous `.bal` suffix is auto-detected;
official datasets using the generic `.txt` suffix require `format="bal"`.

## Partial reads

`sceneio.read_partial(path, ...)` requires exactly one selector and returns the
same public record kind as `read()`:

- `window=(row_start, row_stop, column_start, column_stop)` uses half-open bounds
  for PFM, binary P5/P6 Netpbm, lossless VP8L WebP, FLO, and scalar DMB;
- `points=(start, stop)` selects a half-open range from XYZ, count-prefixed PTS,
  LAS, binary Gaussian PLY, and `.splat`;
- `tensors=("name", ...)` selects named tensors from safetensors without
  materializing unrelated payload tensors;
- `slices={"name": (start, stop), ...}` selects half-open leading-axis ranges
  from named safetensors tensors;
- `image_id=<persisted COLMAP id>` returns a one-image `Reconstruction` with its
  referenced camera from binary or text COLMAP. It deliberately leaves the
  point arrays empty and does not open `points3D.bin` / `points3D.txt`.

PFM, binary Netpbm, and DMB copy only selected rows, lossless WebP uses
libwebp's cropped decoder, and FLO returns a read-only derived view whose owner
retains the mmap. ASCII P2/P3 reject because they require complete-payload token
decoding; lossy VP8 rejects because crop-local chroma upsampling is not
guaranteed to match a full-decode slice. Fixed-record
cloud formats index their selected records; XYZ and PTS scan text for row
boundaries but allocate and parse numeric values only for the requested range.
PTS additionally validates its mandatory declared point count.
Safetensors selection returns read-only mmap-backed tensor views where host
byte order and payload alignment permit; each view retains its mapping owner
after the file handle leaves scope.
Unsupported codecs raise `FormatError` rather than disguising a full decode as
a partial read. COLMAP text caps non-name tokens at 1 MiB consistently in its
full and partial readers; image names retain their unbounded format behavior.
