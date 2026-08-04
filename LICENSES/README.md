# Licenses and attributions

SceneIO itself is licensed under Apache-2.0; the complete project license is
in the repository-root [`LICENSE`](../LICENSE) file. This directory contains
the notices that must accompany third-party code compiled into
`sceneio._core`, copied beside it, or generated into a distribution artifact.

The table is the distribution inventory. Versions are the exact versions or
commits selected by the CMake dependency and qualification modules, vendored
`COMMIT.txt` files, and pinned release tooling.
Where an upstream project offers multiple permissive licenses, the
redistribution choice used by SceneIO is stated explicitly.

| Component | Version or pin | How it is shipped | License used here | Notice |
|---|---|---|---|---|
| nanobind | build requirement `>=2.4` (2.13.0 locally validated) | statically linked binding runtime | BSD-3-Clause | [nanobind.txt](nanobind.txt) |
| delvewheel | 1.13.0 | generates the DLL-loading bootstrap in the repaired Windows wheel; the exact-output verifier fixture is included in the sdist | MIT | [delvewheel.txt](delvewheel.txt) |
| Microsoft Visual C++ runtime | Visual Studio 2022 v143 x64 redistributable selected by `repair_windows_wheel.py` | unmodified `msvcp140.dll` sidecar in the Windows wheel when required by `_core.pyd` | applicable Visual Studio 2022 Distributable Code terms and REDIST list; platform-toolchain exception to the open-source codec policy | [redistribution notice and official terms](microsoft-vc-runtime.txt) |
| miniz | 3.0.2, commit `293d4db1b7d0ffee9756d035b9ac6f7431ef8492` | vendored and statically linked | MIT | [top-level license](miniz.txt), [ZIP implementation notice](miniz-zip.txt) |
| nlohmann/json | 3.11.3, commit `9cca280a4d0ccf0c08f47a99aa71d1b0e52f8d03` | vendored compiled header-only code | MIT; C++11-only Abseil fallback is Apache-2.0 | [top-level license](nlohmann-json.txt), [selected-source attribution](nlohmann-json-source.txt) |
| Zstandard | 1.5.6, commit `794ea1b0afca0f020f4e57b6732332231fb23c70` | vendored and statically linked | BSD-3-Clause; selected libdivsufsort and build-helper code use MIT-compatible terms | [top-level license](zstd.txt), [selected-source attribution](zstd-source.txt) |
| fast_float | 6.1.6, commit `00c8c7b0d5c722d2212568d915a39ea73b08b973` | vendored compiled header-only code | MIT option | [fast-float.txt](fast-float.txt) |
| LAZperf | 3.4.0, commit `b7bbe26109dc986f42d4fc80b8de3d2b6ca634ce` | vendored and statically linked | Apache-2.0, BSD-3-Clause, BSD-2-Clause; portable endian header is public domain with BSD/MIT/Apache fallback | [top-level license](lazperf.txt), [selected-source attribution](lazperf-source.txt) |
| LodePNG | version 20260119, commit `ed6fe5825c6a4fbb7f58ab35a4231c7543cd452a` | vendored and statically linked | zlib | [lodepng.txt](lodepng.txt) |
| SQLite | 3.53.4 amalgamation | vendored and statically linked | public domain | [sqlite.txt](sqlite.txt) |
| libwebp | 1.5.0, commit `a4d7a715337ded4451fec90ff8ce79728e04126c` | vendored and statically linked core libraries for WebP, animated WebP, and the bounded WebM/V_VP8 all-keyframe profile | BSD-3-Clause with upstream additional patent grant | [license](libwebp.txt), [patent grant](libwebp-patents.txt) |
| libvpx | `v1.16.0-178-g4780fac96`, commit `4780fac9612992f8584227ea508c298fe8c01d05` | compact portable source closure, vendored and statically linked for temporal VP8/VP9 WebM encode/decode | BSD-3-Clause with upstream additional WebM patent grant | [license](libvpx.txt), [patent grant](libvpx-patents.txt) |
| Chromium libvpx build metadata | Chromium commit `d3345aa1656fdfce4861a2d7080cac649d45e814` | selected generated generic source list/configuration material used to define the libvpx closure; no Chromium runtime is bundled | BSD-3-Clause | [chromium.txt](chromium.txt) |
| libogg | 1.3.6, commit `be05b13e98b048f0b5a0f5fa8ce514d56db5f822` | vendored and statically linked Ogg framing library for the bounded Theora profile | BSD-3-Clause | [ogg.txt](ogg.txt) |
| libtheora | 1.2.0, commit `8e4808736e9c181b971306cc3f05df9e61354004` | vendored and statically linked Theora encoder/decoder | BSD-3-Clause | [theora.txt](theora.txt) |
| musl fdlibm-derived `log1p` | musl 1.2.5, commit `0784374d561435f7c787a555aeab8ede699ed298` | private header adaptation used for deterministic SOG metadata; no musl library is linked | original Sun permission notice; musl project MIT | [musl-log1p.txt](musl-log1p.txt) |
| libjpeg-turbo | 3.2.0, commit `c85e6b905bf237038faa936dab160ebfc5da0344` | statically linked only in explicit JPEG qualification builds until selected | IJG, BSD-3-Clause, zlib | [libjpeg-turbo.txt](libjpeg-turbo.txt), [upstream `README.ijg` copy](libjpeg-turbo-IJG.txt) |
| stb_image / stb_image_write | commit `31c1ad37456438565541f4919958214b6e762fb4` | vendored compiled headers | MIT option | [stb.txt](stb.txt) |
| TinyEXR | commit `1b106618644dbf8a0935c2348ba51a2d863dd7c2` | vendored compiled headers | BSD-3-Clause | [tinyexr.txt](tinyexr.txt) |
| tinyobjloader | commit `45636bdcef1a4fec140346b90c0b50bf0bc3e23b` | vendored compiled header | MIT; bundled earcut ISC; bundled fast_float under MIT | [tinyobjloader.txt](tinyobjloader.txt), [fast-float.txt](fast-float.txt) |
| cgltf | 1.15, commit `360db1a95480fe102ae9c69b27c5d101167ff5ba` | vendored compiled headers | MIT; bundled jsmn MIT | [cgltf.txt](cgltf.txt) |
| COLMAP persisted formats | upstream schema/format references pinned at `0b31f98133b470eae62811b557dc2bcff1e4f9a5` (3.13.0), `a0d785fba74b2664f31edc4a29026a8b27c00f67` (4.1.1), and `64805cb870b574a569dccc34918d95a2db2b2fee` (current-main snapshot); OpsiClear database/dense reference pinned at `de15b08a2dba98b55d6ddfb7cedac147838afbb4` and compact-adapter reference pinned at `a3cfdd784d16a493878877f445fd1e27333fd8fc` | independently implemented sparse/database/dense codecs plus workspace, extended-sidecar, MappingInput, MegaLoc, rig, SIFT, pair/match, and Sim3 adapters; no COLMAP library is linked or bundled | BSD-3-Clause for upstream COLMAP formats; SceneIO implementation Apache-2.0 | [COLMAP notice](colmap.txt), [OpsiClear compatibility authorization record](opsiclear-colmap-mod.txt) |
| h5py | optional dependency `>=3.11` (3.16.0 locally validated) | separately installed optional HDF5 provider; not bundled in SceneIO distributions | BSD-3-Clause | [h5py.txt](h5py.txt) |
| SciPy | test extra `==1.18.0`, release commit `7adb8c972443f664b9395a0e6e8e0283e9b4faff` | separately installed mathematical conversion oracle; never imported by the NumPy-only runtime and not bundled in wheels | BSD-3-Clause | [scipy.txt](scipy.txt) |
| PyYAML | test extra `==6.0.3`, release commit `49790e73684bebad1df05ef8d828fa12f685bffb` | separately installed YAML syntax oracle for calibration and EuRoC/ASL fixtures; never imported by the NumPy-only runtime and not bundled in wheels | MIT | [pyyaml.txt](pyyaml.txt) |
| Google Research Kubric | revision `61f2422c84bab75006df33c6989e0b483db3ccfe` | deterministic label-map generator semantics and compact hand-evaluated test outputs only; Kubric/Blender are not installed or bundled | Apache-2.0 | [kubric.txt](kubric.txt) |
| HDF5 | provider version selected by the separately installed h5py distribution | used through h5py; not bundled or linked into SceneIO distributions | permissive HDF5 license | [hdf5.txt](hdf5.txt) |
| Zarr Python | optional dependency `>=3.1,<4` (3.2.1 locally validated) | separately installed optimized Zarr v2/v3 provider; not bundled in SceneIO distributions | MIT | [zarr.txt](zarr.txt) |
| numcodecs | version selected by the separately installed Zarr distribution (0.16.5 locally validated) | separately installed compiled chunk-codec provider used by Zarr; not bundled in SceneIO distributions | MIT top-level terms; individual bundled codecs retain their upstream permissive terms in the provider distribution | [numcodecs.txt](numcodecs.txt) |
| NVIDIA NCore | source revision `12f4429522c98356c5a46eee1d84f29bd846e367` | format specification/oracle and source of the adapted indexed-tar constants/algorithm; the upstream package is not a runtime dependency | Apache-2.0 | [ncore.txt](ncore.txt) |
| cbor2 | optional dependency `>=5.6,<6` | separately installed CBOR provider for NCore indexed-tar metadata; not bundled in SceneIO distributions | MIT | [cbor2.txt](cbor2.txt) |
| tifffile | optional dependency `>=2025.5` (2026.7.14 locally validated) | separately installed optimized TIFF provider; not bundled in SceneIO distributions | BSD-3-Clause | [tifffile.txt](tifffile.txt) |
| pye57 | optional dependency `>=0.4.18,<0.5` (0.4.19 locally validated) | separately installed E57 provider; not bundled in SceneIO distributions | MIT | [pye57.txt](pye57.txt) |
| libE57Format | version selected by the separately installed pye57 wheel | compiled into the separately installed pye57 provider; not bundled in SceneIO distributions | Boost Software License 1.0 | [libe57format.txt](libe57format.txt) |
| pyquaternion | version selected by pye57 (0.9.9 locally validated) | separately installed pye57 runtime dependency; not bundled in SceneIO distributions | MIT | [pyquaternion.txt](pyquaternion.txt) |
| Apache Xerces-C++ | provider version selected by the separately installed pye57 wheel (3.2 series locally validated) | shared library inside the separately installed pye57 provider; not bundled in SceneIO distributions | Apache-2.0 | [notice](xerces-c-notice.txt), [complete Apache-2.0 terms](apache-arrow-license.txt) |
| Apache Arrow / PyArrow | optional dependency `>=18,<24` (23.0.1 locally validated) | separately installed optimized Parquet and Arrow IPC provider; not bundled in SceneIO distributions | Apache-2.0 | [license](apache-arrow-license.txt), [notice](apache-arrow-notice.txt) |
| TinyVDB | optional dependency `>=0.9,<1` (0.9.0 locally validated) | separately installed OpenVDB provider; not bundled in SceneIO distributions; one upstream float-grid seed is packaged and fully replaced during writes | Apache-2.0 | [tinyvdb.txt](tinyvdb.txt), [seed provenance](../src/sceneio/io/_assets/openvdb_float_template.PROVENANCE.txt) |
| TinyUSDZ | optional dependency `>=0.9.4,<1` (0.9.4 locally validated) | separately installed USD/USDA/USDC/USDZ parser used with SceneIO's repository-owned USDA/USDZ writer; not bundled in SceneIO distributions; its published Linux x86-64 binary has a manylinux 2.27/2.28 floor independent of SceneIO's manylinux2014 base wheel | Apache-2.0 with permissively licensed bundled components documented upstream | [tinyusdz.txt](tinyusdz.txt) |
| AOUSD Core Specification Supplemental | release `1.0.1.post0`, tag object `404e2bde49c1`, peeled commit `c15ae0cad3ed` | one unmodified crate-10 time-sample fixture is base64-embedded in the test source and included in source distributions, not wheels | Apache-2.0 | [fixture attribution](aousd-core-spec-supplemental.txt); complete terms in the root `LICENSE` |
| PlayCanvas splat-transform | npm 3.1.6, gitHead `04b6d15b3c895136d2deba57fdb06df1d4ff3b91`; captured-reference revision `6b07ba05d731eac1163ad4ff1b14e47e5e3f162c`; exact test closure retained in `tools/splat-transform-oracle/package-lock.json` | separately installed executable oracle in splat CI; captured outputs appear in source tests; not bundled in distributions | MIT; locked transitive test packages declare ISC, MIT, or BSD-3-Clause | [splat-transform.txt](splat-transform.txt) |
| gsply | 0.4.6, commit `363885c707d445ce5d925024e2ab536fc72c1b9d` | separately installed Gaussian PLY/SPZ executable oracle; not bundled in distributions | MIT | [gsply.txt](gsply.txt) |
| GaussianSplats3D | 0.4.7, commit `eb2fc4593e3ea5e75388296fcdde2459542d1290` | generated KSplat vectors retained in source tests; upstream runtime not bundled | MIT | [gaussian-splats-3d.txt](gaussian-splats-3d.txt) |
| Niantic SPZ | 3.0.0, revision `5bf2945de1a003cee07133b1e495fe9c6ffdc7e7` | separately installed focused SPZ oracle in the hosted qualification lane; not bundled | MIT | [niantic-spz.txt](niantic-spz.txt) |
| Large-file benchmark sources | pinned Niantic SPZ, PDAL Autzen, Khronos BoxVertexColors, and TUM RGB-D trajectory assets; exact revisions and SHA-256 digests are in `bench/data/large_io_sources.toml` | downloaded only into ignored local benchmark storage; no source asset is tracked or distributed | MIT, CC-BY-4.0, and CC0-1.0 as applicable | [source attribution](large-io-benchmark-sources.txt) |
| Pixar OpenUSD | 26.08, revision `ee47c679abde5b467a7b6a41f3b2285564a4222e` | separately installed focused USD Gaussian oracle; no `pxr` module or OpenUSD code in runtime wheels | TOST-1.0 | [openusd.txt](openusd.txt) |
| gsplat | 1.5.3, commit `937e29912570c372bed6747a5c9bf85fed877bae` | covariance/SH/rendering semantic reference only; not installed or bundled | Apache-2.0 | [gsplat.txt](gsplat.txt); complete terms in root `LICENSE` |
| Brush | 0.3.0, commit `3edecbb2fe79d3e2c87eeab85b15e0b1dd10d486` | independent PLY consumer/rendering semantic reference only; not installed or bundled | Apache-2.0 | [brush.txt](brush.txt); complete terms in root `LICENSE` |
| Pillow | optional dependency `>=12.3,<12.4` (12.3.0 locally validated) | separately installed AVIF provider; not bundled in SceneIO distributions; the minor line is bounded because mapped reads use its tested private buffer entry | MIT-CMU | [pillow.txt](pillow.txt) |
| libavif | 1.4.2 in the locally validated Pillow 12.3.0 wheel | used through Pillow's separately installed `PIL._avif` provider; not bundled or linked into SceneIO distributions; one unmodified upstream 12-bit rejection fixture is stored as base64 in the source test fixtures and is not packaged in wheels | BSD-2-Clause | [libavif.txt](libavif.txt) |
| libaom | 3.14.1 encoder in the locally validated Pillow 12.3.0 wheel | used through Pillow/libavif; not bundled or linked into SceneIO distributions | BSD-2-Clause with the Alliance for Open Media royalty-free patent license | [license](libaom.txt), [patent license](libaom-patents.txt) |
| dav1d | 1.5.3 decoder in the locally validated Pillow 12.3.0 wheel | used through Pillow/libavif; not bundled or linked into SceneIO distributions | BSD-2-Clause | [dav1d.txt](dav1d.txt) |

