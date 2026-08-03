# Large-file I/O benchmark

Schema: `large-io-v1`
Tier: `standard`
Generated: `2026-08-03T13:39:47.943951+00:00`
Commit: `d538306ffe702df8cc894f81b0b3ce59acd2aebc` (dirty=False)
Cache mode: `warm`
Cache control: `{"applied": false, "reason": null, "requested": false, "status": "not_requested"}`
Completion: **False**; correctness: **False**
Source verification: **verified**

Cache path: `build\bench-data\large-io`. generated or verified in cache; large inputs are not committed
Outputs: provider outputs retained through cross-read, then removed.

## Consolidated outcome

This is a finite, incomplete qualification rather than a release-wide speed
claim. The detailed tables below come from the wider 300-second run at
`d538306`; it completed NPY, LAZ, SPZ, and GLB with 29 successful operations,
36 passing validation rows, and no failed measured or cross-read row. The
follow-up run at `8eac044` used the documented 900-second child bound. It
completed 22 operations and 24 validation rows for NPY, LAZ, and GLB, all
passing, but the 256 MiB COLMAP preparation still reached that bound.

| Evidence | Bound | Result | Purpose |
| --- | ---: | --- | --- |
| [`windows-msvc-d538306-partial.json`](results/large_io/windows-msvc-d538306-partial.json) | 300 s | four cases measured; COLMAP preparation timeout | widest measurement set and the detailed tables below |
| [`windows-msvc-8eac044.json`](results/large_io/windows-msvc-8eac044.json) | 900 s | three cases measured; COLMAP preparation timeout; SPZ preparation-only assertion | confirms the COLMAP limit and records the follow-up exactly |

The follow-up SPZ assertion came from comparing a pre-quantization prepared
record with the written file. It did not occur in a timed operation, and the
current harness fixes it by reusing prepared values only for COLMAP. The SPZ
measurements below remain supported by all nine writer-reader directions in
the first artifact. A focused post-fix standard SPZ preparation check then
passed in 6.816 seconds with the Niantic-written v4 fixture; it was not used as
a throughput sample. No third standard run was made.

### Performance reading

The speed ratio is reference time divided by SceneIO time; above 1 favors
SceneIO. Exact medians and all three samples remain in the generated tables.

| Workload | Operation | Reference | SceneIO s | Reference s | Ratio | Reading |
| --- | --- | --- | ---: | ---: | ---: | --- |
| NPY depth stack | full scan | NumPy | 0.1121 | 0.1146 | 1.022 | essentially matched; SceneIO slightly faster |
| NPY depth stack | write | NumPy | 0.1718 | 0.1293 | 0.752 | NumPy faster |
| Autzen LAZ | read | laspy/lazrs | 0.3365 | 0.1653 | 0.491 | laspy about 2.0x faster |
| Autzen LAZ | write | laspy/lazrs | 1.6616 | 0.2143 | 0.129 | laspy about 7.8x faster |
| Autzen LAZ | 256-point selection | laspy/lazrs | 0.16045 | 0.01245 | 12.884 | SceneIO about 12.9x faster |
| Racoon SPZ | read | Niantic | 0.1393 | 0.1313 | 0.942 | near parity; Niantic slightly faster |
| Racoon SPZ | write | Niantic | 5.4980 | 2.4758 | 0.450 | Niantic about 2.2x faster |
| Racoon SPZ | read | gsply | 0.1393 | 0.08594 | 0.617 | gsply about 1.6x faster |
| Racoon SPZ | write | gsply | 5.4980 | 0.9140 | 0.166 | gsply about 6.0x faster |
| Box-grid GLB | read | trimesh | 0.3683 | 0.3924 | 1.065 | SceneIO about 6.5% faster |
| Box-grid GLB | write | trimesh | 0.5804 | 1.2860 | 2.216 | SceneIO about 2.2x faster |

SceneIO's traced Python peak stayed below 4.3 MiB for every applicable
256 MiB-class read/write row, and every conclusive allocation check passed.
RSS includes decoded output ownership and therefore is not interpreted as a
whole-file Python copy. The main measured optimization opportunities are LAZ
full read/write and SPZ write. The unmeasured blocker is COLMAP: its generated
model occupied 537,771,252 encoded bytes across the retained model/common
trees, but SceneIO preparation did not finish inside 900 seconds, so no COLMAP
throughput number is reported.

