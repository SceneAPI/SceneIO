# SplatTransform test oracle

This private npm package pins the external PlayCanvas SplatTransform executable
used by SceneIO's Gaussian cross-implementation tests. It is test tooling only:
it is not imported by SceneIO and is not included in SceneIO distributions.

The three-platform CI lane installs this directory with
`npm ci --ignore-scripts`, verifies the pinned CLI revision, and sets
`SCENEIO_SPLAT_TRANSFORM_CLI`. Normal tests keep the oracle optional;
`SCENEIO_REQUIRE_SPLAT_ORACLES=1` turns absence into a failure in the dedicated
lane.

For a local Windows run from the repository root:

```powershell
npm ci --prefix tools/splat-transform-oracle --ignore-scripts --no-audit --no-fund
$env:SCENEIO_SPLAT_TRANSFORM_CLI = (Resolve-Path tools/splat-transform-oracle/node_modules/.bin/splat-transform.cmd)
$env:SCENEIO_REQUIRE_SPLAT_ORACLES = "1"
.venv/Scripts/python.exe -m pytest -q tests/codecs/test_splat_transform_oracle.py
```

Do not replace the locked install with bare `npx`; update the direct version
and lockfile together when deliberately qualifying a new upstream release.
