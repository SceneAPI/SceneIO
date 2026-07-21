# SceneIO core architecture (nanobind)

How the compiled core is organized, and **how to add a codec** — the two
things that keep this expansible as the format list from
`formats_survey.md` grows.

## Layering

```
sceneio (Python)                     public, stable surface
  read() / write() / detect()        format-dispatched I/O
  io.registry                        one entry per format (ext · magic · reader · writer · record · datatype)
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
  a format id to its extensions, magic sniff, reader, writer, record type,
  and DataType; `read()`/`write()`/`detect()` dispatch through it and map
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
5. **Parity test** — `tests/codecs/test_<fmt>.py` using
   `sceneio.testing.assert_codec_parity(...)` against the reference oracle
   (pycolmap / gsply / plyfile / imageio / …). Cover: cross-impl equality,
   round-trip identity, a convention pin, and numpy↔torch.

Everything else — dispatch, error mapping, `read()`/`write()`,
DataType binding — is handled by the layer and needs no per-codec code.
