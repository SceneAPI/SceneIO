"""Parity and hardening suite for mkkellogg KSplat v0.1.

The oracle below is an independent struct/NumPy implementation of the pinned
GaussianSplats3D v0.4.7 layout. The compressed embedded vectors were produced
by its MIT-licensed ``util/create-ksplat.js`` at commit
``eb2fc4593e3ea5e75388296fcdde2459542d1290``.
"""

from __future__ import annotations

import base64
import gc
import math
import mmap
import struct
import tracemalloc
import zlib

import numpy as np
import pytest

from sceneio import _core

SH_C0 = 0.28209479177387814
HEADER_SIZE = 4096
SECTION_HEADER_SIZE = 1024
OFFICIAL_VECTORS = {
    0: """
eNrtmPtLFFEUxyftZdqaoUmmUaLUJmZLZZZ7z0xE4YZsRZhYiD1+yDRNQ5Isqo1CtG1LCcus
zYgN2xRFsmzdObOGaKZZYJJoDyHx0UMrAiPpcSdaugT9AcX9MANzZ5hzvuf7vb/MCBMEgR4/
zym/zj952N6OkUdbQeBwOBwOh8PhcDgcDofzT/K3b36VJ56/rz24VRzOf0dmb4kruOWDYl7s
kHU5Jqjd6oT9mgHwX7RGiRrzUKrD7FgTlQxButgJ4/U12LFyNxo9e2Szbh22fjwv+4zHkFNN
EfI0i5VEHjXA9NTN+orMKZDaeQwOj8rQs6wc3xxYCAWJRaD+R7xbcwbXa8PR3nsVKuOcuCTp
CE6dPxGnWeY6DcX9rpt2u0sQjrnMvU+Jz/vnJPvBF2K+E6wkvvRQrIZZiiZQg6puthZbw6xr
pprq9QWJfsDqcvezWPvIvvw0aEuppc9v4sjGZOxuOQlvX92DNKkMK+P0tNYJOdww07U/uEUMT
M6RLqydI8b1XBHjvTrFxhublAHlOpru3wbTHisaswo1Wts5jJgZhXR2edhLQ3VYnVQfYb0wO
AtJfIkIqwYvQTBpVHtQLdthW3oVsL66PWP9FYQ+mlGRlJyzSVpxzQC2wJfi0iaT5FOmh8rH0
crrvWFiqysBhQ2Xv1Gf1WzUTGC91kYetsdD3vFr4NuVAWWTb0FDiB2TvhXD1/A2HPay0Bzmq
77Jz6468Kz3IUztFOgcnQ0dKweJ0XMrxpcoMl3rtTZ/qMjMB0NxmJSQEOByDO2UWnakSKUvg
mBe9EVY8KQIc/I8xM+1oDSvtWHdiNBBtas1Zdqb+Ha9c9JcSFXdFjjrPU5G5Vyga0ivWg50
TqC54cGAAjpzIN0vFfR+HVaHZiN9j/bfHEtnwYygjUgzk2m2hGoGmhEIQrlE9y5qiUP8dCN
ful3SKOGeR1iVlUveTt4pZvulg6m6ewtbi63B5sLqcvebvcsM6r9vNmN3fmzWqo7+GIvoGAp
Vdo1NWm3c5ynCgdOiulejA7LE3brvJKTPBsMzjGOsx6y3rBdsXu4cnIVNcLG0FFlf3Z6x/v
4AJe7SEw==
""",
    1: """
eNpjYGRgACIwZodiEBsZnD1zZp9u/Uk7hlEwCkbBKBgFo2AUjIJRMApGwSgYBaNgFAxJAOvz
gzr9rGCRBQ48QPJ/PQODBxNEDUicaTSoRsEoGHaACYoZkbDnpCkHwkJNDzAwHNgPYq9axeXA
wJDgUHB7mx1EHMIODX3qAFKzPXe1A0TNgf3hNVEbVE5wmzwyNTCX3CW+I3DrSyMpQ2vG1q2
Wmy+sM9y0f81xzbiVX3S8jWYrWRuwmbw3ZdzqbNhlkratdovmRj7TR1s/bVbc8GUBxHX79N
7rXdN/ukNsx6YdBRtAIhB1EDWG646rdhlATAPpZNEPMZ5kGrf11SY9E3GzW1sebVRcs+7H1
gTPCbcs/tnMsOvdZbp1m+nnLX4FXXxLt1RsnL2qYMOXJWl6EJeE6vwxfG7CuU1xC4txtinE
vSDXQdwcwO73K6bE1+iHHZ/LE8NtO5Ut121i8J/7r2uNoVacoaZumpGMaZ7xAtOArdNNIrc
VbOHb+GXF1a03NrNtmD3PUv/Cpj9rZ6stNbA2if04Y2Zw02+nawYXTfq2CFt83am1des7hn
PHN95Ynaedt/y47lajG/p7jY+brjXcb2K4zWPL/g3Opmu3dm7OWz9bSnNrw6a4tV0aXwzYS
gUFdXddtLV14XGr3rZbW8A6wrhx/Y0wiDqIGoiPIKaBdCabeJtB/A3yJcTv23K/eJqv0feQ
tsi2YWBosP6pr2/6UsDvO8TdEDdDXALxHcgnKmZntkDcC3IdxM0A0ToJtw==
""",
    2: """
eNpjYGRgACIwZodiJgZUcPbMmX269SftGEbBKBgFo2AUjIJRMApGwSgYBaNgFIyCUTAkAazP
DxoAYAWLLHDgAZL/64EsRogaVixjAqNgFIyCoQ+YoJgRCXtOmnIgLNT0AAPDgf0g9qpVXA4M
DAkOBbe32UHEIezQ0KcOIDXbc1c7QNQc2B9eE7VB5QS3ySNTA3PJXeI7Are+NJIytGYUNI9z
yugvnrm/ZfXF79JbbzOo+TzjMgivhbhin957vWv6T3eI7di0o2ADWEjNByib2L4OqOUZ1+J
TH0Ssr/ySd81e92NrgueEWxb/bGbY9e4y3brN9PMWv4IuPmXP/OCqBUDDp+15zK57/C3Qvu
/SQBsD2P1+xZT4Gv2w43N5Yrhtp7Lluk0M/nP/ZU7YNuvA89MfRe8wqvuWcBtG1C2xSepYf
zX244yZwU2/na4ZXDTp2yJs8XWn1tat7xjOueVMLp97ePm5Lzvvs2gFvOIziW6UsE/t3sRW
Kiiou+uira0Lj1v1tt3aAtYRxo3rb4QB5YGyQMcAtUjY3/gPdB+7LtCF23K/eJqv0feQtsi
2YWBosP6pr2/6UsDvO9B+oO1Aw4FOskn6rQC0TysAaCMAtxS5Mg==
""",
}