Repository validation after consolidation: 26 focused benchmark/contract
tests passed; the full local suite passed with 4,633 tests and 16 documented
skips; Ruff and `git diff --check` passed. Hosted Linux/macOS validation was
not part of this local measurement run.

## Fixture provenance

| Case | Source | Acquisition | Prepare s | Logical MiB | Encoded MiB | Derivation |
| --- | --- | --- | ---: | ---: | ---: | --- |
| npy_depth_stack | synthetic | synthetic_fallback | 1.221 | 256.641 | 256.641 | {"fixture_version": "npy-depth-v2", "frames": 219, "geometry": [640, 480], "seed": "arange-remainder-v1"} |
| laz_autzen | pdal_autzen_laz | derived_fixture | 2.201 | 203.196 | 51.842 | {"count": 10653336, "fixture_version": "laz-pf2-origin-v2", "omitted_source_fields": ["gps_time", "classification", "returns", "scan_angle", "user_data", "point_source_id", "extra_bytes", "waveform", "crs_metadata"], "profile": "las-1.2-pf2", "retained_fields": ["x", "y", "z", "intensity", "red", "green", "blue"], "source_reason": "canonical SceneIO-compatible LAZ profile"} |
| spz_racoon_v4 | niantic_racoonfamily_spz | derived_fixture | 5.069 | 256.000 | 25.959 | {"kind": "derived_fixture", "output_profile": "SPZ v4 flags=0", "repeat_count": 2, "seed": "niantic-racoonfamily", "selected_seed_count": 932560, "translation_step": [0.125, 0.0, 0.0], "unsupported_source_flags_dropped": true} |
| glb_box_grid | khronos_box_vertex_colors_glb | derived_fixture | 5.956 | 256.001 | 217.602 | {"color_normalization": "float-or-normalized source values rounded to uint8", "grid_order": "x-major then y then z", "kind": "derived_fixture", "repeat_count": 279621, "seed": "khronos-box-vertex-colors"} |

### Licensed sources

