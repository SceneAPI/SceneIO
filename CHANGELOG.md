# Changelog

All notable changes to SceneIO are recorded here. Release-specific detail is
kept in [`docs/releases/`](docs/releases/).

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

[0.3.0]: https://github.com/SceneAPI/SceneIO/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/SceneAPI/SceneIO/releases/tag/v0.2.0