def _official_vector(level: int) -> bytes:
    return zlib.decompress(
        base64.b64decode("".join(OFFICIAL_VECTORS[level].split()))
    )


def _cloud(n: int = 73, degree: int = 2):
    i = np.arange(n, dtype=np.int64)
    means = np.stack(
        [
            ((i * 17) % 101 - 50) / 7,
            ((i * 31) % 97 - 48) / 9,
            ((i * 43) % 89 - 44) / 11,
        ],
        axis=1,
    ).astype(np.float32)
    scales = np.stack(
        [
            ((i * 7) % 37 - 18) / 8,
            ((i * 11) % 41 - 20) / 9,
            ((i * 13) % 43 - 21) / 10,
        ],
        axis=1,
    ).astype(np.float32)
    quaternions = np.stack(
        [
            np.where(i % 2, 1, -1) / 5,
            ((i * 3) % 31 - 15) / 17,
            ((i * 5) % 29 - 14) / 19,
            ((i * 7) % 23 - 11) / 13,
        ],
        axis=1,
    ).astype(np.float32)
    opacities = (((i * 19) % 127 - 63) / 9).astype(np.float32)
    sh_dc = np.stack(
        [
            ((i * 23) % 137 - 68) / 32,
            ((i * 29) % 131 - 65) / 33,
            ((i * 37) % 139 - 69) / 34,
        ],
        axis=1,
    ).astype(np.float32)
    rest = (0, 9, 24)[degree]
    if rest:
        j = np.arange(rest, dtype=np.int64)
        sh_rest = (
            ((i[:, None] * 17 + j[None, :] * 37) % 249 - 124) / 310
        ).astype(np.float32)
        return _core.gaussian_cloud(
            means,
            scales,
            quaternions,
            opacities,
            sh_dc,
            sh_rest,
        )
    return _core.gaussian_cloud(
        means, scales, quaternions, opacities, sh_dc
    )