| Source | Asset / repository | Pin type | License | Acquisition | Attribution | Size bytes | SHA-256 |
| --- | --- | --- | --- | --- | --- | ---: | --- |
| khronos_box_vertex_colors_glb | [asset](https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/2bac6f8c57bf471df0d2a1e8a8ec023c7801dddf/Models/BoxVertexColors/glTF-Binary/BoxVertexColors.glb) / [repository](https://github.com/KhronosGroup/glTF-Sample-Assets) | `2bac6f8c57bf471df0d2a1e8a8ec023c7801dddf` (git_commit) | [CC0-1.0](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/2bac6f8c57bf471df0d2a1e8a8ec023c7801dddf/Models/BoxVertexColors/LICENSE.md) | direct_upstream | Marco Hutter; KhronosGroup glTF Sample Assets BoxVertexColors | 1924 | `9c48227f33b0ba2fbcf23b98ebf60d1c8ae0c6e6c5281e0aa3cc58affee10382` |
| niantic_racoonfamily_spz | [asset](https://raw.githubusercontent.com/nianticlabs/spz/5bf2945de1a003cee07133b1e495fe9c6ffdc7e7/samples/racoonfamily.spz) / [repository](https://github.com/nianticlabs/spz) | `5bf2945de1a003cee07133b1e495fe9c6ffdc7e7` (git_commit) | [MIT](https://github.com/nianticlabs/spz/blob/5bf2945de1a003cee07133b1e495fe9c6ffdc7e7/LICENSE) | direct_upstream | Niantic Labs, nianticlabs/spz | 24202962 | `2e068d893730955c09aee324ff170c559f71c0e8758c1b14c3811a5969333cfe` |
| pdal_autzen_laz | [asset](https://media.githubusercontent.com/media/PDAL/data/ce0024257c573526389c4db9ab26e82739b8aaa9/autzen/autzen.laz) / [repository](https://github.com/PDAL/data) | `ce0024257c573526389c4db9ab26e82739b8aaa9` (git_commit) | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) | git_lfs_media | Aaron Reyna and Watershed Sciences; curated in PDAL/data by PDAL/Hobu | 56350988 | `944b947501156e45df1b3b9d25bc1dc04ff5ef377e7e169576ba59231c2896ba` |
| tum_freiburg1_xyz_groundtruth | [asset](https://cvg.cit.tum.de/rgbd/dataset/freiburg1/rgbd_dataset_freiburg1_xyz-groundtruth.txt) / [repository](https://cvg.cit.tum.de/data/datasets/rgbd-dataset) | `content-sha256:aac0319a6ef4e1cdf61e779d2152b95aa7e9f7b1749d6d18717b43ddabffede2` (content_sha256) | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) | official_download | TUM Computer Vision Group RGB-D SLAM Dataset and Benchmark | 201100 | `aac0319a6ef4e1cdf61e779d2152b95aa7e9f7b1749d6d18717b43ddabffede2` |

## Environment and providers

Platform: `Windows-11-10.0.26100-SP0`; Python: `CPython`; compiler: `MSC v.1943 64 bit (AMD64)`.
CPU count: `32`; RAM: `194202.7 MiB`.
Thread policy: `environment values when set; otherwise provider defaults`; variables: `{"MKL_NUM_THREADS": "provider defaults", "NUMEXPR_NUM_THREADS": "provider defaults", "OMP_NUM_THREADS": "provider defaults", "OPENBLAS_NUM_THREADS": "provider defaults", "WEBP_THREAD_LEVEL": "provider defaults"}`.

| Provider | Distribution version | Revision/build | Module |
| --- | --- | --- | --- |
| gsply | 0.4.6 | - | gsply |
| laspy | 2.7.0 | - | laspy |
| lazrs | 0.8.1 | - | lazrs |
| niantic_spz | 1.1.0 | 5bf2945de1a003cee07133b1e495fe9c6ffdc7e7 | spz |
| numpy | 2.4.6 | - | numpy |
| pycolmap | 4.1.1 | - | pycolmap |
| sceneio | 0.2.0 | - | sceneio |
| trimesh | 4.12.2 | - | trimesh |

## Measurements

Raw samples are seconds from a fresh timing child; memory is a separate fresh child.

| Case | Provider | Operation | Median s | Raw samples | Logical MiB/s | Encoded MiB/s | RSS delta MiB | Trace peak MiB | Status |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
| npy_depth_stack | sceneio | map_open | 5.29999e-05 | [0.0001146998256444931, 5.2999937906861305e-05, 4.0499959141016006e-05] | - | - | 12.277 | 4.187 | ok |
| npy_depth_stack | numpy | map_open | 0.0002329 | [0.00033119996078312397, 0.00023290002718567848, 0.0002118998672813177] | - | - | 0.238 | 0.048 | ok |
| npy_depth_stack | sceneio | full_scan | 0.112098 | [0.11549060000106692, 0.11209759977646172, 0.11209619999863207] | 2289.439 | 2289.440 | 245.766 | 4.221 | ok |
| npy_depth_stack | numpy | full_scan | 0.114594 | [0.11459420016035438, 0.11500119999982417, 0.1138486999552697] | 2239.560 | 2239.561 | 228.996 | 0.079 | ok |
| npy_depth_stack | sceneio | write | 0.171774 | [0.17802829993888736, 0.17177410004660487, 0.1686738000717014] | 1494.059 | 1494.060 | 269.090 | 4.188 | ok |
| npy_depth_stack | numpy | write | 0.129253 | [0.12795759993605316, 0.12925340002402663, 0.13062920002266765] | 1985.562 | 1985.563 | 0.188 | 0.014 | ok |
| npy_depth_stack | sceneio | inspect | 8.09e-05 | [0.00020579993724822998, 8.09000339359045e-05, 5.910010077059269e-05] | - | - | 12.402 | 4.187 | ok |
| npy_depth_stack | numpy | inspect | 0.0003017 | [0.0003790000919252634, 0.0003016998525708914, 0.00025649997405707836] | - | - | 0.242 | 0.048 | ok |
| laz_autzen | sceneio | read | 0.336514 | [0.338556099915877, 0.33651369996368885, 0.3325220998376608] | 603.828 | 154.056 | 306.355 | 4.189 | ok |
| laz_autzen | laspy | read | 0.165274 | [0.16378599987365305, 0.1829488999210298, 0.16527409991249442] | 1229.450 | 313.672 | 332.125 | 264.179 | ok |
| laz_autzen | sceneio | write | 1.66163 | [1.623125199927017, 1.682469299994409, 1.6616320998873562] | 122.287 | 31.199 | 4.281 | 0.013 | ok |
| laz_autzen | laspy | write | 0.214312 | [0.21354479994624853, 0.2143122002016753, 0.2302470998838544] | 948.132 | 241.899 | 65.250 | 40.662 | ok |
| laz_autzen | sceneio | point_select | 0.0124541 | [0.012454100186005235, 0.013509399956092238, 0.012261900119483471] | - | - | 14.781 | 4.189 | ok |
| laz_autzen | laspy | point_select | 0.160455 | [0.18605889985337853, 0.15939759998582304, 0.16045470000244677] | - | - | 331.070 | 264.179 | ok |
| laz_autzen | sceneio | inspect | 6.88999e-05 | [0.00015279999934136868, 6.889994256198406e-05, 5.060015246272087e-05] | - | - | 12.262 | 4.189 | ok |
| laz_autzen | laspy | inspect | 0.0001547 | [0.00023719994351267815, 0.00015469989739358425, 0.0001395998988300562] | - | - | 0.242 | 0.020 | ok |
| spz_racoon_v4 | sceneio | read | 0.139338 | [0.13739270018413663, 0.15070009999908507, 0.1393376998603344] | 1837.264 | 186.304 | 294.422 | 4.186 | ok |
| spz_racoon_v4 | niantic_spz | read | 0.131271 | [0.13127140002325177, 0.14045169996097684, 0.13007199997082353] | 1950.159 | 197.752 | 257.125 | 0.003 | ok |
| spz_racoon_v4 | gsply | read | 0.0859352 | [0.08593519986607134, 0.08548460016027093, 0.08759470004588366] | 2978.990 | 302.079 | 259.211 | 0.022 | ok |
| spz_racoon_v4 | sceneio | write | 5.498 | [5.498000600142404, 5.546781899873167, 5.475889699999243] | 46.562 | 5.260 | 170.316 | 0.004 | ok |
| spz_racoon_v4 | niantic_spz | write | 2.47581 | [2.475808900082484, 2.5043522000778466, 2.4744303999468684] | 103.401 | 10.485 | 0.305 | 0.004 | ok |
| spz_racoon_v4 | gsply | write | 0.913959 | [0.894128399901092, 0.913959400029853, 1.0149719000328332] | 280.100 | 28.405 | 0.758 | 0.005 | ok |
| spz_racoon_v4 | sceneio | inspect | 6.09001e-05 | [0.00013950001448392868, 6.0900114476680756e-05, 4.309997893869877e-05] | - | - | 12.391 | 4.187 | ok |
| glb_box_grid | sceneio | read | 0.36834 | [0.3782894001342356, 0.3622035998851061, 0.36833990016020834] | 695.012 | 590.763 | 511.617 | 4.188 | ok |
| glb_box_grid | trimesh | read | 0.392382 | [0.3972676999401301, 0.3923820999916643, 0.3875890001654625] | 652.427 | 554.566 | 781.164 | 780.834 | ok |
| glb_box_grid | sceneio | write | 0.580406 | [0.5804058997891843, 0.5824128999374807, 0.5797853001859039] | 441.072 | 374.914 | 604.539 | 0.008 | ok |
| glb_box_grid | trimesh | write | 1.28602 | [1.2686866000294685, 1.2860234000254422, 1.286056999815628] | 199.064 | 169.205 | 570.332 | 652.828 | ok |
| glb_box_grid | sceneio | inspect | 9e-05 | [0.00016520009376108646, 8.999998681247234e-05, 7.519987411797047e-05] | - | - | 12.590 | 4.188 | ok |
| glb_box_grid | trimesh | inspect | 0.439345 | [0.4393448999617249, 0.440510299988091, 0.43572710012085736] | - | - | 781.070 | 780.834 | ok |

## Matching-operation ratios

The SceneIO/reference speed ratio is reference seconds divided by SceneIO seconds within the same case and full operation; values above 1 favor SceneIO. Map-open, partial, and inspect rows are excluded.

| Case | Operation | Reference | SceneIO/reference speed ratio |
| --- | --- | --- | ---: |
| glb_box_grid | read | trimesh | 1.065 |
| glb_box_grid | write | trimesh | 2.216 |
| laz_autzen | read | laspy | 0.491 |
| laz_autzen | write | laspy | 0.129 |
| npy_depth_stack | full_scan | numpy | 1.022 |
| npy_depth_stack | write | numpy | 0.752 |
| spz_racoon_v4 | read | gsply | 0.617 |
| spz_racoon_v4 | read | niantic_spz | 0.942 |
| spz_racoon_v4 | write | gsply | 0.166 |
| spz_racoon_v4 | write | niantic_spz | 0.450 |

## Correctness validation

| Case | Check | Writer | Reader/operation | Status | Profile |
| --- | --- | --- | --- | --- | --- |
| npy_depth_stack | provider_output_cross_read | sceneio | sceneio | pass | shape_dtype_order_exact |
| npy_depth_stack | provider_output_cross_read | sceneio | numpy | pass | shape_dtype_order_exact |
| npy_depth_stack | provider_output_cross_read | numpy | sceneio | pass | shape_dtype_order_exact |
| npy_depth_stack | provider_output_cross_read | numpy | numpy | pass | shape_dtype_order_exact |
| npy_depth_stack | common_file_cross_read | - | - | pass | shape_dtype_fixed_float64_reduction |
| npy_depth_stack | common_file_read | - | full_scan | pass | fixed_float64_reduction |
| npy_depth_stack | common_file_read | - | inspect | pass | normalized_provider_metadata |
| npy_depth_stack | common_file_read | - | map_open | pass | provider_operations_completed |
| laz_autzen | provider_output_cross_read | sceneio | sceneio | pass | absolute_xyz_half_scale_plus_f32_ulp_and_integer_attributes |
| laz_autzen | provider_output_cross_read | sceneio | laspy | pass | absolute_xyz_half_scale_plus_f32_ulp_and_integer_attributes |
| laz_autzen | provider_output_cross_read | laspy | sceneio | pass | absolute_xyz_half_scale_plus_f32_ulp_and_integer_attributes |
| laz_autzen | provider_output_cross_read | laspy | laspy | pass | absolute_xyz_half_scale_plus_f32_ulp_and_integer_attributes |
| laz_autzen | common_file_cross_read | - | - | pass | laspy_sceneio_scale_and_integer_attributes |
| laz_autzen | partial_read | - | - | pass | sceneio_point_window_equals_laspy_full_slice |
| laz_autzen | common_file_read | - | inspect | pass | normalized_provider_metadata |
| laz_autzen | common_file_read | - | point_select | pass | provider_operations_completed |
| laz_autzen | common_file_read | - | read | pass | provider_operations_completed |
| spz_racoon_v4 | provider_output_cross_read | sceneio | sceneio | pass | spz_racoon_v4:semantic-v1 |
| spz_racoon_v4 | provider_output_cross_read | niantic_spz | sceneio | pass | spz_racoon_v4:semantic-v1 |
| spz_racoon_v4 | provider_output_cross_read | gsply | sceneio | pass | spz_racoon_v4:semantic-v1 |
| spz_racoon_v4 | provider_output_cross_read | sceneio | niantic_spz | pass | spz_racoon_v4:semantic-v1 |
| spz_racoon_v4 | provider_output_cross_read | niantic_spz | niantic_spz | pass | spz_racoon_v4:semantic-v1 |
| spz_racoon_v4 | provider_output_cross_read | gsply | niantic_spz | pass | spz_racoon_v4:semantic-v1 |
| spz_racoon_v4 | provider_output_cross_read | sceneio | gsply | pass | spz_racoon_v4:semantic-v1 |
| spz_racoon_v4 | provider_output_cross_read | niantic_spz | gsply | pass | spz_racoon_v4:semantic-v1 |
| spz_racoon_v4 | provider_output_cross_read | gsply | gsply | pass | spz_racoon_v4:semantic-v1 |
| spz_racoon_v4 | common_file_cross_read | - | - | pass | spz_racoon_v4:semantic-v1 |
| spz_racoon_v4 | common_file_read | - | inspect | pass | normalized_provider_metadata |
| spz_racoon_v4 | common_file_read | - | read | pass | provider_operations_completed |
| glb_box_grid | provider_output_cross_read | sceneio | sceneio | pass | glb_box_grid:semantic-v1 |
| glb_box_grid | provider_output_cross_read | trimesh | sceneio | pass | glb_box_grid:semantic-v1 |
| glb_box_grid | provider_output_cross_read | sceneio | trimesh | pass | glb_box_grid:semantic-v1 |
| glb_box_grid | provider_output_cross_read | trimesh | trimesh | pass | glb_box_grid:semantic-v1 |
| glb_box_grid | common_file_cross_read | - | - | pass | glb_box_grid:semantic-v1 |
| glb_box_grid | common_file_read | - | inspect | pass | normalized_provider_metadata |
| glb_box_grid | common_file_read | - | read | pass | provider_operations_completed |

## SceneIO allocation checks

| Case | Operation | Trace peak MiB | Bound MiB | Conclusive | Status | Profile / reason |
| --- | --- | ---: | ---: | --- | --- | --- |
| npy_depth_stack | map_open | 4.187 | 64.160 | True | pass | no_approximately_file_sized_python_allocation |
| npy_depth_stack | full_scan | 4.221 | 64.160 | True | pass | no_approximately_file_sized_python_allocation |
| npy_depth_stack | write | 4.188 | 64.160 | True | pass | no_approximately_file_sized_python_allocation |
| laz_autzen | read | 4.189 | 12.960 | True | pass | no_approximately_file_sized_python_allocation |
| laz_autzen | write | 0.013 | 12.960 | True | pass | no_approximately_file_sized_python_allocation |
| spz_racoon_v4 | read | 4.186 | 6.490 | True | pass | no_approximately_file_sized_python_allocation |
| spz_racoon_v4 | write | 0.004 | 7.229 | True | pass | no_approximately_file_sized_python_allocation |
| glb_box_grid | read | 4.188 | 54.400 | True | pass | no_approximately_file_sized_python_allocation |
| glb_box_grid | write | 0.008 | 54.401 | True | pass | no_approximately_file_sized_python_allocation |

## Skips

- {'case_id': 'colmap_tum_tracks', 'reason': 'worker exceeded 300 seconds', 'type': 'RuntimeError'}

## Completion limits

- one or more required fixtures were not prepared
- missing provider operations: [('colmap_tum_tracks', 'pycolmap', 'inspect'), ('colmap_tum_tracks', 'pycolmap', 'read'), ('colmap_tum_tracks', 'pycolmap', 'write'), ('colmap_tum_tracks', 'sceneio', 'image'), ('colmap_tum_tracks', 'sceneio', 'inspect'), ('colmap_tum_tracks', 'sceneio', 'read'), ('colmap_tum_tracks', 'sceneio', 'write')]
- missing directional provider output reads: [('colmap_tum_tracks', 'pycolmap', 'pycolmap'), ('colmap_tum_tracks', 'pycolmap', 'sceneio'), ('colmap_tum_tracks', 'sceneio', 'pycolmap'), ('colmap_tum_tracks', 'sceneio', 'sceneio')]
- missing common-input oracle checks: ['colmap_tum_tracks']
- one or more cases lack cross-read validation

## Interpretation limits

These measurements describe this recorded machine, provider versions, fixture profiles, and warm-cache run. They are comparative evidence, not portable throughput guarantees. Licensed assets are provenance seeds; transformed cases are labeled derived fixtures.

## Reproduction

`.venv\Scripts\python.exe bench/bench_large_io.py run --tier standard --runs 3 --worker-timeout 300 --cache build\bench-data\large-io`
