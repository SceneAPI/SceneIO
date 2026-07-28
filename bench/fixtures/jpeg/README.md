# JPEG qualification fixtures

`ycck_16x16_q90_420.b64` is generated test data, not copied image content.
It was produced on 2026-07-28 with the pinned libjpeg-turbo 3.2.0
TurboJPEG API from commit `c85e6b905bf237038faa936dab160ebfc5da0344`.

The generator creates a 16 x 16 CMYK raster with these byte formulas:

- C: `(x * 13 + y * 3) & 255`
- M: `(x * 5 + y * 17) & 255`
- Y: `(x * 19 + y * 7) & 255`
- K: `(x * 11 + y * 23) & 255`

It calls `tj3Compress8` with `TJPF_CMYK`, quality 90, 4:2:0 subsampling,
sequential output, and optimization disabled. TurboJPEG's documented default
maps a CMYK input raster to a YCCK JPEG. The resulting 911-byte stream has
Adobe transform 2 and SHA-256
`2a3223d511c8750927237bd7b3b0d1d6e2aeb7bfe14e96197f00632907ef01c0`.
The base64 wrapper is used so the fixture remains reviewable in text diffs.

The libjpeg-turbo and IJG notices are already indexed in `LICENSES/README.md`
and packaged as `LICENSES/libjpeg-turbo.txt` and
`LICENSES/libjpeg-turbo-IJG.txt`.
