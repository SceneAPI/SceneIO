# Changelog

All notable changes to SceneIO are recorded here. Release-specific detail is
kept in [`docs/releases/`](docs/releases/).

## Unreleased

- Made `payload_kind` the single codec and inspection payload field; removed
  the duplicate `datatype` alias and compatibility-only module/pickle
  identities. Public records now retain their real, importable definition
  modules instead of synthetic `sceneio.io` identities.
- Consolidated Middlebury FLO I/O onto `FlowField` for full and bounded reads,
  writes, and inspection; removed the parallel raw ndarray and specialized
  flow-wrapper APIs.
- Consolidated generic E57 I/O onto `ScanSet` and generic TIFF I/O onto
  `RasterCollection`; retained only the format-specific bounded selectors
  `read_e57_scan` and `read_tiff_collection`.
- Removed redundant `PointScan` aliases and presence flags, the ambiguous
  `SceneGraph.mesh_at` primitive accessor, and native-record compatibility
  fallbacks. `point_cloud`, `num_stored_points`,
  `has_row_column_indices`, and `mesh_primitive_at` are the sole forms.
- Made inspector and registry family modules the direct owners of dispatch
  functions and registry value types instead of re-exporting compatibility
  wrappers through their parent modules.
- Removed the unused private blob-hash validation alias and refreshed the
  public contracts, documentation, benchmarks, and native inventories.

## [0.4.0] - 2026-08-30

- Consolidated all 90 public data representations onto one canonical type per
  concept, with root-level public identities and no legacy alias or adapter
  layer.
- Unified camera intrinsics, features, correspondence graphs, depth maps,
  posed views, tracked point clouds, and static mesh scenes without reducing
  the format-I/O capability inventory.
- Made `SceneGraph` the glTF, GLB, USD, and USDZ scene representation;
  `PointCloud` now carries optional track CSR data; and `CorrespondenceGraph`
  now carries both raw and verified pair channels.
- Removed the public `sceneio.data` and `sceneio.canonical` namespaces and the
  duplicate `sceneio.io.<Type>` aliases. This is an intentional pre-1 contract
  reset; no legacy compatibility layer is shipped.
- Added immutable, machine-readable contracts for all 131 public class
  identities and the 26 built-in codec payload kinds, with deterministic
  lookup, serialization, generated documentation, and executable evidence.
- Canonicalized all camera-model ids, names, parameter counts, and layouts in
  one 18-model manifest consumed by Python and generated C++ code.
- Preserved the complete 74-format I/O inventory: 74 readable, 73 writable,
  74 inspectable, 43 bounded selectors across 37 formats, 74 streaming reads,
  and 71 streaming writes.

## [0.3.0] - 2026-08-29

- Expanded the compiled registry from the original 23-codec tier to 74
  built-in formats: 74 readable, 73 writable, and 74 inspectable.
- Added 43 bounded partial selectors across 37 formats, streaming reads for
  all 74 formats, and streaming writes for 71 formats.
- Added reconstruction, calibration, dense, point-cloud, Gaussian, mesh,
  scene, scientific-container, visual-inertial dataset, label-map, and video
  profiles, with strict rejection outside each documented bounded profile.
- Added explicit coordinate contracts for every built-in format and versioned
  normalization contracts for all 103 public data representations.
- Added transactional output handling, direct and mapped I/O paths, exact
  repository-to-sdist source-closure checks, provider qualification, public
  fixture provenance, and cross-platform installed-wheel validation.
- Made frozen backend-qualification configuration identities invariant across
  LF and CRLF checkouts.
- Kept NumPy as the only unconditional runtime dependency; established
  separately installable extras for HDF5, Zarr, NCore, TIFF, E57, Arrow,
  OpenVDB, AVIF, and USD support.

See the [SceneIO 0.3.0 release notes](docs/releases/v0.3.0.md) for the full
scope, compatibility boundaries, and validation matrix.

## [0.2.0] - 2026-07-24

- Published the first compiled, stable-ABI SceneIO format-I/O tier with 23
  codecs and Linux, macOS, and Windows wheels.

[Unreleased]: https://github.com/SceneAPI/SceneIO/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/SceneAPI/SceneIO/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/SceneAPI/SceneIO/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/SceneAPI/SceneIO/releases/tag/v0.2.0
