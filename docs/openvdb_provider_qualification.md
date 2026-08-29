# OpenVDB FC5 provider qualification

FC5 closes as a qualified provider exclusion. SceneIO keeps its existing
single-grid compatibility path and does not export `SparseGrid`,
`SparseVolumeSet`, or typed multi-grid selectors under TinyVDB 0.9.0.

## Reproducible oracle vectors

[`tools/generate_openvdb_provider_vectors.py`](../tools/generate_openvdb_provider_vectors.py)
uses the official OpenVDB Python binding to author seven small cases: multiple
scalar grids, a nontrivial affine transform and nonzero background, an empty
transformed grid, a level set, a `vec3s` velocity grid, mixed float/vector/bool
types, and duplicate names. On Ubuntu 24.04 the oracle environment is:

```text
apt install python3-openvdb
python3 tools/generate_openvdb_provider_vectors.py build/fc5-openvdb-vectors
```

The qualified run used OpenVDB/pyopenvdb 10.0.1 to author the files and
TinyVDB 0.9.0 to consume them. The test route is opt-in because official
OpenVDB has no supported CPython 3.12 Windows wheel:

```text
set SCENEIO_OPENVDB_VECTOR_DIR=build\fc5-openvdb-vectors
.venv\Scripts\python.exe -m pytest -q tests/test_openvdb_provider_qualification.py
```

## Deciding observations

TinyVDB can enumerate `grid_count`, names, and tree type names from headers.
Everything else needed by a truthful `SparseGrid`—class, background,
transform, active count/bounds, and values—requires the zero-argument
`VDBFile.read_grids()`, whose provider documentation says it reads and
decompresses all grids. Passing an index or name is a `TypeError`. Thus a
selected-grid API would be a post-decode slice and fails the program's bounded
selection gate.

The official vectors also expose semantic loss:

- nonempty `Tree_float_5_4_3` scalar values, backgrounds, and an affine matrix
  are readable exactly enough for a possible aggregate-only prototype;
- the scale-2 transform on an empty float grid is returned as identity;
- a `Tree_vec3s_5_4_3` grid with two active velocity values, nonzero vector
  background, and scale 0.25 is returned with zero active values, scalar-zero
  background, identity transform, and a failing `to_sparse()` call;
- bool trees enumerate but are not sparse-decodable; and
- duplicate names survive and make name selection ambiguous.

The write surface cannot repair these limits: `VDBFile` has no `add_grid`, and
`VDBGrid.transform` is read-only. It can only replace or extend a grid already
present in a template.

## Closed boundary

The compatibility API remains one nonempty, zero-background,
identity-transform `Tree_float_5_4_3` grid represented as a `TensorDict`.
FC5 adds an explicit empty-grid refusal because TinyVDB loses the authored
transform of an empty grid; accepting it could otherwise silently relabel a
transformed source as identity. Existing nonempty scalar read/write and
metadata-only inspection behavior remains covered by its independent
TinyVDB oracle tests.

No selection benchmark is claimed: the provider exposes no selected-grid
operation to benchmark. `multiple_grids`, `vector_grids`, `empty_grids`,
`nonzero_background`, and `transformed_grids` remain discoverable unsupported
features. Reconsidering this exclusion requires a provider that preserves the
declared metadata/value types, decodes one selected grid without reading the
others, and passes the existing dependency, wheel, license, and oracle gates.
