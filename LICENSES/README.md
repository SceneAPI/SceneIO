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
| libwebp | 1.5.0, commit `a4d7a715337ded4451fec90ff8ce79728e04126c` | vendored and statically linked core libraries | BSD-3-Clause with upstream additional patent grant | [license](libwebp.txt), [patent grant](libwebp-patents.txt) |
| libjpeg-turbo | 3.2.0, commit `c85e6b905bf237038faa936dab160ebfc5da0344` | statically linked only in explicit JPEG qualification builds until selected | IJG, BSD-3-Clause, zlib | [libjpeg-turbo.txt](libjpeg-turbo.txt), [upstream `README.ijg` copy](libjpeg-turbo-IJG.txt) |
| stb_image / stb_image_write | commit `31c1ad37456438565541f4919958214b6e762fb4` | vendored compiled headers | MIT option | [stb.txt](stb.txt) |
| TinyEXR | commit `1b106618644dbf8a0935c2348ba51a2d863dd7c2` | vendored compiled headers | BSD-3-Clause | [tinyexr.txt](tinyexr.txt) |
| tinyobjloader | commit `45636bdcef1a4fec140346b90c0b50bf0bc3e23b` | vendored compiled header | MIT; bundled earcut ISC; bundled fast_float under MIT | [tinyobjloader.txt](tinyobjloader.txt), [fast-float.txt](fast-float.txt) |
| cgltf | 1.15, commit `360db1a95480fe102ae9c69b27c5d101167ff5ba` | vendored compiled headers | MIT; bundled jsmn MIT | [cgltf.txt](cgltf.txt) |
| COLMAP persisted formats | upstream BSD formats, compatibility reference pinned at OpsiClear `colmap_mod` commit `de15b08a2dba98b55d6ddfb7cedac147838afbb4` | independently implemented codecs and oracle-derived tests; no COLMAP library is linked or bundled | BSD-3-Clause for upstream COLMAP formats; SceneIO implementation Apache-2.0 | [COLMAP notice](colmap.txt), [OpsiClear compatibility authorization record](opsiclear-colmap-mod.txt) |

The complete Apache-2.0 terms in the root `LICENSE` also cover the
Apache-licensed portion of LAZperf. Local integration and correctness changes
to vendored or fetched projects are documented beside their sources in
`src/cpp/third_party/*/COMMIT.txt`.

NumPy is SceneIO's sole Python runtime dependency, but it is installed as a
separate distribution and is not copied or linked into SceneIO wheels. Build
tools and test-only oracle packages are otherwise not bundled. Delvewheel
itself is not bundled, but its generated Windows bootstrap and the verifier's
exact-output fixture are distribution content, so its notice is included.
The MSVC runtime sidecar is the platform-toolchain exception required by the
Windows/MSVC wheel target; all codec libraries remain under the permissive
open-source policy.

No entry in this directory changes any upstream license terms.

This software is based in part on the work of the Independent JPEG Group.
