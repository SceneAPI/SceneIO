# Format & data-structure coverage

This is the canonical source for SceneIO's **current codec capabilities and
validation status**. It reconciles the live registry
(`src/sceneio/io/registry.py`) with the generated capability snapshot below.
Future policy and sequencing live in
[`coverage_roadmap.md`](coverage_roadmap.md), not in current-evidence claims.

The detailed execution, verification, and wheel-validation sequence for the
remaining formats is in
[`format_gap_implementation_plan.md`](format_gap_implementation_plan.md).
The module-boundary, offline-source, bounded package-closure, and trigger-based
codec-backend mechanism are in
[`repository_organization_plan.md`](repository_organization_plan.md); its
commit-sized execution checklist is
[`next_stage_implementation_checklist.md`](next_stage_implementation_checklist.md).

Legend: ✅ done · 🟡 partial · ⬜ pending · **R** read · **W** write

> Status note: everything marked ✅ is implemented by the compiled
> `sceneio._core`. The original 23 codecs ship in SceneIO 0.2.0; safetensors,
> PTS, DMB, BAL, BMP, TGA, generic point PLY, PCD, EuRoC state CSV, and the
> OpenCV/ROS/Kalibr calibration codecs, g2o pose graphs, and the COLMAP
> feature database, SuperSplat compressed PLY, PlayCanvas SOG, KSplat,
> mesh/scene codecs, LAZ, lazy image directories, and raw Y4M are post-0.2
> formats on
> `phase0-nanobind-core` and are not released yet.
>
> **COLMAP dense/workspace checkpoint (2026-07-29):** the current local
> registry has 54 codecs: 48 buffer-backed files, three path-native
> multi-file containers, and three directories. The four additions are exact
> COLMAP MVS depth and normal matrices, consistency graphs, and fused-point
> visibility. All four support mmap reads, direct sinks, metadata inspection,
> and independent binary oracles; depth and normal also support bounded
> windows. The lazy `sceneio.colmap_mvs` adapter covers canonical dense,
> PMVS, and CMP-MVS topology without decoding encoded image payloads. Historical
> 50-codec validation records below remain evidence for their named commits;
> the 54-codec tree is pending its final pushed CI/package run.
>
> **C3/C4 CI correction candidate (2026-07-29):** the exact collection is
> 3,879 nodes with normalized SHA-256
> `39fe1dc507ed2faea06a75dcc823515ff550dfa742813b89cdcd24a7584ad4f6`.
> Local MSVC passes 3,874 tests with five documented skips. The correction
> scopes the COLMAP consistency-graph ownership assertion to its reader and
> bounds resident growth by the mapped input plus exact decoded vectors. It
> also replaces SOG's host-math-library metadata variation with a pinned,
> attributed repository-contained transform; Windows and Ubuntu now produce
> the same exact archive. The automatic failures at runs
> `30458601255`/`30458601174` are therefore addressed locally; a new pushed
> CI and build-only package run are still required before this checkpoint is
> called hosted-green.
>
> **Stable-ABI evidence correction (2026-07-28):** earlier package records
> verified `cp312-abi3` wheel tags, contents, and Python 3.12 smoke but did not
> verify the embedded extension’s ABI. R6 review found a CPython-specific
> fallback. The current branch requires `Python::SABIModule`, checks the
> nanobind stable target/suffix, and produces `_core.pyd` on Windows plus
> `_core.abi3.so` on Unix. No corrected release has been published.
>
> **R6 closure (2026-07-28):** the correctness-tested current backends are
> accepted as this stage's release baseline at packaged source commit
> `105b3017dae37345a6974f289e661d9173186a2a`. Exact-head CI
> [30405666674](https://github.com/SceneAPI/SceneIO/actions/runs/30405666674),
> native-runtime validation
> [30405666673](https://github.com/SceneAPI/SceneIO/actions/runs/30405666673),
> and build-only package run
> [30406706115](https://github.com/SceneAPI/SceneIO/actions/runs/30406706115)
> pass; publication is skipped. The exact sdist and MSVC, manylinux2014 GCC 10,
> and AppleClang cp312-abi3 wheels pass independent artifact inspection and
> all-50 installed smoke. Exact hashes are in the
> [closure evidence](next_stage_implementation_checklist.md#r6-closure-evidence).
> The 124 provisional performance rows remain transparent optional post-R6
> work and are not relabeled qualified. No new format wave is activated.
>
> **Validated N0 implementation checkpoint (2026-07-25, `a5e7fa4`):** the live registry contains
> 50 available codecs. Every codec reports read, write, inspect, streaming read,
> and streaming write support; 28 advertise a bounded partial selector. Local
> MSVC validation passes 2,919 tests with 4 documented skips, the 50-codec
> benchmark guard, source/wheel rebuild, and a NumPy-only installed-wheel
> smoke. [Normal CI run 30181287022][current-ci] passes the full Linux suite,
> retained performance guard, pinned GCC 10 job, and Linux/Windows/macOS
> portability matrix. [Compiler-instrumented run
> 30181287161][current-instrumented] collects all 2,923 tests and passes its
> complete and focused native jobs. [Release dry run
> 30181286675][current-release] builds and smoke-tests all three platform wheel
> sets plus the source archive with publication skipped. N0 is validated at
> this immutable implementation commit; the later R1-R6 records below
> supersede its next-step wording.
>
> **R1 implementation and validation checkpoint (2026-07-26, `95061c6`):**
> R1a adds the immutable 50-codec
> ownership projection, checked compatibility/repository contracts, and a
> 130-operation performance ledger. R1b separates completed Waves A-C evidence
> from the active dependency queue and adds documentation consistency checks.
> These organization-only changes do not alter codec behavior. Local MSVC
> collects 2,955 tests and passes 2,951 with four documented skips. A clean
> Windows abi3 wheel built from the exact `95061c6` source archive passes the
> NumPy-only installed-wheel smoke. [Normal CI run
> 30187895845][r1-current-ci] passes the complete suite, retained performance
> guard, pinned GCC 10 job, and Linux/Windows/macOS portability matrix.
> [Instrumented run 30187895838][r1-current-instrumented] passes its complete
> and focused jobs. [Build-only release run
> 30189483142][r1-current-release] builds the source archive and builds and
> smoke-tests all three platform wheel sets, with publication skipped. R1 is
> closed and R2 is next.
>
> **R2 local organization checkpoint (2026-07-26, `14bf53b`):** R2.0
> (`40d5412`) removes image-sequence upward runtime dependencies; R2.1
> (`ccfeea4`) extracts shared registry services; and `b2bda1d` moves the four
> calibration registrations and metadata inspectors behind the first
> lower-layer family boundary. `29af9de` lowers the shared inspection types and
> mmap bridge while retaining compatibility. `975533f` moves the six
> contiguous mesh registrations plus only the PLY-mesh/STL/OFF facade-owned
> inspectors; OBJ/glTF/GLB bespoke adapters remain in place. `8040bc7` lowers
> the proven shared metadata limits, exact-read/integer grammar, and
> image-result constructor. `68c47d6` then moves the eight contiguous image
> registrations and their bounded metadata parsers behind lower family
> modules while keeping image-sequence access live. `14bf53b` moves the final
> contiguous family, Y4M plus the lazy image directory, while retaining live
> image-extension access and directory-adapter ownership. Codec behavior and
> the 50-id inventory remain unchanged. Local MSVC collects 3,083 tests and
> passes 3,079 with four documented skips; the all-codec
> performance/allocation guard passes, and a Windows abi3 wheel derived from
> the exact 306-member source archive passes the expanded NumPy-only smoke and
> installed sequence-family probe.
> [Normal CI run
> 30193628676][r2-calibration-ci] and [compiler-instrumented run
> 30193628672][r2-calibration-instrumented] pass for the preceding calibration
> checkpoint. [Normal CI run
> 30195153288][r2-shared-ci] and [compiler-instrumented run
> 30195153277][r2-shared-instrumented] pass for `29af9de`. [Normal CI run
> 30196192081][r2-mesh-ci] and [compiler-instrumented run
> 30196192103][r2-mesh-instrumented] pass for `975533f`. [Normal CI run
> 30197244102][r2-image-helpers-ci] and [compiler-instrumented run
> 30197244104][r2-image-helpers-instrumented] pass for `8040bc7`. [Normal CI
> run 30198507638][r2-images-ci] and [compiler-instrumented run
> 30198507645][r2-images-instrumented] pass for `68c47d6`. [Normal CI run
> 30200316679][r2-sequences-ci] and [compiler-instrumented run
> 30200316665][r2-sequences-instrumented] pass for `14bf53b`. `1ec0550`
> stages all built-in definitions outside the public registry,
> validates the exact canonical aggregate, and publishes the same 50 objects
> once. Parent/candidate codec-definition and operation-binding contracts are
> exact, and the portable 50-codec benchmark structure retains hash
> `2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`,
> and the complete local MSVC suite collects 3,095 tests and passes 3,091 with
> four documented skips. The exact-tree package preflight contains 310 source
> files and a 73-file Windows abi3 wheel whose only runtime-member delta is
> `_registry/assembly.py`; index/archive/wheel identity, attribution,
> NumPy-only metadata, native dependency inspection, the complete installed
> smoke, and an explicit aggregate/sequence probe pass. All three independent
> reviews are clear. `6086315` corrects the portable structure guard without
> changing runtime or wheel contents. [Normal CI run
> 30204352767][r2-aggregate-ci] and [compiler-instrumented run
> 30204352744][r2-aggregate-instrumented] pass the exact corrected commit,
> including the strict performance/allocation guard and all portability lanes.
> The boundary is closed. It enables the four remaining interleaved families
> to move without changing detection order.
>
> **R2 arrays checkpoint (2026-07-26):** exact commit `d99dcf0` moves the
> non-contiguous `pfm`, `npy`, `npz`, `safetensors`, `flo`, and `dmb`
> definitions to
> `_registry/families/arrays.py`, and their metadata parsers now live in
> `_inspectors/arrays.py`. The registry facade retains its canonicalization
> callbacks and restores the exact six positions through aggregate staging;
> codec behavior and the 50-id inventory are unchanged. Parent-derived
> valid/malformed fixtures, bounded large-file inspection, mapped-view and
> selector suites, the exact all-codec structural hash
> `2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`,
> the arrays-only hash
> `5c0104dc8a0372ede12a86f48c8c57a7426718b030c95ec9d7088a9b26364aac`,
> and the retained five-run guard pass locally. The candidate collects 3,134
> tests. Fifteen interleaved same-host import samples add only
> `_registry.families.arrays` and `_inspectors.arrays` to the I/O facade;
> `import sceneio` and direct `_core` module sets are unchanged. Exact-tree
> packaging, a fresh NumPy-only installed-wheel probe, and all three
> independent reviews pass. [Normal CI run
> 30207617248][r2-arrays-ci] and [compiler-instrumented run
> 30207617253][r2-arrays-instrumented] are green for the exact commit. Arrays
> are closed; points are active next.
>
> **R2 points checkpoint (2026-07-26):** Exact commit `686f42e` moves `ply`,
> `pcd`, `xyz`, `pts`, `las`, and `laz` to
> `_registry/families/points.py`, while their metadata parsers live in
> `_inspectors/points.py`. Aggregate staging restores canonical positions
> 12/13/39/40/41/42 and retains the exact mmap, sink, and point-range native
> targets. Parent-derived valid/malformed fixtures, full-versus-partial
> slices, path release, generated 50,000-point inspection bounds, the exact
> all-codec structural hash
> `2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`,
> the points-only hash
> `8282b574166aeb88d0eb51ded126566d7a4f21b0752244ea0c987dcee06437bd`,
> and the strict five-run guard pass locally. The candidate collects 3,184
> tests. Fifteen same-host import samples add only
> `_registry.families.points` and `_inspectors.points` to the I/O facade;
> `import sceneio` and direct `_core` module sets are unchanged. The complete
> local suite passes 3,180 tests with four documented skips. Exact-tree
> source/wheel identity, attribution, NumPy-only metadata, native dependency
> inspection, complete installed smoke, and an explicit all-six point probe
> pass. All three independent reviews are clear for staged tree
> `442093b402db2af290c9a19a61747b6691e2af1c`; the largest independent focused
> matrix passes 729 tests and no review required a source change. The final
> exact-tree source archive and wheel pass at tree
> `688f0a4caa81edf6e499f7b72e1bc03117a4ddf0`. [Normal CI run
> 30210055913][r2-points-ci] and [compiler-instrumented run
> 30210055930][r2-points-instrumented] are green for the exact commit. Points
> are closed; reconstruction is active next.
>
> **R2 reconstruction inspector checkpoint (2026-07-26):** The 12
> reconstruction, pose, graph, and database metadata implementations now live
> in `_inspectors/reconstruction.py`; the compatibility facade keeps
> same-signature delegates and its historical shared-value/helper exports.
> A parent-derived contract fixes deterministic artifacts, normalized
> inspections, full logical record fingerprints, and malformed causes for all
> 12 formats. Generated pose, graph, transforms/OpenMVG JSON, COLMAP-directory,
> and database fixtures above 4 MiB stay below the 2 MiB traced-allocation
> bound and release their paths promptly. Both candidate benchmark captures
> reproduce the exact all-50 and ordered reconstruction-only structural
> hashes, and the retained five-run guard passes. The inspector checkpoint and
> its portable absent-value fingerprint correction are pushed at `49fd976`
> and `6e94614`; [normal CI run 30214058828][r2-reconstruction-inspector-ci]
> and [compiler-instrumented run
> 30214058885][r2-reconstruction-inspector-instrumented] pass the corrected
> checkpoint.
>
> **R2 reconstruction registry checkpoint (2026-07-26):** all 12 exact Codec
> definitions now come from the immutable, side-effect-free
> `_registry/families/reconstruction.py` tuple and are staged once into their
> original non-contiguous canonical positions. Native directory/database
> operations, nine mmap/sink adapter pairs, EuRoC state ranges, COLMAP image
> selectors, database image/pair selectors, detection precedence, and
> explicit-only TUM/KITTI behavior retain their frozen targets. The complete
> local suite passes 3,252 tests with four documented skips; the 3,256-node
> collection, both structural benchmark hashes, and strict five-run guard
> pass. A scaled family-only diagnostic uses files up to 35.2 MiB; Windows
> cannot provide the requested POSIX cache-eviction hint, so it is recorded as
> warm-cache evidence. Fifteen interleaved exact-export import samples retain
> the seven-module `sceneio` and eight-module direct `_core` sets; the I/O
> facade adds only `_registry.families.reconstruction` (42 to 43 modules).
> The original exact-tree source archive, derived wheel, and external
> NumPy-only smoke pass with all 12 family members exercised, and all three
> independent reviews are clear. The extraction is pushed at `be836a0`.
> [normal run 30216568265][r2-reconstruction-registry-ci] exposed AppleClang
> retaining `-0.0` in BAL's canonical 180-degree quaternion and the GCC-10
> command omitting `/work` from its import path after changing directory. The
> BAL repair normalizes only exact-zero quaternion components after sign
> selection. The separate workflow repair retains installed-package isolation
> at `/tmp` and adds command-scoped `PYTHONPATH=/work` for the architecture
> fixture import. The repairs are committed at `1f32b49` and `aa5b624`.
> The final exact implementation tree is `06f89e8b685c3536af0e67a462d9cff90a86bc9c`;
> its 321/322/79 Git/source-archive/wheel inventory is byte-consistent, the
> external NumPy-only smoke and positive-zero probe pass, and all repair
> reviews are clear. [Normal run
> 30218232248][r2-reconstruction-registry-final-ci] and
> [compiler-instrumented run
> 30218232246][r2-reconstruction-registry-final-instrumented] pass every final
> lane. The checkpoint is closed.
>
> **R2 splat-family complete (2026-07-27):** metadata ownership for
> `gaussian_ply`, `compressed_ply`, `sog`, `ksplat`, `spz`, and `splat` now
> lives in `_inspectors/splats.py`. The compatibility facade retains exact
> `(path, datatype)` wrappers and unchanged dispatch; the lower module uses no
> full decoder or registry. Inspector commit `a4c968b` passes
> [normal run 30224059298](https://github.com/SceneAPI/SceneIO/actions/runs/30224059298)
> and
> [compiler-instrumented run 30224059282](https://github.com/SceneAPI/SceneIO/actions/runs/30224059282).
> The architecture suite covers exact-parent
> valid/malformed outcomes, all four accepted SOG entry forms, facade
> delegation, dependency direction, inert reload, generated 36 MiB-plus
> bounded inspections, retained results/exceptions, individual declared-layer
> release, and whole-directory replacement.
>
> All six exact Codec definitions now come from
> `_registry/families/splats.py`, with the facade-owned SOG path callbacks
> injected into its side-effect-free factory. Aggregate staging restores
> positions 2/3/4/5/14/49 and preserves exact ASTs, operation descriptors,
> detection, path routing, and partial selectors. The candidate collection is
> 3,309 nodes with sorted normalized SHA-256
> `cd0a8c1a273dd87d72c9a08edf39d45f93b562295e8c3216e09b076b4dd65a43`;
> 3,305 pass locally with four documented skips. The all-six installed smoke
> surface now includes Gaussian PLY, SPZ, and SPLAT as well as compressed PLY,
> SOG, and KSplat.
>
> Two structural captures and the retained five-run guard pass. A 15-sample
> randomized exact-parent comparison on every large fixture keeps all six
> inspector medians within the planned variation bound and reproduces the
> parent's maximum traced allocation exactly. A second 15-sample randomized
> comparison covers all 23 read, write, inspect, and supported point-range
> operations; every median passes its variation bound and every candidate
> peak equals its parent peak. Fresh-process import sets are exact at 7/7,
> 43/45, and 8/8 modules, with only `_inspectors.splats` and
> `_registry.families.splats` added to the I/O facade. Cross-platform parent
> behavior is frozen and green at `1864359`. Exact-tree source/wheel
> packaging, the external NumPy-only installed smoke, and all three
> independent reviews pass. Registry implementation `3e46d82` and the
> platform-fingerprint contract repair `9928c6d` are pushed;
> [normal run 30228235491](https://github.com/SceneAPI/SceneIO/actions/runs/30228235491)
> and
> [compiler-instrumented run 30228235535](https://github.com/SceneAPI/SceneIO/actions/runs/30228235535)
> pass the final tree, including all three splat operating systems and the
> GCC-10 lane. R2 is closed and R3 is active.
>
> **R3.1a benchmark boundary (2026-07-26, current tree):** the development
> harness retains its `bench/bench_io.py` CLI while shared models,
> measurements, and reporting live under `bench/io_bench/`. Parent and two
> candidate one-run captures reproduce the exact 50-codec structural SHA-256
> `2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`
> and identical deterministic projections. Record-aware fixture fingerprints,
> console output, outside-checkout entry modes, and the warmed-parent RSS
> meaning are checked contracts. After one noisy LAS comparator, the unchanged
> complete five-run confirmation passes with LAS read at 1.32x. This is
> behavior-equivalence evidence, not a new codec-performance claim. Normal run
> [30231629465](https://github.com/SceneAPI/SceneIO/actions/runs/30231629465)
> and compiler-instrumented run
> [30231629496](https://github.com/SceneAPI/SceneIO/actions/runs/30231629496)
> pass the exact R3.1a commit. R3.1b closes at follow-up commit `0bdfe0f`.
> Its versioned
> development-only protocol uses one warmed fresh child per sample, reports
> baseline/peak/delta RSS with platform and sampler metadata, and refuses to
> turn unavailable sampling into a numeric result. Three samples at 8 MiB and
> 48 MiB keep a bounded 64 KiB operation flat while the full-payload control
> reproduces and rejects approximately 40 MiB growth. Semantic operation
> signatures, request binding, high-water calibration, and every-size
> comparisons close the reviewed false-pass cases, and the protocol test is
> wired into the Linux/Windows/macOS mmap lane. Existing codec capability
> claims are unchanged. Local MSVC collects 3,320 tests and passes 3,316 with
> four documented skips; the unchanged complete five-run performance guard,
> all three independent reviews, exact-source packaging, and isolated
> NumPy-only wheel smoke pass. Normal run
> [30234796010](https://github.com/SceneAPI/SceneIO/actions/runs/30234796010)
> passes the complete suite and all platform lanes; compiler-instrumented run
> [30234796025](https://github.com/SceneAPI/SceneIO/actions/runs/30234796025)
> passes both jobs. R3.2 family extraction is complete. Arrays close at
> `6d9ec34`: normal run
> [30236069971](https://github.com/SceneAPI/SceneIO/actions/runs/30236069971)
> and compiler-instrumented run
> [30236069959](https://github.com/SceneAPI/SceneIO/actions/runs/30236069959)
> pass. Calibration closes at `5dc03f4`: normal run
> [30237676629](https://github.com/SceneAPI/SceneIO/actions/runs/30237676629)
> and compiler-instrumented run
> [30237676648](https://github.com/SceneAPI/SceneIO/actions/runs/30237676648)
> pass. The current raster-image extraction preserves the same eight format
> capabilities and only moves development benchmark ownership. Seven live
> rows have independent metrics; portable Radiance HDR benchmark throughput is
> an explicit exemption while independent NumPy RGBE parity remains covered.
> Raster images close at `6572a76`: normal run
> [30239455960](https://github.com/SceneAPI/SceneIO/actions/runs/30239455960)
> and compiler-instrumented run
> [30239455952](https://github.com/SceneAPI/SceneIO/actions/runs/30239455952)
> pass. The current mesh extraction moves five buffer-backed specs plus shared
> glTF fixture/oracle helpers without changing any format capability;
> specialized glTF orchestration remains in the compatible facade until
> runner extraction. Meshes close at `613fd26`: normal run
> [30241711640](https://github.com/SceneAPI/SceneIO/actions/runs/30241711640)
> and compiler-instrumented run
> [30241711620](https://github.com/SceneAPI/SceneIO/actions/runs/30241711620)
> pass. The current point extraction moves the non-contiguous XYZ/PTS/
> point-PLY/PCD/LAS/LAZ benchmark hook and its fixtures/comparisons without
> changing a format capability. Five live rows have independent metrics; XYZ
> explicitly exempts benchmark throughput while independent NumPy text parity
> remains covered. Points close at `45e2757`: normal run
> [30244892746](https://github.com/SceneAPI/SceneIO/actions/runs/30244892746)
> and compiler-instrumented run
> [30244892600](https://github.com/SceneAPI/SceneIO/actions/runs/30244892600)
> pass. The local reconstruction extraction moves nine buffer-backed specs
> plus their fixtures and portable EuRoC/g2o/BAL comparisons without changing
> a format capability. Specialized COLMAP binary, text, and database
> orchestration remains facade-owned. Three reconstruction rows have live
> comparison metrics; six record exact benchmark-throughput exemptions backed
> by independent parity. The g2o comparison now materializes every graph value
> rather than counts only. Reconstruction closes at `76ed21b`: normal run
> [30247662591](https://github.com/SceneAPI/SceneIO/actions/runs/30247662591)
> and compiler-instrumented run
> [30247662622](https://github.com/SceneAPI/SceneIO/actions/runs/30247662622)
> pass. The local sequence extraction moves Y4M plus the Y4M and
> image-directory fixtures without changing a format capability. The
> image-directory `DirectorySpec` remains facade-owned until runner
> extraction. Y4M has live portable metrics and validates complete planes and
> metadata; image-directory throughput records one exact exemption backed by
> manifest/PGM parity. Sequences close at `4b8c829`: normal run
> [30250394890](https://github.com/SceneAPI/SceneIO/actions/runs/30250394890)
> and compiler-instrumented run
> [30250394906](https://github.com/SceneAPI/SceneIO/actions/runs/30250394906)
> pass. The local splat extraction lower-owns all six ordinary rows and moves
> their Gaussian fixture plus optional `gsply` adapters unchanged. Gaussian
> PLY and SPZ retain live independent metrics; Compressed PLY, SOG, KSplat,
> and `.splat` retain exact throughput exemptions backed by their codec parity
> suites. Splats close at `cd32268`: normal run
> [30253301819](https://github.com/SceneAPI/SceneIO/actions/runs/30253301819)
> and compiler-instrumented run
> [30253301871](https://github.com/SceneAPI/SceneIO/actions/runs/30253301871)
> pass. The runner extraction moves the complete sweep and specialized
> glTF/COLMAP/image-directory orchestration to `io_bench/runner.py`; the thin
> compatible entry point preserves the exact checked helper surface. The
> 50-codec structure, complete suite, 366/81 source/wheel inventory, 15
> attributions, and fresh NumPy-only smoke pass. Exact runner commit
> `cf8d117` passes [normal run
> 30257105454](https://github.com/SceneAPI/SceneIO/actions/runs/30257105454)
> and [compiler-instrumented run
> 30257105468](https://github.com/SceneAPI/SceneIO/actions/runs/30257105468).
> The final R3.2 behavior checkpoint is implemented locally: the immutable
> 50-entry ledger has 33 timed comparisons and 17 exact reviewed exemptions,
> complete sweeps reject missing/duplicate/noncanonical built-ins, runtime
> extensions stay outside repository qualification, and strict mode propagates
> every required comparison failure. Its one-run strict sweep has 50
> successful rows and all 33 timed pairs; the skip-comparison structural hash
> remains unchanged. The complete five-run strict O4/O5 guard passes; local
> MSVC collects 3,339 tests and passes 3,335 with four documented skips, and
> Ruff is clean. All three independent closure reviews are clear. The exact
> staged 367-file tree produces a 368-file sdist and an 81-member Windows abi3
> wheel with all 15 attribution files; a fresh environment contains only
> SceneIO and NumPy, and `sceneio._wheel_smoke` returns `2`.
> Exact qualification commit `0e54cf5` passes [normal run
> 30263506366](https://github.com/SceneAPI/SceneIO/actions/runs/30263506366)
> and [compiler-instrumented run
> 30263506270](https://github.com/SceneAPI/SceneIO/actions/runs/30263506270).
> Exact catalog commit `81f143b` passes [normal run
> 30266501529](https://github.com/SceneAPI/SceneIO/actions/runs/30266501529)
> and [compiler-instrumented run
> 30266501618](https://github.com/SceneAPI/SceneIO/actions/runs/30266501618).
> R3.3 is locally complete: an immutable catalog owns the exact 50 built-ins as
> 44 buffer, three path, and three directory fixture definitions, including
> the live projection of 28 partial-capable codecs and 32 selector
> declarations. The mmap suite now consumes
> `tests/_support/buffer_codec_cases.py`. Exact migration commit `9a73892`
> passes [normal run
> 30268797350](https://github.com/SceneAPI/SceneIO/actions/runs/30268797350)
> and [compiler-instrumented run
> 30268797374](https://github.com/SceneAPI/SceneIO/actions/runs/30268797374).
> The duplicated local matrix is now removed; its 44-case order, live callable
> identities, and 43-codec portable encoded-fixture projection SHA-256
> `b21a55c6cbde2a46d89bf2bc013b6e81ffe3d58565922dcd690c2605f31143ab`
> remain checked alongside the semantic mmap suite. Compressed PLY is excluded
> from that universal byte hash because its quantization has an established
> AppleClang profile; its shared semantic Gaussian input and platform-profiled
> parity test remain checked. Exact removal commit `fc86f44` passes
> [normal run
> 30271311308](https://github.com/SceneAPI/SceneIO/actions/runs/30271311308)
> and [compiler-instrumented run
> 30271309916](https://github.com/SceneAPI/SceneIO/actions/runs/30271309916).
> The complete local tree
> collects 3,345 tests and passes 3,341 with four
> documented skips; Ruff and all three independent reviews are clear. A
> one-run 50-codec benchmark smoke retains structural SHA-256
> `2f7172317f354f43b493ab5373566fec246cb83d918d1f74a3ed32daaf6d5376`.
> The exact staged tree has 371 tracked files and produces a 372-file sdist
> whose only generated file is `PKG-INFO`; its sdist-derived 81-member Windows
> abi3 wheel contains one native module and all 15 attribution files. A fresh
> environment contains only SceneIO and NumPy, and `sceneio._wheel_smoke`
> returns `2`.
> Streaming behavior now has focused ownership in
> `tests/test_io_streaming.py`: the same 14 function bodies produce 16 nodes
> with unchanged test names and parameter ids, and the assembly contract pins
> every old/new path. The complete local suite remains 3,341 passed and four
> skipped from 3,345 collected; normalized collection SHA-256 is
> `1131f211bb324c4d6800350b71364eb1f95efd13acef5a6dc4e984d708a88d53`.
> The exact staged tree has 373 files, its sdist has only generated
> `PKG-INFO` beyond those files, and the sdist-derived 81-member Windows abi3
> wheel retains one native module and all 15 attribution files. A fresh
> SceneIO-plus-NumPy installation passes `sceneio._wheel_smoke`.
> Exact streaming commit `914702d` passes [normal run
> 30274413815](https://github.com/SceneAPI/SceneIO/actions/runs/30274413815)
> and [compiler-instrumented run
> 30274413693](https://github.com/SceneAPI/SceneIO/actions/runs/30274413693).
> Inspection behavior now lives in `tests/test_io_inspection.py`; its 47 tests
> and three helpers preserve all 76 node suffixes, and both platform commands
> include the module explicitly. The complete collection remains 3,345 with
> normalized SHA-256
> `f90c2f368fa8d5f976291cc8af3c7038c740893ac1abc78ec9b1bcf4ca5af959`.
> Exact inspection commit `0e21e27` passes [normal run
> 30278777267](https://github.com/SceneAPI/SceneIO/actions/runs/30278777267)
> and [compiler-instrumented run
> 30278777173](https://github.com/SceneAPI/SceneIO/actions/runs/30278777173).
> Partial-family migration starts with three unchanged array-specific DMB/FLO
> tests in `tests/test_io_partial_arrays.py`; the complete collection remains
> 3,345 with normalized SHA-256
> `ae4ab66a375c9c130ddf10682eb37e2ba21a0433ba2fb454ecce4358ef616414`.
> Its exact 375-file source tree produces a 376-file sdist with only generated
> `PKG-INFO` and an unchanged 81-member Windows abi3 wheel. A fresh
> SceneIO-plus-NumPy installation passes `sceneio._wheel_smoke`.
> Exact array commit `5009ea0` passes [normal run
> 30282057346](https://github.com/SceneAPI/SceneIO/actions/runs/30282057346)
> and [compiler-instrumented run
> 30282056576](https://github.com/SceneAPI/SceneIO/actions/runs/30282056576).
> The image partial unit moves 10 unchanged parameterized Netpbm/WebP nodes
> into `tests/test_io_partial_images.py` and lowers their two shared
> image-window assertions. Collection remains 3,345 with normalized SHA-256
> `c9db2c71c11f6af8d4fcd5a08a5bf75a2428ea915805e3671c5cadb2ef581cc4`.
> Exact package verification records 377 source files, a 378-file sdist whose
> only generated member is `PKG-INFO`, and an unchanged 81-member Windows abi3
> wheel. A fresh SceneIO-plus-NumPy installation passes
> `sceneio._wheel_smoke`.
> Exact image commit `d198560` passes [normal run
> 30285128366](https://github.com/SceneAPI/SceneIO/actions/runs/30285128366)
> and [compiler-instrumented run
> 30285128448](https://github.com/SceneAPI/SceneIO/actions/runs/30285128448).
> The mesh partial unit moves the unchanged face-range semantic and
> mapping-close test into `tests/test_io_partial_meshes.py`. Its exact
> path-only rename and function projection are pinned. Collection remains
> 3,345 with normalized SHA-256
> `c658cb0d7353ad5c6cf4f6e38b01a02418f693b121e6d8f4bba887945821cc9d`.
> Exact package verification records 378 source files, a 379-file sdist whose
> only generated member is `PKG-INFO`, and an unchanged 81-member Windows abi3
> wheel. A fresh SceneIO-plus-NumPy installation passes
> `sceneio._wheel_smoke`.
> Exact mesh commit `4294dbe` passes [normal run
> 30287854716](https://github.com/SceneAPI/SceneIO/actions/runs/30287854716)
> and [compiler-instrumented run
> 30287854692](https://github.com/SceneAPI/SceneIO/actions/runs/30287854692).
> The point partial unit moves 13 unchanged XYZ/LAS nodes into
> `tests/test_io_partial_points.py` and lowers their shared point-range
> assertion. Collection remains 3,345 with normalized SHA-256
> `2451c9bb2606ac1587011eafeb2345fc9f34f7e08df7ea17b239b5a1e78a624f`.
> Exact package verification records 379 source files, a 380-file sdist whose
> only generated member is `PKG-INFO`, and an unchanged 81-member Windows abi3
> wheel. A fresh SceneIO-plus-NumPy installation passes
> `sceneio._wheel_smoke`.
> Exact point commit `ac1a4d1` passes [normal run
> 30290617469](https://github.com/SceneAPI/SceneIO/actions/runs/30290617469)
> and [compiler-instrumented run
> 30290617607](https://github.com/SceneAPI/SceneIO/actions/runs/30290617607).
> The reconstruction partial unit moves 15 unchanged COLMAP nodes and their
> private helpers into `tests/test_io_partial_reconstruction.py`, while the
> shared fresh-process RSS helper gains lower ownership. Collection remains
> 3,345 with normalized SHA-256
> `217c227e566a6767fc59b031b1217202ced5ba0dc6a14b3b7fa2d27c0f9314f4`.
> Exact package verification records 380 source files, a 381-file sdist whose
> only generated member is `PKG-INFO`, and an unchanged 81-member Windows abi3
> wheel. A fresh SceneIO-plus-NumPy installation passes
> `sceneio._wheel_smoke`.
> The first hosted normal run `30294120621` exposed four explicit manylinux
> selectors that retained the old shared-module path. They now name the
> focused reconstruction module, and the assembly suite rejects stale paths.
> Compiler-instrumented run `30294120444` passed the reconstruction commit.
> Follow-up commit `b5e5c55` passes normal run `30296172958` and
> compiler-instrumented run `30296174522`.
>
> The final R3.3 ownership audit confirms that sequence and splat dedicated
> partial behavior is already owned by their family architecture/codec suites.
> The seven tests left in `tests/test_io_partial.py` intentionally span
> families; their sequence/splat/shared ownership, unchanged AST projections,
> 21 exact family-owned node/parameter ids, and per-function shared format
> maps are now contract-pinned. No codec capability changes.
> The closure candidate passes 3,341 tests with four documented skips, Ruff,
> and the complete five-run strict O4/O5 guard. Its exact 380-file staged tree
> produces a 381-file sdist and 81-member Windows ABI3 wheel with one native
> module, all 15 attribution files, and NumPy as the sole unconditional
> dependency; fresh installed smoke passes.
> Exact R3.3 closure commit `811cb0d` passes [normal run
> 30300122309](https://github.com/SceneAPI/SceneIO/actions/runs/30300122309)
> and [compiler-instrumented run
> 30300122324](https://github.com/SceneAPI/SceneIO/actions/runs/30300122324).
>
> R3.4 is implemented locally. Its installed-wheel smoke derives the exact
> 50-codec order from `BUILTIN_DEFINITIONS`, requires agreement with the
> installed registry and public listing, and observes successful public
> write/read/inspect. Every declared stream-capability direction is paired
> with a successful corresponding public path call; dedicated mmap and sink
> suites retain independent allocation proof. All 32 selectors declared by
> 28 partial-capable codecs are exercised. The reviewed property-specific
> exemption mechanism exists, but the current exemption set is empty. The
> complete local suite passes 3,344 tests with four documented skips; Ruff and
> the five-run strict guard pass. Its first exact 380-file source tree produces
> a 381-file sdist and 81-member Windows ABI3 wheel with one native module, all
> 15 attribution files, NumPy-only unconditional metadata, and a passing fresh
> installed smoke.
>
> R4.1 reorganizes build ownership without changing a format capability. The
> root CMake file now assembles four focused modules; all 40 codec sources have
> one exact family owner, all 16 record sources are explicit, and the previous
> `_core` source/link order is retained. Fresh MSVC and manylinux2014 GCC 10
> configure projections match the R3.4 parent and both toolchains build the
> candidate. R4.1 is pushed at `b2cf5d4`; normal run `30310780347` and
> compiler-instrumented run `30310780355` pass. R4.2 closes at pushed commit
> `81e0e1c` and moves
> all 16 record and 40 codec registration functions into validated
> family-owned tables and exposes a private canonical inventory for all 49
> native/hybrid built-ins. The Python-owned `image_sequence` adapter remains
> separately checked. Preliminary MSVC/GCC 10, focused 416-test, collection,
> and strict-guard evidence passes. The complete suite passes 3,350 tests with
> four documented skips, and Ruff is clean. The exact 398/399/81
> source/sdist/wheel package gate and fresh NumPy-only installed smoke pass;
> all three confirmation reviews are clear. Normal run `30316577366` and
> compiler-instrumented run `30316577369` pass that exact commit. R4.3 and
> final R4 qualification close at pushed commit `da1d709`. All 40 native codec
> sources are family-nested; exact-tree MSVC/GCC 10, 398/399/81 package,
> public-snapshot, normal CI `30326256230`, and instrumented `30326256137`
> gates pass. No format capability changes.
>
> R5.1 is complete without changing the stable format table:
> ordinary wheels continue to use stb for JPEG. A default-off qualification
> build can select either the retained backend or SIMD-required
> libjpeg-turbo 3.2.0 behind the same JPEG API. Candidate intake and default
> wheel isolation pass. R5.2's same-corpus installed-wheel harness,
> frozen quality/size/parity bounds, actual configured-SIMD receipt, and
> manual nonpublishing three-toolchain workflow are implemented. The binding
> clean-wheel MSVC run at `7a88e7c` passes 1,596/1,597 frozen gates and records
> 4.787x encode / 1.782x decode median geomeans, but libjpeg-turbo fails the
> q95 4:4:4 comparative-quality floor (`-0.058242 dB` versus `-0.05 dB`).
> It is rejected as the combined stable default; stb remains repository-owned
> and unchanged. The user-gated remote comparison was not dispatched because
> no conforming candidate advanced beyond MSVC. R6 source intake is complete.
> The stable-ABI fallback found during package review is corrected and checked
> by local Windows/Ubuntu native builds; the final exact-tree MSVC package gate
> precedes the prepared, user-gated exact-sdist GCC 10/AppleClang build.

[current-ci]: https://github.com/SceneAPI/SceneIO/actions/runs/30181287022
[current-instrumented]: https://github.com/SceneAPI/SceneIO/actions/runs/30181287161
[current-release]: https://github.com/SceneAPI/SceneIO/actions/runs/30181286675
[r1-current-ci]: https://github.com/SceneAPI/SceneIO/actions/runs/30187895845
[r1-current-instrumented]: https://github.com/SceneAPI/SceneIO/actions/runs/30187895838
[r1-current-release]: https://github.com/SceneAPI/SceneIO/actions/runs/30189483142
[r2-calibration-ci]: https://github.com/SceneAPI/SceneIO/actions/runs/30193628676
[r2-calibration-instrumented]: https://github.com/SceneAPI/SceneIO/actions/runs/30193628672
[r2-shared-ci]: https://github.com/SceneAPI/SceneIO/actions/runs/30195153288
[r2-shared-instrumented]: https://github.com/SceneAPI/SceneIO/actions/runs/30195153277
[r2-mesh-ci]: https://github.com/SceneAPI/SceneIO/actions/runs/30196192081
[r2-mesh-instrumented]: https://github.com/SceneAPI/SceneIO/actions/runs/30196192103
[r2-image-helpers-ci]: https://github.com/SceneAPI/SceneIO/actions/runs/30197244102
[r2-image-helpers-instrumented]: https://github.com/SceneAPI/SceneIO/actions/runs/30197244104
[r2-images-ci]: https://github.com/SceneAPI/SceneIO/actions/runs/30198507638
[r2-images-instrumented]: https://github.com/SceneAPI/SceneIO/actions/runs/30198507645
[r2-sequences-ci]: https://github.com/SceneAPI/SceneIO/actions/runs/30200316679
[r2-sequences-instrumented]: https://github.com/SceneAPI/SceneIO/actions/runs/30200316665
[r2-aggregate-ci]: https://github.com/SceneAPI/SceneIO/actions/runs/30204352767
[r2-aggregate-instrumented]: https://github.com/SceneAPI/SceneIO/actions/runs/30204352744
[r2-arrays-ci]: https://github.com/SceneAPI/SceneIO/actions/runs/30207617248
[r2-arrays-instrumented]: https://github.com/SceneAPI/SceneIO/actions/runs/30207617253
[r2-points-ci]: https://github.com/SceneAPI/SceneIO/actions/runs/30210055913
[r2-points-instrumented]: https://github.com/SceneAPI/SceneIO/actions/runs/30210055930
[r2-reconstruction-inspector-ci]: https://github.com/SceneAPI/SceneIO/actions/runs/30214058828
[r2-reconstruction-inspector-instrumented]: https://github.com/SceneAPI/SceneIO/actions/runs/30214058885
[r2-reconstruction-registry-ci]: https://github.com/SceneAPI/SceneIO/actions/runs/30216568265
[r2-reconstruction-registry-instrumented]: https://github.com/SceneAPI/SceneIO/actions/runs/30216568311
[r2-reconstruction-registry-final-ci]: https://github.com/SceneAPI/SceneIO/actions/runs/30218232248
[r2-reconstruction-registry-final-instrumented]: https://github.com/SceneAPI/SceneIO/actions/runs/30218232246

## Data structures (memory Records)

SoA, zero-copy to numpy/torch (DLPack), conventions carried as metadata.

| Record | Intended DataType | Status | Notes |
|---|---|---|---|
| `Reconstruction` | `sparse_model` | ✅ | cameras (COLMAP models 0-17) + image poses (WXYZ, world→cam) + points3D/tracks + optional modern rigs/frames and sensor/data assignments |
| `GaussianCloud` | `splat` | ✅ record / ⬜ datatype | DataType registration is **Phase‑C** (needs a wire‑format id); the codecs use `"splat"` as an informal label |
| `PosedViewSet` | `camera` + poses | ✅ record / ⬜ datatype | SE3/view + optional `Camera` intrinsics; per‑source convention tags (order/direction/axis/scale). `"posed_views"` label is informal, Phase‑C |
| `Camera` | (shared) | ✅ | COLMAP model ids 0-17 + exact `params[]`; reused by `Reconstruction` and `PosedViewSet` |
| `Image` | `image_sequence` elem | ✅ | interleaved HxWxC (u8/u16/f32), color_space/alpha_mode/maxval metadata, owner-safe zero-copy `pixels` |
| `ImageSequence` | `image_sequence` | ✅ | owned lazy encoded-frame paths or owned uint8 planar Y/U/V frames; exact optional int64-ns timing, dimensions, chroma sampling/siting, range, matrix, interlace, rate, and aspect metadata |
| `TensorDict` | (named arrays) | ✅ | dict‑like, 12 numpy dtypes (dtype‑erased), zero‑copy views; backs NPZ and mapped safetensors |
| `PointCloud` | `point_cloud` (new) | ✅ | xyz + rgb/rgb16 + normals + intensity, optional organized width/height and acquisition viewpoint, plus an optional validated lossless LAS waveform sidecar; backs `.xyz`, count-prefixed `.pts`, point `.ply`, PCD, plain `.las`, and `.laz` |
| `DepthMap` | `depth_map` | ✅ | scalar f32 depth + scale/unit/invalid + confidence; backs scalar DMB, explicit typed PFM/PNG/EXR adapters, and COLMAP MVS camera-Z/nonpositive depth |
| `NormalMap` | `normal_map` | ✅ record / ⬜ datatype | HxWx3 f32 camera-frame normals with explicit component/frame conventions; backs COLMAP MVS normal matrices |
| `ConsistencyGraph` | `consistency_graph` | ✅ record / ⬜ datatype | CSR pixel/image-index adjacency with explicit row/column and positional-index conventions; backs COLMAP MVS consistency graphs |
| `PointVisibility` | `point_visibility` | ✅ record / ⬜ datatype | CSR fused-point/image-index visibility with an explicit positional-index convention; backs COLMAP fused `.ply.vis` |
| `FlowField` | `flow` | ✅ | HxWx2 f32 vectors with component/axis/row/unit/invalid metadata; raw FLO API remains ndarray-compatible |
| `StateTrajectory` | `state_trajectory` | ✅ record / ⬜ datatype | exact int64 nanosecond timestamps plus float64 position, WXYZ orientation, velocity, gyro bias, and accelerometer bias; explicit frame/unit/sign metadata |
| `CameraRig` | `camera_rig` | ✅ record / ⬜ datatype | ordered cameras; ragged model parameters; exact optional K/R/P; extrinsic, ROI/binning, topic, and time-offset metadata with explicit conventions |
| `PoseGraph` | `pose_graph` | ✅ record / ⬜ datatype | ordered typed SE(3) nodes/edges, fixed-node flags, exact ids, XYZW transforms, and symmetric 6×6 information matrices with explicit direction/order metadata |
| `FeatureSet` | `feature_set` | ✅ record / ⬜ datatype | per-image id/name/camera/size/time; Nx{2,4,6} f32 keypoints; descriptors in u8/i8/f16/f32/f64 with dtype/dimension/name presence; optional RGB colors, quality, and scores |
| `MatchGraph` | `match_graph` | ✅ record / ⬜ datatype | canonical COLMAP image pairs and pair ids; ragged raw/verified u32 matches; optional parallel scores, provenance flags/retrieval score, F/E/H, config, relative pose, and recovered endpoint cameras |
| `ColmapDatabase` | `match_graph` | ✅ record / ⬜ datatype | cameras, prior-focal flags, ordered features, match graph, nested rig/frame, pose-prior, marker, metadata-only video, and ownership records; exact profile/application/schema identity |
| `ColmapRigFrameSet` | COLMAP DB companion | ✅ nested record | non-sentinel uint32 rig/frame/sensor IDs, uint64 data IDs/CSR offsets, WXYZ `sensor_from_rig`, SQL-NULL pose presence, and frame assignments; database frames intentionally carry no world pose |
| `ColmapPosePriorSet` | COLMAP DB companion | ✅ nested record | stock plus extended MAXX priors; nullable position/gravity and XYZW `cam_from_world` rotation; logical row-major 3x3/6x6 covariance with explicit variable-order and unit tags |
| `ColmapMarkerSet` | COLMAP DB companion | ✅ nested record | marker ids/labels/types, optional world positions/covariance, point links/enabled flags, and top-left pixel projections with pinned/point2D state |
| `ColmapVideoMetadataSet` | COLMAP DB companion | ✅ nested record | metadata-only source/frame rows; SQL NULL versus empty text, dimensions/count/rate/duration, PTS, and independent time IDs; paths are inert strings |
| `ColmapMaxxSchemaInfo` | COLMAP DB companion | ✅ nested record | exact schema/minimum-reader versions and producer version/commit; absent as `None` outside owned MAXX rows |
| `MaterialSet` | `material_set` | ✅ record / ⬜ datatype | metallic-roughness factors, alpha modes, URI texture references, UV sets, and sampler metadata; material names may be empty or repeated as glTF permits |
| `Mesh` | `mesh` | ✅ record / ⬜ datatype | polygon-preserving ragged topology; vertex/corner normals, UVs, RGBA; primitive/material domains; coordinate metadata and local transform |
| `MeshScene` | `mesh_scene` | ✅ record / ⬜ datatype | ordered mesh primitives, mesh-to-primitive ranges, shared materials, node hierarchy/local transforms, scene roots, names, and default scene |

## Formats (codecs)

### ✅ Implemented — original and self-contained codec spine

| Format id | Record | R/W | Oracle | Notes |
|---|---|---|---|---|
| `pfm` | ndarray (raw) + `DepthMap` (typed) | R+W | pure‑Python | gray/color raw API unchanged; explicit scalar typed-depth encoding, unit-magnitude header guard, bounded typed windows |
| `colmap_sparse` | `Reconstruction` | R+W | **pycolmap** | legacy three-file and modern five-file `.bin`; rigs/frames and camera models 0-17; byte-identical to pycolmap 4.1.1; bounded direct writer |
| `colmap_sparse_txt` | `Reconstruction` | R+W | **pycolmap** | legacy/modern text twin; rigs/frames; binary↔text value/byte differential |
| `gaussian_ply` | `GaussianCloud` | R+W | **gsply** | 3DGS Gaussian PLY, channel‑grouped f_rest |
| `compressed_ply` | `GaussianCloud` | R+W | pinned **PlayCanvas splat-transform 3.1.6** vector + pinned hosted macOS AppleClang/ARM parent fingerprint + NumPy oracle | SuperSplat chunked PLY; hosted Windows/MSVC and Ubuntu/glibc match PlayCanvas, while the characterized macOS profile differs at one lossy quantization boundary; exp/log rounding is the inferred cause; degree 0–3; bounded point reads |
| `sog` | `GaussianCloud` | R+W | pinned **PlayCanvas splat-transform 3.1.6** source + independent Pillow/NumPy/ZIP oracle + pinned musl/fdlibm `log1p` adaptation | SOG v2 bundled ZIP and unbundled directory; strict lossless-WebP layers; cross-platform deterministic metadata plus Morton/codebook/palette writer; degree 0–3; bounded point allocation |
| `ksplat` | `GaussianCloud` | R+W | pinned **GaussianSplats3D 0.4.7** vectors + independent struct/NumPy oracle | mkkellogg v0.1; compression levels 0–2; SH degrees 0–2; multi-section read; deterministic single-section bucketed writer; bounded point allocation |
| `spz` | `GaussianCloud` | R+W | **gsply** | v1/2/3 read, **v3+v4 write**, v4 read; bit‑exact v3 encode |
| `splat` | `GaussianCloud` | R+W | numpy oracle | antimatter15 blob; WXYZ+SH_C0 verified; lossy 8‑bit, SH‑drop |
| `transforms_json` | `PosedViewSet` | R+W | pure‑Python | NeRF/Instant‑NGP/Nerfstudio; records OpenGL c2w |
| `tum` | `PosedViewSet` | R+W | pure‑Python | TUM trajectory (xyzw, verbatim) |
| `kitti` | `PosedViewSet` | R+W | pure‑Python | KITTI 3×4 [R\|t] poses |
| `bundler` | `Reconstruction` | R+W | pycolmap | Bundler `.out` |
| `nvm` | `Reconstruction` | R+W | manual | VisualSFM `.nvm` (NVM_V3) |
| `openmvg` | `Reconstruction` | R+W | manual | openMVG `sfm_data.json` |
| `npy` | ndarray | R+W | **numpy** | pinned mapped native/C-order view; byte‑exact v1.0 writer (== np.save) |
| `npz` | `TensorDict` | R+W | **numpy** | ZIP (stored+deflate) via repository-contained miniz 3.0.2; 12 dtypes |
| `netpbm` | `Image` | R+W | pure‑Python | PGM P5/P2 + PPM P6/P3; 16‑bit big‑endian, comment‑tolerant |
| `.xyz` | `PointCloud` | R+W | pure‑Python | headerless point-cloud text (fast_float parsing) |
| `.pts` | `PointCloud` | R+W | independent parser | mandatory count header; XYZ/XYZI/XYZRGB/XYZIRGB; count validation |
| `.flo` | ndarray (raw) + `FlowField` (typed) | R+W | independent NumPy parser | raw API retains its pinned mapped view; `read_flow`/`write_flow`/`inspect_flow` attach and guard Middlebury semantics |

### ✅ Complete — image / point tier via **permissive native source** (no system libs)

Key reframing (proven out): most "needs a C lib" formats have permissive,
self-contained source libraries that drop into the existing pinned-source
native build pattern (miniz, zstd, nlohmann/json, fast_float) — so they needed **no vcpkg/conda
`SCENEIO_WITH_*` gate** and kept runtime numpy-only.

| Format | Record | Native backend (license) | Status |
|---|---|---|---|
| PNG (incl. 16‑bit depth) | `Image` (raw) + `DepthMap` (typed) | lodepng (zlib) — self‑contained inflate | ✅ R+W; raw palette/RGB/RGBA API unchanged; typed grayscale uint16 exact widening/guarded write with explicit encoding |
| JPEG (baseline+progressive) | `Image` | stb (public domain) | ✅ R (gray+RGB) / W (RGB‑only); pillow oracle; lossy |
| Radiance `.hdr` | `Image`(f32) | stb (public domain) | ✅ R+W; numpy RGBE oracle; lossy encode |
| OpenEXR | `Image`(f32) (raw) + `DepthMap` (typed) | tinyexr (BSD) — reuses our miniz | ✅ R+W; OpenEXR‑python oracle; HALF→FLOAT, premult‑alpha, PIZ/ZIP/RLE; explicit single-channel typed depth |
| plain `.las` | `PointCloud` | **none** — hand‑parsed binary, like colmap `.bin` | ✅ R+W; laspy oracle; formats 0‑10, origin+rgb16, georef rebase; formats 4/5/9/10 preserve internal waveform descriptor VLRs, packet EVLR, references, and opaque point fields in a sidecar |
| `.laz` | `PointCloud` | LAZperf 3.4.0 (Apache‑2.0/BSD‑3-Clause/BSD‑2-Clause) | ✅ R+W; laspy/lazrs oracle; formats 0‑3 and 6‑8, exact standard records, chunk-parallel decode and chunk-aware ranges, mmap, header inspect, seekable streaming sink; waveform, extra bytes, unrelated VLR/EVLR metadata, and COPC reject |
| WebP | `Image` | repository-contained libwebp 1.5.0 (BSD-3-Clause) — upstream SIMD CMake build, statically linked | ✅ R+W; Pillow oracle; lossless byte-exact + lossy; local-source build and strict benchmark clean on MSVC |

Cross‑cutting: the cibuildwheel dry run and tagged release both built and
smoke‑tested the abi3 wheels on Linux, macOS, and Windows. SceneIO 0.2.0 is
published on PyPI from the tag workflow; the repository-contained libwebp
source retains that wheel-build result. Vendored stb carries documented **local
hardening patches** for truncated HDR input, corrupt JPEG marker failure, and a
signed-shift UB in JPEG entropy output (see `stb/COMMIT.txt`). CMYK JPEG is
best‑effort stb→RGB and opaque RGBA collapses to RGB in WebP (both documented).

Genuinely need the system‑lib `SCENEIO_WITH_*` gate (deferred): HDF5 (+hloc),
TIFF (libtiff). **LAZ is statically built from repository-contained LAZperf
3.4.0 source** (Apache‑2.0/BSD‑3-Clause/BSD‑2-Clause), with formats 0‑3 and
6‑8 in its supported compression set. COLMAP DB `.db` is covered by a pinned
public-domain SQLite amalgamation statically linked into `_core`.

### ✅ Post-0.2 self-contained expansion

| Format id | Record | R/W | Oracle | Notes |
|---|---|---|---|---|
| `safetensors` | `TensorDict` | R+W | **safetensors.numpy 0.8** | deterministic canonical writer; all 12 TensorDict dtypes; string metadata; read-only mmap views; named-tensor and leading-axis slice reads |
| `dmb` | `DepthMap` | R+W | independent NumPy parser | scalar Gipuma DMB float32 depth; exact little-endian payload; unknown scale; zero-invalid; bounded windows; **not** COLMAP's `width&height&depth&` MVS matrix |
| `colmap_mvs_depth` | `DepthMap` | R+W | independent `struct`/NumPy parser | COLMAP `width&height&1&` header plus planar little-endian f32 camera-Z depth; nonpositive-invalid; bounded windows |
| `colmap_mvs_normal` | `NormalMap` | R+W | independent `struct`/NumPy parser | COLMAP `width&height&3&` header plus planar little-endian f32 camera-frame XYZ normals; bounded windows |
| `colmap_mvs_consistency` | `ConsistencyGraph` | R+W | independent `struct` parser | repeated signed-int32 column, row, count, and positional image-index lists; strict full-payload consumption |
| `colmap_fused_visibility` | `PointVisibility` | R+W | independent `struct` parser | repeated little-endian uint32 count plus positional image indices; exact companion for `fused.ply.vis` |
| `bal` | `Reconstruction` | R+W | UW BAL specification + independent parser | zero-based observations; angle-axis cameras with focal and two radial terms; explicit BAL↔SceneIO frame transform; strict canonical writer |
| `bmp` | `Image` | R+W | **Pillow** + Microsoft DIB specification | Windows V3/V4/V5 BI_RGB/BI_BITFIELDS; palette and packed-16 reads; top/bottom orientation; deterministic RGB/RGBA writers |
| `tga` | `Image` | R+W | **Pillow** + Truevision 2.0 specification | grayscale/RGB/RGBA and zero-origin palettes; raw/RLE; top/bottom orientation; deterministic RLE writer |
| `ply` | `PointCloud` | R+W | independent NumPy/stdlib parser + **Open3D 0.19** | ASCII and binary LE/BE; all standard scalar input types; exact rgb8/rgb16; schema-aware Gaussian/point/mesh dispatch; binary point ranges |
| `ply_mesh` | `Mesh` | R+W | independent struct/NumPy oracle | polygon-preserving ASCII and binary LE/BE; vertex/corner normals, UVs, RGBA; primitive/material ranges; coordinate metadata and local transforms |
| `obj` | `Mesh` + `MaterialSet` | R+W | pinned **TinyObjLoader** + **trimesh 4** | polygon-preserving independent indices; vertex/corner normals and UVs; RGB8, object/group/smoothing domains; strict single-library MTL factors and texture maps; adjacent paired OBJ/MTL output |
| `stl` | `Mesh` | R+W | independent `struct`/text parsers + **trimesh 4** | strict binary LE and ASCII; canonical unwelded triangle soup; facet normals; bounded face ranges; ambiguous facet attributes/colors reject |
| `off` | `Mesh` | R+W | independent token parser + **trimesh 4** | strict record-per-line (1 MiB cap) polygon-preserving ASCII OFF/NOFF/COFF/ST variants; exact vertex normals, UVs, and RGBA8; bounded face ranges |
| `gltf` | `MeshScene` | R+W | **pygltflib 1.16** + **trimesh 4** | glTF 2.0 JSON with mapped external or base64 data buffers; strided/sparse accessors, triangle primitives, nodes/scenes, metallic-roughness materials, and URI images; mesh/primitive selectors; atomic paired `.gltf` + `.bin` sink |
| `glb` | `MeshScene` | R+W | **pygltflib 1.16** + **trimesh 4** | GLB 2.0 with embedded BIN; same canonical scene/material subset and selectors as `gltf`; single-file mmap and direct sink |
| `pcd` | `PointCloud` | R+W | independent NumPy/stdlib parser + **Open3D 0.19** | PCD 0.7 ASCII, little-endian binary, and LZF `binary_compressed`; organized dimensions and viewpoint; packed RGB/intensity; bounded binary point ranges |
| `euroc_state` | `StateTrajectory` | R+W | independent stdlib CSV parser + EuRoC schema | exact int64-ns timestamps; p/q(WXYZ)/v/gyro-bias/accel-bias; canonical-header detection; bounded state ranges |
| `opencv_yaml` / `opencv_xml` | `CameraRig` | R+W | **PyYAML** / stdlib ElementTree | exact K/D plus optional R/P; schema-signature detection; generic YAML/XML extensions intentionally unclaimed |
| `ros_camera_info` | `CameraRig` | R+W | **PyYAML** + ROS CameraInfo schema | exact K/D/R/P, distortion model, binning, ROI, and rectify flag |
| `kalibr` | `CameraRig` | R+W | **PyYAML** + Kalibr schema | pinhole/omni intrinsics, distortion, topics, camera-chain or IMU extrinsics, and camera↔IMU time offsets |
| `g2o` | `PoseGraph` | R+W | independent strict parser + g2o BSD-3 source semantics | `VERTEX_SE3:QUAT`, `EDGE_SE3:QUAT`, `FIX`; XYZW; exact upper-triangle information; unsupported mixed types/parameters reject |
| `colmap_db` | `ColmapDatabase` (`FeatureSet` + `MatchGraph` + nested companions) | inspect, R+W all four exact profiles, partial | stdlib **sqlite3** + **pycolmap 4.1.1** | exact structural identity and selected-profile writes for stock 3.13/4.1.1/current and owned MAXX; decoded exact records preserve their profile through public writes, while constructed core records retain the hybrid compatibility route; stock rig/frame/prior, current recovered cameras, and MAXX descriptors/colors/scores/provenance/quality/extended priors/markers/metadata-only video/ownership round-trip; conversion reports enumerate identity changes and incompatible fields before destination access; migration-derived pre-ownership databases remain legacy/unknown and are a C4 classification item |
| `laz` | `PointCloud` | R+W | **laspy 2.7 + lazrs 0.8.1** | pinned LAZperf 3.4.0; standard formats 0–3/6–8; strict LASzip VLR/chunk extents; chunk-aware ranges; seekable streaming sink |
| `image_sequence` | `ImageSequence` | R+W | independent manifest/PGM fixtures + existing image-codec parity suites | flat image directories; deterministic natural order or strict versioned manifest; lazy owned paths; exact optional timing; heterogeneous frames reject; transactional bounded-copy writer; frame ranges |
| `y4m` | `ImageSequence` | R+W | independent Python parser/writer + exact golden bytes | original dependency-free YUV4MPEG2 subset; uint8 mono/4:2:0/4:2:2/4:4:4 planar frames, odd dimensions, exact rational timing, mmap, streaming sink, inspect, and frame ranges; no RGB conversion or video-framework dependency |

### Repository-owned COLMAP workflow adapters

The 54-codec registry is unchanged. The lazy `sceneio.colmap` namespace adds
repository-owned read/write adapters for fork sparse companions, MappingInput
v1/v2, MegaLoc artifact directories, rig JSON, SIFT text, stock and dense
image-pair text (including positional cap rows), feature-match blocks, and
Sim3 text. MappingInput and MegaLoc numeric payloads use read-only mappings;
large companion reads avoid whole-file Python copies, and writers stream
through atomic replacement. See
[`colmap_adapters.md`](colmap_adapters.md) for the public API and
[`colmap_ecosystem_coverage.md`](colmap_ecosystem_coverage.md) for the exact
closure matrix.

The corrected local closure gate collects 3,879 tests and passes 3,874 with
five documented optional/platform skips. The prior 38-test adapter suite and
131-test focused gate remain green; the 132-test
SOG/MVS/catalog/architecture correction sweep, final 143-test architecture
review sweep, installed-wheel smoke, Ruff, and diff checks also pass. Three
independent architecture, correctness/test, and platform/documentation
reviews signed off. Exact-pushed-tree automatic and nonpublishing MSVC/GCC
10/AppleClang package validation remain active.

Encoded image paths and model paths remain opaque values. TIFF plus embedded
or standalone `.xmp` metadata are optional generic format/metadata work, not
requirements for COLMAP ecosystem closure.

### ⬜ Pending — declared roadmap gaps

- Sequence/dataset: animated WebP, APNG, and RTMV.
- Optional scientific/container: HDF5, hloc feature/match layouts, TIFF, E57,
  and Parquet/Arrow.
- Chunked/heavyweight: Zarr v2/v3, USD/USDZ, and OpenVDB.
- Policy-gated: AVIF, JPEG-XL, and Draco-compressed glTF. These do not enter
  implementation without an explicit decision under the patented-codec rule.

Draco-compressed glTF remains policy-gated. Plain glTF/GLB is implemented and
rejects Draco, meshopt, unknown extensions, and unrepresented scene features
rather than silently flattening or dropping them.

### 🟡 In progress — Phase 7 (reliability and performance)
✅ mmap-backed reads for all buffer-backed file codecs plus paired OBJ/MTL and
glTF/external-buffer mappings (SOG additionally supports an unbundled native
multi-file path; COLMAP DB and the two COLMAP directory codecs read paths
directly in native code) · ✅
zero-copy read-only mapped
ndarray views for native NPY/FLO payloads (PFM row-flips into owned storage) · ✅ bytes/mmap differential +
three-case push backing-store mutation sweep, with a 100-case default-branch
schedule retained · ✅ compiler-instrumented native reliability workflow passes
its complete and focused jobs at `a5e7fa4` · ⬜ randomized oracle-triangulated
fuzzing · ✅ direct file-sink writes · ✅ bounded measured-path workers
(XYZ/LAS/LAZ/EXR/PNG16/WebP lossless) · ✅ partial/lazy reads (`inspect` covers all
54; bounded pixel/point/face/mesh/primitive/state/frame/COLMAP-image/COLMAP-pair/tensor
subsets cover capable containers) · ⬜ GPU-via-DLPack (torch-cuda/cupy) · ✅
expanded 54-codec benchmark/oracles.

## Infrastructure & capabilities

| Piece | Status | Notes |
|---|---|---|
| nanobind + scikit‑build‑core build | ✅ | abi3/cp312, `NB_STATIC`; `Python::SABIModule`, `nanobind-static-abi3`, and the platform suffix are configure-checked; local Windows emits `_core.pyd` against `python3.dll`, Ubuntu emits `_core.abi3.so` without libpython |
| cibuildwheel release path | ✅ | one verified sdist feeds Linux/macOS/Windows wheels; locked build inputs, all-50 installed smoke, per-wheel inventory, and tag-only publication in `publish.yml`; final build-only run `30406706115` and downloaded-artifact inspection pass, while tagging and publication remain user-gated |
| CI parity (oracles in CI) | ✅ | At `a5e7fa4`, normal Linux CI passes 2,914 tests with nine documented platform/oracle skips, the 50-codec performance guard, pinned GCC 10 portability, and the three-OS focused matrix |
| Codec registry + `read`/`write`/`inspect`/`read_partial`/`detect` | ✅ | inspection covers all 54; bounded partial hooks are capability-specific |
| Repo-maintained stable codec adapters | ✅ | all 54 production adapters, grammars, convention guards, inspectors, partial capability policies/available paths, and sinks live in `src/cpp` / `src/sceneio`; separately installed implementations and executables are test/reference oracles only |
| Offline native-source closure | ✅ | all selected native sources—including libwebp 1.5.0—are stored in-tree and the production CMake graph has no native-source fetch; local exact-tree proof plus final MSVC, GCC 10, and AppleClang sdist-to-wheel execution and artifact inspection pass |
| Zero‑copy numpy + torch (DLPack) | ✅ | validated per codec |
| Conventions‑as‑metadata + write guards | ✅ | record‑don't‑convert enforced |
| Parity kit (`sceneio.testing.parity`) | ✅ | cross‑impl + round‑trip + convention pins |
| In-tree native dependencies | ✅ | all selected production dependencies are permissive, pinned, source-manifested, and license-indexed |
| Image libraries | ✅ | lodepng, stb, tinyexr, and libwebp 1.5.0 are repository-contained and statically built |
| Feature‑flagged optional C libs (`SCENEIO_WITH_*`) | ⬜ | planned for HDF5, TIFF, E57, Arrow, USD, and OpenVDB; LAZ instead uses pinned, statically built LAZperf in the default tier |
| mmap / streaming sources | ✅ | mmap reads + raw NPY/FLO views + direct file-sink writes complete |
| Bounded intra-file workers | ✅ | measured O4 paths; deterministic one-vs-many lane tests |
| Instrumented + mmap differential CI | ✅ | at `a5e7fa4`, exact 2,923-test collection, complete compiler-instrumented suite, focused native lifetime controls, and the three-case push backing-store sweep pass; the retained default-branch schedule raises that sweep to 100 cases |
| Capability flags (`reads/writes/inspect/partial/streams/lossy/needs_dep`) | ✅ | frozen metadata through `sceneio.capabilities()`; snapshot below is CI-validated |
| `splat` / `posed_views` DataTypes in the vocabulary | ⬜ | **Phase‑C** (wire identity; cross‑repo) |

<!-- sceneio-capabilities:start -->
### Registry capability snapshot

This table is generated conceptually from `sceneio.capabilities()` and checked
byte-for-byte against the live registry by `tests/test_io_capabilities.py`.
Streaming means the public path avoids a whole-file/output-sized Python
`bytes`; it does not imply that the underlying compression algorithm is
incremental.

| Format id | Container | Read | Write | Inspect | Partial selectors | Stream read | Stream write | Lossy-capable | Native feature |
|---|---|---|---|---|---|---|---|---|---|
<!-- sceneio-capability-rows:start -->
| `bal` | file | yes | yes | yes | - | yes | yes | no | - |
| `bmp` | file | yes | yes | yes | - | yes | yes | no | - |
| `bundler` | file | yes | yes | yes | - | yes | yes | no | - |
| `colmap_db` | file | yes | yes | yes | image_id, pair | yes | yes | no | - |
| `colmap_fused_visibility` | file | yes | yes | yes | - | yes | yes | no | - |
| `colmap_mvs_consistency` | file | yes | yes | yes | - | yes | yes | no | - |
| `colmap_mvs_depth` | file | yes | yes | yes | window | yes | yes | no | - |
| `colmap_mvs_normal` | file | yes | yes | yes | window | yes | yes | no | - |
| `colmap_sparse` | directory | yes | yes | yes | image_id | yes | yes | no | - |
| `colmap_sparse_txt` | directory | yes | yes | yes | image_id | yes | yes | no | - |
| `compressed_ply` | file | yes | yes | yes | points | yes | yes | yes | - |
| `dmb` | file | yes | yes | yes | window | yes | yes | no | - |
| `euroc_state` | file | yes | yes | yes | states | yes | yes | no | - |
| `exr` | file | yes | yes | yes | - | yes | yes | no | - |
| `flo` | file | yes | yes | yes | window | yes | yes | no | - |
| `g2o` | file | yes | yes | yes | - | yes | yes | no | - |
| `gaussian_ply` | file | yes | yes | yes | points | yes | yes | no | - |
| `glb` | file | yes | yes | yes | mesh_id, primitive_id | yes | yes | no | - |
| `gltf` | multi_file | yes | yes | yes | mesh_id, primitive_id | yes | yes | no | - |
| `hdr` | file | yes | yes | yes | - | yes | yes | yes | - |
| `image_sequence` | directory | yes | yes | yes | frames | yes | yes | no | - |
| `jpeg` | file | yes | yes | yes | - | yes | yes | yes | - |
| `kalibr` | file | yes | yes | yes | - | yes | yes | no | - |
| `kitti` | file | yes | yes | yes | - | yes | yes | no | - |
| `ksplat` | file | yes | yes | yes | points | yes | yes | yes | - |
| `las` | file | yes | yes | yes | points | yes | yes | yes | - |
| `laz` | file | yes | yes | yes | points | yes | yes | yes | - |
| `netpbm` | file | yes | yes | yes | window | yes | yes | no | - |
| `npy` | file | yes | yes | yes | - | yes | yes | no | - |
| `npz` | file | yes | yes | yes | - | yes | yes | no | - |
| `nvm` | file | yes | yes | yes | - | yes | yes | no | - |
| `obj` | multi_file | yes | yes | yes | - | yes | yes | no | - |
| `off` | file | yes | yes | yes | faces | yes | yes | no | - |
| `opencv_xml` | file | yes | yes | yes | - | yes | yes | no | - |
| `opencv_yaml` | file | yes | yes | yes | - | yes | yes | no | - |
| `openmvg` | file | yes | yes | yes | - | yes | yes | no | - |
| `pcd` | file | yes | yes | yes | points | yes | yes | no | - |
| `pfm` | file | yes | yes | yes | window | yes | yes | no | - |
| `ply` | file | yes | yes | yes | points | yes | yes | no | - |
| `ply_mesh` | file | yes | yes | yes | faces | yes | yes | no | - |
| `png` | file | yes | yes | yes | - | yes | yes | no | - |
| `pts` | file | yes | yes | yes | points | yes | yes | no | - |
| `ros_camera_info` | file | yes | yes | yes | - | yes | yes | no | - |
| `safetensors` | file | yes | yes | yes | tensors, slices | yes | yes | no | - |
| `sog` | multi_file | yes | yes | yes | points | yes | yes | yes | - |
| `splat` | file | yes | yes | yes | points | yes | yes | yes | - |
| `spz` | file | yes | yes | yes | - | yes | yes | yes | - |
| `stl` | file | yes | yes | yes | faces | yes | yes | no | - |
| `tga` | file | yes | yes | yes | - | yes | yes | no | - |
| `transforms_json` | file | yes | yes | yes | - | yes | yes | no | - |
| `tum` | file | yes | yes | yes | - | yes | yes | no | - |
| `webp` | file | yes | yes | yes | window | yes | yes | yes | - |
| `xyz` | file | yes | yes | yes | points | yes | yes | no | - |
| `y4m` | file | yes | yes | yes | frames | yes | yes | no | - |
<!-- sceneio-capability-rows:end -->

Supported and intentionally unsupported subfeatures, such as LAS point formats
or WebP animation/window behavior, are carried by each immutable capability
record rather than expanded into this summary.
<!-- sceneio-capabilities:end -->

<!-- sceneio-native-features:start -->
### Optional native-feature manifest

`sceneio.native_features()` reports build-time integrations even when they are
not compiled into the current extension. The table is checked byte-for-byte
against that public manifest.

| Feature | CMake option | Compiled | Planned format ids |
|---|---|---|---|
<!-- sceneio-native-feature-rows:start -->
| `arrow` | `SCENEIO_WITH_ARROW` | no | `parquet` |
| `avif` | `SCENEIO_WITH_AVIF` | no | `avif` |
| `draco` | `SCENEIO_WITH_DRACO` | no | `gltf`, `glb` |
| `e57` | `SCENEIO_WITH_E57` | no | `e57` |
| `hdf5` | `SCENEIO_WITH_HDF5` | no | `hdf5`, `hloc_features`, `hloc_matches` |
| `jxl` | `SCENEIO_WITH_JXL` | no | `jpeg_xl` |
| `openvdb` | `SCENEIO_WITH_OPENVDB` | no | `openvdb` |
| `tiff` | `SCENEIO_WITH_TIFF` | no | `tiff` |
| `usd` | `SCENEIO_WITH_USD` | no | `usd`, `usdz` |
<!-- sceneio-native-feature-rows:end -->

An unknown feature name raises the same normalized `FormatError` family used
by codec discovery. Future feature-enabled builds must export their compiled
names from `_core.__native_features__`.
<!-- sceneio-native-features:end -->

## Partial-read capability

`sceneio.read_partial` exposes only measured bounded paths:

| Selector | Formats | Result |
|---|---|---|
| pixel `window=(r0,r1,c0,c1)` | PFM, binary P5/P6 Netpbm, lossless VP8L WebP, FLO, scalar DMB, COLMAP MVS depth/normal | ndarray, `Image`, `DepthMap`, or `NormalMap`, matching the full-read slice with metadata preserved |
| point range `points=(start,stop)` | XYZ, PTS, binary generic PLY, uncompressed binary PCD, LAS, Gaussian PLY, compressed PLY, SOG, KSplat, SPLAT | `PointCloud` / `GaussianCloud`, with convention metadata preserved |
| face range `faces=(start,stop)` | generic mesh PLY, STL, OFF | `Mesh`; PLY/OFF retain the complete vertex domain, while STL returns local canonical triangle soup |
| state range `states=(start,stop)` | EuRoC state CSV | `StateTrajectory` with convention metadata preserved |
| frame range `frames=(start,stop)` | image directories, raw Y4M | `ImageSequence`; directory frames remain lazy encoded paths and Y4M copies only selected planar frames |
| `image_id` | COLMAP binary + text | one-image `Reconstruction` plus every camera required by its retained modern rig/frame (or its one legacy camera); no point-container read |
| `image_id` | COLMAP SQLite database | one compiled `FeatureSet`; unrelated keypoint/descriptor BLOBs remain unread |
| unordered `pair=(image_id1,image_id2)` | COLMAP SQLite database | one compiled `MatchGraph` with raw/verified matches and optional geometry |
| `tensors=(...)` | safetensors | selected complete tensors as a mapped `TensorDict`; other payload pages remain untouched |
| `slices={name: (start, stop)}` | safetensors | contiguous leading-axis slices as a mapped `TensorDict` |

PNG, JPEG, HDR, EXR, SPZ, ASCII point-cloud PLY, ASCII/compressed PCD, and other compressed/scene containers intentionally
do not advertise a partial hook when their current decoder would still
materialize the complete payload. ASCII P2/P3 Netpbm rejects because it must
token-decode the complete raster; lossy VP8 rejects because a crop-local decode
cannot promise bit-exact parity with the full decoder's chroma context.
