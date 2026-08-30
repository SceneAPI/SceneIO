# Loaded records and neutral contracts

SceneIO has two intentionally different in-memory roles. Compiled records such
as `sceneio.FeatureSet` and `sceneio.DepthMap` preserve storage facts needed for
exact inspection and writing. Python records under `sceneio.data` are the
smaller, backend-neutral inputs and outputs shared by mapping and matching
procedures. Equal short names do not imply equal class identity.

`sceneio.canonical` is the explicit bridge. Importing `sceneio` remains lazy;
the compiled core and NumPy load only when the canonicalization namespace is
used. Ordinary `read()` never projects a record implicitly.

## Adapter surface

| Loaded/storage-faithful role | Neutral role | Functions | Boundary |
|---|---|---|---|
| `sceneio.Camera` | `sceneio.data.CameraIntrinsics` | `camera_intrinsics_from_native`, `camera_from_neutral` | Intrinsic model, dimensions, and ordered parameters are exact. Collection-local camera id is supplied separately when materializing. |
| `sceneio.FeatureSet` | `sceneio.data.FeatureSet` | `feature_set_from_native`, `feature_set_from_neutral` | Nx2 keypoints, descriptors, scores, and pixel center are exact. Native image/extractor metadata, colors, quality, presence state, and extra 4/6-column keypoint attributes require `allow_loss=True` when projecting. Unsupported descriptor dtypes refuse on materialization. |
| `sceneio.MatchGraph` | `sceneio.data.CorrespondenceGraph` | `correspondence_graph_from_native`, `match_graph_from_neutral` | The caller selects exactly one `raw` or `verified` channel and supplies the numeric-id/name map. Raw presence comes from `match_present`; verified presence comes from `geometry_present`, including verified rows without E/F/H matrices. Indexed pairs, per-match raw scores, and E/F/H are preserved. A populated unselected channel, relative poses, recovered cameras, provenance, retrieval scores, configuration codes, and absent-vs-empty SQL state require loss acknowledgement. Coordinate-mode neutral pairs cannot become a native indexed graph. |
| `sceneio.DepthMap` | `sceneio.data.DepthMap` | `depth_map_from_native`, `depth_map_from_neutral` | Projection requires an explicit factor from stored values to parent-frame units. Invalid-policy metadata becomes a boolean validity mask. Native confidence needs loss acknowledgement; unspecified depth meaning needs acknowledgement. Ray-distance depth refuses in both directions until a ray calibration performs the geometric conversion; neutral materialization therefore accepts only `camera_z`. Invalid pixels use the selected native sentinel policy. |
| `sceneio.PosedViewSet` | `sceneio.data.PosedViewSet` | `posed_view_set_from_native`, `posed_view_set_from_neutral` | Pose direction, quaternion order, OpenCV/OpenGL axes, numeric scale, names, and referenced parametric cameras convert explicitly; equivalent neutral intrinsics share one native camera entry. Native-to-neutral projection requires caller-owned image references; normalized output also requires `normalization_scale_to_meters`. Arbitrary or normalized neutral input requires `source_scale_to_meters`; `scale_to_meters` declares the target native storage unit. Timestamps, unreferenced native cameras, and unsupported neutral priors/masks require loss acknowledgement. `RayMap` calibration and world-frame re-anchoring refuse without the missing geometric context. |

The public type catalog records each pair with reciprocal `adapts_to`
relations. That relation means an explicit checked adapter exists; it does not
claim that every value in either representation is losslessly representable.

## Example: HLoc records to the matching floor

```python
import sceneio

feature_store = sceneio.read("features.h5", format="hloc_features")
match_store = sceneio.read("matches.h5", format="hloc_matches")

# HLoc carries image dimensions and names on each native feature record. The
# graph keys retain the names, while the neutral FeatureSet has no size field,
# so that storage-only omission is acknowledged explicitly.
features = {
    name: sceneio.canonical.feature_set_from_native(record, allow_loss=True)
    for name, record in feature_store.items()
}
graph = sceneio.canonical.correspondence_graph_from_native(
    match_store.graph,
    features,
    image_names=match_store.image_names,  # an ordered sequence means ids 1..N
    channel="raw",
    allow_loss=True,
)
```

## One camera-model authority

`src/sceneio/_camera_models.py` is the only editable camera-model registry. It
owns persisted ids 0 through 17, names, parameter counts, and ordered parameter
names. This includes `RAD_TAN_THIN_PRISM_FISHEYE`, the division and equidistant
fisheye models, `EUCM`, and `EQUIRECTANGULAR` in addition to the original
0-through-10 vocabulary.

Python calibration contracts and every Python COLMAP adapter import derived
views of that manifest. During CMake configuration,
`tools/generate_camera_models.py` generates the native
`colmap_model_info()` lookup from the same file. A model addition therefore
changes one authority and must pass the Python/native/generator parity test;
hand-maintained count tables or a second C++ switch are not permitted.

## Compatibility rules

- Native and neutral classes remain distinct; no alias changes existing
  `isinstance`, pickle, constructor, or writer behavior.
- Conversion is explicit and never part of format detection or `read()`.
- Semantic changes needing calibration or a world transform refuse even when
  `allow_loss=True`. That flag acknowledges omission; it is not permission to
  relabel values.
- Array dtype changes are permitted only where the target record itself fixes
  a lossless canonical integer/index dtype. Descriptor values are never
  silently narrowed.
