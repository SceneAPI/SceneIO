# sceneapi-io

The **I/O contract** for [SceneAPI](https://github.com/SceneAPI). This is a
contract package — interfaces, wire codecs, and on-disk data-format schemas —
not an implementation. It is the single place where the SceneAPI core, the
backend packages, and the generated SDKs agree on how bytes are read, written,
and validated.

- Distribution: `sceneapi-io`
- Import package: `sceneapi_io`
- Version: `0.1.0`
- Dependencies: **none** (Python standard library only)

## What it owns

- **Wire codecs** — the `application/x-sfm-points-v1` binary points format
  (44-byte header + fixed 26-byte records) via
  `sceneapi_io.points_binary` (`encode_all`, `decode_records`,
  `write_header` / `read_header`, `write_record` / `read_record`,
  `Point3DRecord`, and the `MAGIC` / `HEADER_SIZE` / `RECORD_SIZE` constants).
- **Storage / source protocols** — `BlobStore` (the sha256-keyed binary-store
  Protocol) and `validate_sha` (the content-address format check) in
  `sceneapi_io.blobstore`; `ImageSourceImpl` and `MaterializedImage` in
  `sceneapi_io.imagesource`.
- **Schema contracts** — the extended COLMAP scene-database schema
  (`sceneapi_io.colmap_db`: table/column model, `pair_id` encoding, extractor /
  matcher registries, and the serialized cross-tier `contract_dict()`) and the
  `PCMAPIN` resume-checkpoint helpers in `sceneapi_io.mapping_input`.
- **Error base** — `SceneIoError`, the root of every format/codec/contract
  error raised here.

## Who depends on it

The SceneAPI **core** (`sceneapi`) re-exports these names from its historic
module paths as thin shims and ships the concrete backends (filesystem / S3 /
in-memory blob stores, the FastAPI service, engine adapters) that implement the
protocols defined here. The Python / TypeScript / C++ **SDKs** decode the same
wire formats. Keeping the contract in one leaf package means all of them move in
lockstep.

## Usage

```python
from sceneapi_io import Point3DRecord, encode_all, decode_records

blob = encode_all(
    [Point3DRecord(point3d_id=1, xyz=(1.0, 2.0, 3.0), rgb=(255, 0, 0), track_len=4)],
    bbox_min=(1.0, 2.0, 3.0),
    bbox_max=(1.0, 2.0, 3.0),
)
records, bbox_min, bbox_max = decode_records(blob)
```

```python
from sceneapi_io import BlobStore, validate_sha, SceneIoError

validate_sha("a" * 64)          # ok
try:
    validate_sha("not-a-sha")   # raises SceneIoError
except SceneIoError:
    ...
```

```python
from sceneapi_io import colmap_db  # noqa: F401 — schema contract, plain data

# or the flattened surface:
from sceneapi_io import COLMAP_DB_TABLES, contract_dict, image_pair_to_pair_id
```

## Development

```powershell
uv venv --seed
uv pip install -e ".[dev]"
uv run ruff check src tests
uv run pytest -q
```

## License

Apache-2.0. See `LICENSE`.