def _record_size(level: int, degree: int) -> int:
    coefficients = (0, 3, 8)[degree] * 3
    return (44 + coefficients * 4, 24 + coefficients * 2, 24 + coefficients)[
        level
    ]


def _oracle_decode(data: bytes) -> dict[str, np.ndarray | int]:
    if len(data) < HEADER_SIZE:
        raise ValueError("short KSplat header")
    major, minor = data[:2]
    if (major, minor) != (0, 1):
        raise ValueError("unsupported KSplat version")
    section_count = struct.unpack_from("<I", data, 4)[0]
    level = struct.unpack_from("<H", data, 20)[0]
    sh_min, sh_max = struct.unpack_from("<ff", data, 36)
    sh_min = sh_min or -1.5
    sh_max = sh_max or 1.5
    headers_end = HEADER_SIZE + section_count * SECTION_HEADER_SIZE
    section_base = headers_end
    sections = []
    degree = 2
    total = 0
    for index in range(section_count):
        offset = HEADER_SIZE + index * SECTION_HEADER_SIZE
        count = struct.unpack_from("<I", data, offset + 4)[0]
        bucket_size, bucket_count = struct.unpack_from(
            "<II", data, offset + 8
        )
        block_size = struct.unpack_from("<f", data, offset + 16)[0]
        scale_range = struct.unpack_from("<I", data, offset + 24)[0] or 32767
        full, partial = struct.unpack_from("<II", data, offset + 32)
        section_degree = struct.unpack_from("<H", data, offset + 40)[0]
        degree = min(degree, section_degree)
        size = _record_size(level, section_degree)
        partial_bytes = partial * 4 if level else 0
        center_bytes = bucket_count * 12 if level else 0
        data_base = section_base + partial_bytes + center_bytes
        if level:
            lengths = [bucket_size] * full + list(
                struct.unpack_from(
                    f"<{partial}I", data, section_base
                )
                if partial
                else ()
            )
            centers = np.frombuffer(
                data,
                dtype="<f4",
                count=bucket_count * 3,
                offset=section_base + partial_bytes,
            ).reshape(-1, 3)
        else:
            lengths = []
            centers = np.empty((0, 3), dtype=np.float32)
        sections.append(
            (
                count,
                section_degree,
                size,
                data_base,
                lengths,
                centers,
                block_size,
                scale_range,
            )
        )
        section_base = data_base + count * size
        total += count

    coefficients = (0, 3, 8)[degree]
    means = np.empty((total, 3), dtype=np.float32)
    scales = np.empty((total, 3), dtype=np.float32)
    quaternions = np.empty((total, 4), dtype=np.float32)
    colors = np.empty((total, 4), dtype=np.uint8)
    sh = np.empty((total, coefficients * 3), dtype=np.float32)
    output = 0
    for (
        count,
        _section_degree,
        size,
        data_base,
        lengths,
        centers,
        block_size,
        scale_range,
    ) in sections:
        bucket = 0
        bucket_stop = lengths[0] if lengths else 0
        for row in range(count):
            record = data_base + row * size
            if level == 0:
                means[output] = struct.unpack_from("<3f", data, record)
                scalar = "<f"
                scalar_size = 4
                scale_offset, rotation_offset, color_offset, sh_offset = (
                    12,
                    24,
                    40,
                    44,
                )
            else:
                while row >= bucket_stop:
                    bucket += 1
                    bucket_stop += lengths[bucket]
                quantized = np.asarray(
                    struct.unpack_from("<3H", data, record), dtype=np.float64
                )
                means[output] = (
                    (quantized - scale_range)
                    * (block_size * 0.5 / scale_range)
                    + centers[bucket]
                ).astype(np.float32)
                scalar = "<e"
                scalar_size = 2
                scale_offset, rotation_offset, color_offset, sh_offset = (
                    6,
                    12,
                    20,
                    24,
                )
            linear = np.asarray(
                [
                    struct.unpack_from(
                        scalar, data, record + scale_offset + i * scalar_size
                    )[0]
                    for i in range(3)
                ],
                dtype=np.float32,
            )
            scales[output] = np.log(linear)
            quaternion = np.asarray(
                [
                    struct.unpack_from(
                        scalar,
                        data,
                        record + rotation_offset + i * scalar_size,
                    )[0]
                    for i in range(4)
                ],
                dtype=np.float64,
            )
            quaternion /= np.linalg.norm(quaternion)
            if quaternion[0] < 0:
                quaternion *= -1
            quaternions[output] = quaternion
            colors[output] = np.frombuffer(
                data, dtype=np.uint8, count=4, offset=record + color_offset
            )
            for channel in range(3):
                for coefficient in range(coefficients):
                    encoded = (
                        channel * 3 + coefficient
                        if coefficient < 3
                        else 9 + channel * 5 + coefficient - 3
                    )
                    if level == 0:
                        value = struct.unpack_from(
                            "<f", data, record + sh_offset + encoded * 4
                        )[0]
                    elif level == 1:
                        value = struct.unpack_from(
                            "<e", data, record + sh_offset + encoded * 2
                        )[0]
                    else:
                        byte = data[record + sh_offset + encoded]
                        value = byte / 255 * (sh_max - sh_min) + sh_min
                    sh[
                        output, channel * coefficients + coefficient
                    ] = value
            output += 1
    dc = ((colors[:, :3] / 255.0 - 0.5) / SH_C0).astype(np.float32)
    alpha = np.clip(colors[:, 3] / 255.0, 1e-6, 1 - 1e-6)
    opacity = np.log(alpha / (1 - alpha)).astype(np.float32)
    return {
        "count": total,
        "degree": degree,
        "means": means,
        "scales": scales,
        "quaternions": quaternions,
        "opacities": opacity,
        "sh_dc": dc,
        "sh_rest": sh,
    }