The complete Apache-2.0 terms in the root `LICENSE` also cover the
Apache-licensed portion of LAZperf. Local integration and correctness changes
to vendored or fetched projects are documented beside their sources in
`src/cpp/third_party/*/COMMIT.txt`.

NumPy is SceneIO's sole base Python runtime dependency, but it is installed as
a separate distribution and is not copied or linked into SceneIO wheels.
h5py/HDF5, Zarr/numcodecs, cbor2, tifffile, pye57, PyArrow, TinyVDB, TinyUSDZ,
and Pillow's libavif provider are separately installed only when their
respective extras are selected; none is copied or linked into SceneIO wheels.
PyYAML, gsply, and PlayCanvas splat-transform are installed only in test
environments. Build tools and other test-only oracle packages are not bundled.
GaussianSplats3D contributes pinned test vectors only; gsplat and Brush are
reference-only. Delvewheel
itself is not bundled, but its generated Windows bootstrap and the verifier's
exact-output fixture are distribution content, so its notice is included.
The MSVC runtime sidecar is the platform-toolchain exception required by the
Windows/MSVC wheel target; all codec libraries remain under the permissive
open-source policy.

OpenUSD's TOST-1.0 license is accepted as a permissive, Apache-2.0-derived
license under the repository oracle policy. The pinned `usd-core` provider is
still test-only: no `pxr` module, executable, wheel, or OpenUSD code is copied
into SceneIO's runtime wheel. The focused hosted oracle may install it and
must retain [openusd.txt](openusd.txt) with the test artifact.

The machine-readable source and license policy for conversion/normalization
oracles is [`tests/contracts/oracle_sources_v1.toml`](../tests/contracts/oracle_sources_v1.toml).
It records the upstream revision, license expression and class, star snapshot,
lineage, execution role, and exact evidence tests. Strong project-wide
copyleft remains reference-only; MPL-2.0, BSL-1.0, TOST-1.0, and comparable
permissive or weak file-level copyleft sources may be used in separately
installed test lanes.

No entry in this directory changes any upstream license terms.

This software is based in part on the work of the Independent JPEG Group.
