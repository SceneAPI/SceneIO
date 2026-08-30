# COLMAP workflow adapters

`sceneio.colmap` owns portable COLMAP ecosystem data that is not a standalone
entry in the 74-format registry. These adapters are implemented in this
repository, require only NumPy at runtime, and never open an encoded image or
video referenced by a path.

## Public surface

| Data | Records | Read / inspect / write |
|---|---|---|
| Extended sparse directory | `ExtendedSparseModel`, `SparseExtensions`, marker, time, and ChArUco records | `read_extended_sparse_model`, `read_sparse_extensions`, `write_extended_sparse_model` |
| MappingInput v1/v2 | `MappingInput`, `MappingCamera`, `MappingImage`, `MappingMatch` | `read_mapping_input`, `inspect_mapping_input`, `write_mapping_input` |
| MegaLoc artifact directory | `MegaLocArtifacts`, `MegaLocImage`, `MegaLocPair` | `read_megaloc_artifacts`, `inspect_megaloc_artifacts`, `write_megaloc_artifacts` |
| Rig configuration JSON | `RigConfiguration`, `RigConfigCamera` | `read_rig_config`, `write_rig_config` |
| SIFT text | `SiftFeatures` | `read_sift_features`, `write_sift_features` |
| Image pairs and dense cap rows | `(image_name1, image_name2)` tuples and optional `uint32` caps | `read_image_pairs`, `read_stock_image_pairs`, `write_image_pairs` |
| Feature-match text | `NamedMatches` | `read_feature_matches`, `write_feature_matches` |
| Sim3 text | `SimilarityTransform` | `read_similarity_transform`, `write_similarity_transform` |

The standard `sceneio.read(..., format="colmap_sparse")` and
`colmap_sparse_txt` paths still refuse fork extension sidecars. Use
`read_extended_sparse_model` when the caller explicitly wants all 14 possible
binary/text companion filenames. This keeps the normal registry route from
silently ignoring fields.

All camera-bearing adapters share the package-owned ids 0 through 17 in
`src/sceneio/_camera_models.py`; none owns a local parameter-count table.
`sceneio.data.CameraModel` exposes the same names, ids, and ordered parameter
layouts, while CMake generates the compiled core lookup from that manifest.
Use the camera and feature/match bridges in
[`canonicalization.md`](canonicalization.md) when a loaded COLMAP record must
enter the neutral procedure layer.

## Wire and lifetime behavior

- MappingInput is defined as little-endian `PCMAPIN\0` version 1 or 2. Version
  1 maps the missing image `time_id` to the declared invalid `uint32`
  sentinel; version 2 preserves it. Keypoints, match indices, and optional
  relative poses are read-only views over a mapped file and remain usable
  while their record or derived NumPy view is alive. Camera and image IDs are
  positive. Match `config` is the reference two-view enum `0..9`;
  `relative_pose` is on-wire `qx,qy,qz,qw,tx,ty,tz` (XYZW quaternion),
  representing `cam2_from_cam1`.
- MegaLoc version 1 validates its schema, image table, descriptor
  dtype/layout/extent, pair count, exact score columns, pair-list/TSV
  agreement, distinct contained artifact paths, and unknown fields.
  Descriptor arrays are read-only little-endian `float32` mappings; scores
  use canonical finite `float32` or NaN. Model/engine paths and strictly
  JSON-valued metadata are inert values.
- Large fixed sparse ID/tag sidecars are mapped and copied only into their
  two owned result arrays. Variable records are parsed from a read-only
  mapping. Text tag parsing uses two bounded passes instead of Python tuple
  accumulation.
- MappingInput, MegaLoc, sparse companions, SIFT, pair, match, rig, and Sim3
  writers use atomic replacement. Numeric and pair payloads stream to their
  sink instead of assembling an output-sized Python `bytes` or string.
- NumPy wire dtypes and shapes are exact. Writers reject unsupported camera
  models, parameter counts, conventions, references, non-unit quaternions,
  duplicate identifiers/pairs, and unrepresentable values rather than
  converting them.

The SIFT reference importer accepts descriptor floats and explicitly
truncates values in `[0, 255]` to `uint8`. SceneIO performs that same named
conversion on read; its canonical writer emits integral descriptor tokens.
The stock pair parser’s single-ASCII-space grammar is available separately
from the general-whitespace dense pair/cap parser. Dense caps are positive
and limited to the reference signed-32-bit domain.

## Closure boundary

Portable reconstruction, feature, rig, MappingInput, and MegaLoc artifact
data is in scope. The following remain deliberately separate:

- encoded video/container implementations;
- hardware inference engines and retrieval-index binaries;
- solver reports, traces, staged/decoded caches, and application option
  documents;
- VRML visualization output;
- lossy CAM and Recon3D export helpers;
- TIFF pixel decoding plus embedded or standalone `.xmp` metadata, which
  remain an optional generic image-format wave and are not required to
  preserve COLMAP image references.

Encoded image paths, image roots, and model paths are carried as opaque text.
No adapter in this module decodes them or adds a media dependency.