def _assert_matches_oracle(cloud, expected) -> None:
    assert cloud.num_gaussians == expected["count"]
    assert cloud.sh_degree == expected["degree"]
    np.testing.assert_array_equal(cloud.means, expected["means"])
    np.testing.assert_allclose(
        cloud.scales, expected["scales"], rtol=0, atol=3e-7
    )
    np.testing.assert_array_equal(
        cloud.quaternions, expected["quaternions"]
    )
    np.testing.assert_allclose(
        cloud.opacities, expected["opacities"], rtol=0, atol=1e-6
    )
    np.testing.assert_array_equal(cloud.sh_dc, expected["sh_dc"])
    np.testing.assert_array_equal(cloud.sh_rest, expected["sh_rest"])


def _merge_single_section_files(*files: bytes) -> bytes:
    header = bytearray(files[0][:HEADER_SIZE])
    counts = [struct.unpack_from("<I", data, 12)[0] for data in files]
    loaded = [struct.unpack_from("<I", data, 16)[0] for data in files]
    struct.pack_into(
        "<4I",
        header,
        4,
        len(files),
        len(files),
        sum(counts),
        sum(loaded),
    )
    section_headers = b"".join(
        data[HEADER_SIZE : HEADER_SIZE + SECTION_HEADER_SIZE]
        for data in files
    )
    payloads = b"".join(
        data[HEADER_SIZE + SECTION_HEADER_SIZE :] for data in files
    )
    return bytes(header) + section_headers + payloads


@pytest.mark.parametrize("level", [0, 1, 2])
def test_pinned_official_vectors_match_independent_oracle(level):
    data = _official_vector(level)
    _assert_matches_oracle(_core.read_ksplat(data), _oracle_decode(data))


@pytest.mark.parametrize("degree", [0, 1, 2])
@pytest.mark.parametrize("level", [0, 1, 2])
def test_writer_is_deterministic_and_independently_decodable(level, degree):
    cloud = _cloud(degree=degree)
    first = _core.write_ksplat(cloud, level)
    second = _core.write_ksplat(cloud, level)
    assert first == second
    _assert_matches_oracle(_core.read_ksplat(first), _oracle_decode(first))


def test_randomized_valid_differential_and_partial_sweep():
    for seed in range(20):
        rng = np.random.default_rng(seed)
        count = int(rng.integers(1, 50))
        degree = seed % 3
        level = (seed // 3) % 3
        coefficients = (0, 9, 24)[degree]
        quaternions = rng.standard_normal((count, 4)).astype(np.float32)
        arrays = (
            rng.uniform(-10, 10, (count, 3)).astype(np.float32),
            rng.uniform(-3, 3, (count, 3)).astype(np.float32),
            quaternions,
            rng.uniform(-10, 10, count).astype(np.float32),
            rng.uniform(-2, 2, (count, 3)).astype(np.float32),
        )
        if coefficients:
            cloud = _core.gaussian_cloud(
                *arrays,
                rng.uniform(-1, 1, (count, coefficients)).astype(
                    np.float32
                ),
            )
        else:
            cloud = _core.gaussian_cloud(*arrays)
        data = _core.write_ksplat(
            cloud,
            level,
            (0.5, 2.0, 5.0)[seed % 3],
            (1, 3, 16)[seed % 3],
        )
        decoded = _core.read_ksplat(data)
        _assert_matches_oracle(decoded, _oracle_decode(data))
        start = seed % count
        stop = min(count, start + 1 + seed % 7)
        selected = _core.read_ksplat_points(data, start, stop)
        for field in (
            "means",
            "scales",
            "quaternions",
            "opacities",
            "sh_dc",
            "sh_rest",
        ):
            np.testing.assert_array_equal(
                getattr(selected, field),
                getattr(decoded, field)[start:stop],
            )


@pytest.mark.parametrize("level", [0, 1, 2])
def test_point_range_is_exact_slice(level):
    full = _core.read_ksplat(_core.write_ksplat(_cloud(), level))
    partial = _core.read_ksplat_points(
        _core.write_ksplat(_cloud(), level), 7, 29
    )
    for field in (
        "means",
        "scales",
        "quaternions",
        "opacities",
        "sh_dc",
        "sh_rest",
    ):
        np.testing.assert_array_equal(
            getattr(partial, field), getattr(full, field)[7:29]
        )


def test_multisection_ranges_before_within_and_across_sections():
    first_data = _core.write_ksplat(_cloud(5, 0), 0)
    second_data = _core.write_ksplat(_cloud(7, 0), 0)
    data = _merge_single_section_files(first_data, second_data)
    full = _core.read_ksplat(data)
    expected_parts = [
        _core.read_ksplat(first_data),
        _core.read_ksplat(second_data),
    ]
    for field in (
        "means",
        "scales",
        "quaternions",
        "opacities",
        "sh_dc",
        "sh_rest",
    ):
        expected = np.concatenate(
            [np.asarray(getattr(part, field)) for part in expected_parts]
        )
        np.testing.assert_array_equal(getattr(full, field), expected)
        for start, stop in ((0, 3), (5, 9), (4, 12)):
            selected = _core.read_ksplat_points(data, start, stop)
            np.testing.assert_array_equal(
                getattr(selected, field), expected[start:stop]
            )


def test_buffer_protocol_readonly_and_mutation_isolation(tmp_path):
    data = bytearray(_core.write_ksplat(_cloud(), 2))
    expected = np.asarray(
        _core.read_ksplat(memoryview(data).toreadonly()).means
    ).copy()
    readonly = _core.read_ksplat(memoryview(data).toreadonly())
    np.testing.assert_array_equal(readonly.means, expected)
    path = tmp_path / "cloud.ksplat"
    path.write_bytes(data)
    with path.open("rb") as stream, mmap.mmap(
        stream.fileno(), 0, access=mmap.ACCESS_READ
    ) as mapped:
        decoded = _core.read_ksplat(mapped)
    path.unlink()
    gc.collect()
    data[:] = b"\0" * len(data)
    np.testing.assert_array_equal(decoded.means, expected)


def test_metadata_inspection_validates_extent_without_payload_decode():
    data = _core.write_ksplat(_cloud(), 2)
    section_count = struct.unpack_from("<I", data, 4)[0]
    extent = HEADER_SIZE + section_count * SECTION_HEADER_SIZE
    metadata = _core._inspect_ksplat_metadata(data[:extent], len(data))
    assert metadata[:6] == (73, 2, 2, 1, 1, 73)
    assert metadata[6:9] == (0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="trailing bytes"):
        _core._inspect_ksplat_metadata(data[:extent], len(data) + 1)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda d: d.__setitem__(0, 1), "unsupported version"),
        (
            lambda d: struct.pack_into("<H", d, 20, 3),
            "compression level",
        ),
        (
            lambda d: struct.pack_into("<I", d, 8, 2),
            "sectionCount exceeds",
        ),
        (
            lambda d: struct.pack_into("<I", d, HEADER_SIZE + 28, 1),
            "storageSizeBytes",
        ),
        (
            lambda d: struct.pack_into("<I", d, HEADER_SIZE + 36, 0),
            "bucket counts",
        ),
    ],
)
def test_malformed_headers_are_rejected(mutation, message):
    data = bytearray(_core.write_ksplat(_cloud(), 2))
    mutation(data)
    with pytest.raises(ValueError, match=message):
        _core.read_ksplat(memoryview(data).toreadonly())


def test_malformed_bucket_and_record_values_are_rejected():
    original = _core.write_ksplat(_cloud(), 2)
    partial = struct.unpack_from("<I", original, HEADER_SIZE + 36)[0]
    buckets = struct.unpack_from("<I", original, HEADER_SIZE + 12)[0]
    center_base = HEADER_SIZE + SECTION_HEADER_SIZE + partial * 4
    data_base = center_base + buckets * 12

    invalid = bytearray(original)
    struct.pack_into("<I", invalid, HEADER_SIZE + SECTION_HEADER_SIZE, 0)
    with pytest.raises(ValueError, match="partially-filled bucket length"):
        _core.read_ksplat(memoryview(invalid).toreadonly())

    invalid = bytearray(original)
    struct.pack_into("<f", invalid, center_base, math.nan)
    with pytest.raises(ValueError, match="bucket center"):
        _core.read_ksplat(memoryview(invalid).toreadonly())

    invalid = bytearray(original)
    struct.pack_into("<H", invalid, data_base + 6, 0x7C00)
    with pytest.raises(ValueError, match="scale"):
        _core.read_ksplat(memoryview(invalid).toreadonly())

    invalid = bytearray(original)
    invalid[data_base + 12 : data_base + 20] = b"\0" * 8
    with pytest.raises(ValueError, match="quaternion"):
        _core.read_ksplat(memoryview(invalid).toreadonly())

    invalid = bytearray(original)
    struct.pack_into("<ff", invalid, 36, 2.0, 1.0)
    with pytest.raises(ValueError, match="reversed SH"):
        _core.read_ksplat(memoryview(invalid).toreadonly())


def test_float16_subnormal_scale_decodes_without_exponent_loss():
    data = bytearray(_core.write_ksplat(_cloud(degree=0), 1))
    partial = struct.unpack_from("<I", data, HEADER_SIZE + 36)[0]
    buckets = struct.unpack_from("<I", data, HEADER_SIZE + 12)[0]
    data_base = (
        HEADER_SIZE
        + SECTION_HEADER_SIZE
        + partial * 4
        + buckets * 12
    )
    struct.pack_into("<H", data, data_base + 6, 1)
    decoded = _core.read_ksplat(memoryview(data).toreadonly())
    expected = np.log(np.float32(2**-24))
    assert decoded.scales[0, 0] == expected


def test_writer_handles_planar_exact_block_boundaries_without_bucket_aliasing():
    means = np.asarray(
        [[0, 0, 0], [5, 0, 0], [0, 5, 0], [5, 5, 0]],
        dtype=np.float32,
    )
    cloud = _core.gaussian_cloud(
        means,
        np.zeros((4, 3), np.float32),
        np.tile(np.array([[1, 0, 0, 0]], np.float32), (4, 1)),
        np.zeros(4, np.float32),
        np.zeros((4, 3), np.float32),
    )
    decoded = _core.read_ksplat(_core.write_ksplat(cloud, 1, 5.0, 256))
    actual = np.asarray(decoded.means)
    actual = actual[np.lexsort((actual[:, 2], actual[:, 1], actual[:, 0]))]
    expected = means[np.lexsort((means[:, 2], means[:, 1], means[:, 0]))]
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-4)


@pytest.mark.parametrize("cut", [0, 1, 4095, 4096, 5119])
def test_truncation_and_trailing_bytes_are_rejected(cut):
    data = _core.write_ksplat(_cloud(), 1)
    with pytest.raises(ValueError, match="truncated"):
        _core.read_ksplat(data[:cut])
    with pytest.raises(ValueError, match="trailing bytes"):
        _core.read_ksplat(data + b"x")


def test_writer_guards_unrepresentable_clouds_and_options():
    cloud = _cloud()
    with pytest.raises(ValueError, match="compression_level"):
        _core.write_ksplat(cloud, 3)
    with pytest.raises(ValueError, match="block_size"):
        _core.write_ksplat(cloud, 1, 0.0)
    with pytest.raises(ValueError, match="bucket_size"):
        _core.write_ksplat(cloud, 1, 5.0, 0)

    degree3 = _core.gaussian_cloud(
        np.asarray(cloud.means),
        np.asarray(cloud.scales),
        np.asarray(cloud.quaternions),
        np.asarray(cloud.opacities),
        np.asarray(cloud.sh_dc),
        np.zeros((cloud.num_gaussians, 45), dtype=np.float32),
    )
    with pytest.raises(ValueError, match="degree above 2"):
        _core.write_ksplat(degree3)

    def replaced(field: str, value: float):
        arrays = {
            "means": np.asarray(cloud.means).copy(),
            "scales": np.asarray(cloud.scales).copy(),
            "quaternions": np.asarray(cloud.quaternions).copy(),
            "opacities": np.asarray(cloud.opacities).copy(),
            "sh_dc": np.asarray(cloud.sh_dc).copy(),
            "sh_rest": np.asarray(cloud.sh_rest).copy(),
        }
        arrays[field].flat[0] = value
        return _core.gaussian_cloud(
            arrays["means"],
            arrays["scales"],
            arrays["quaternions"],
            arrays["opacities"],
            arrays["sh_dc"],
            arrays["sh_rest"],
        )

    for field in ("means", "scales", "sh_dc", "sh_rest"):
        with pytest.raises(ValueError):
            _core.write_ksplat(replaced(field, math.nan))
    with pytest.raises(ValueError, match="opacities"):
        _core.write_ksplat(replaced("opacities", math.nan))
    with pytest.raises(ValueError, match="quaternion"):
        _core.write_ksplat(replaced("quaternions", math.inf))

    zero = np.asarray(cloud.quaternions).copy()
    zero[0] = 0
    invalid = _core.gaussian_cloud(
        np.asarray(cloud.means),
        np.asarray(cloud.scales),
        zero,
        np.asarray(cloud.opacities),
        np.asarray(cloud.sh_dc),
        np.asarray(cloud.sh_rest),
    )
    with pytest.raises(ValueError, match="quaternion"):
        _core.write_ksplat(invalid)


def test_empty_cloud_round_trip():
    empty = _core.gaussian_cloud(
        np.empty((0, 3), dtype=np.float32),
        np.empty((0, 3), dtype=np.float32),
        np.empty((0, 4), dtype=np.float32),
        np.empty(0, dtype=np.float32),
        np.empty((0, 3), dtype=np.float32),
    )
    decoded = _core.read_ksplat(_core.write_ksplat(empty))
    assert decoded.num_gaussians == 0
    assert decoded.sh_degree == 0


def test_generated_100mb_fixture_partial_allocation_is_bounded():
    count = 2_400_000
    record = struct.pack(
        "<3f3f4f4B",
        0.0,
        0.0,
        0.0,
        1.0,
        1.0,
        1.0,
        1.0,
        0.0,
        0.0,
        0.0,
        128,
        128,
        128,
        128,
    )
    header = bytearray(HEADER_SIZE + SECTION_HEADER_SIZE)
    header[:2] = b"\0\1"
    struct.pack_into("<4I", header, 4, 1, 1, count, count)
    struct.pack_into("<2I", header, HEADER_SIZE, count, count)
    struct.pack_into("<I", header, HEADER_SIZE + 28, count * len(record))
    data = bytes(header) + record * count
    assert len(data) > 100 * 1024 * 1024

    tracemalloc.start()
    partial = _core.read_ksplat_points(
        memoryview(data), count - 8, count
    )
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert partial.num_gaussians == 8
    assert peak < 4 * 1024 * 1024
