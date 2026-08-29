"""Console reporting for the SceneIO I/O benchmark."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence


def print_json_result(result: object) -> None:
    """Print one structured result using the benchmark's existing JSON style."""

    print(json.dumps(result, indent=2))


def print_primary_header() -> None:
    """Print the primary codec table header."""

    header = (
        f"{'codec':<14}{'payloadMB':>10}{'fileMB':>9}{'sioW':>9}{'sioR':>9}"
        f"{'pathR':>9}{'oraW':>9}{'oraR':>9}{'bPeakMB':>9}{'mPeakMB':>9}"
        f"{'bRSSMB':>9}{'mRSSMB':>9}{'sio/ora':>9}"
    )
    print(header)
    print("-" * len(header))


def print_primary_row(
    codec_id: str,
    payload_mb: float,
    file_mb: float,
    write_mbps: float,
    read_mbps: float,
    path_read_mbps: float,
    oracle_write_mbps: float | None,
    oracle_read_mbps: float | None,
    bytes_peak_mb: float,
    mmap_peak_mb: float,
    bytes_rss_mb: float,
    mmap_rss_mb: float,
    ratio: float | None,
) -> None:
    """Print one ordinary primary-table row."""

    print(
        f"{codec_id:<14}{payload_mb:>10.1f}{file_mb:>9.1f}"
        f"{write_mbps:>9.0f}{read_mbps:>9.0f}{path_read_mbps:>9.0f}"
        f"{(oracle_write_mbps or 0):>9.0f}{(oracle_read_mbps or 0):>9.0f}"
        f"{bytes_peak_mb:>9.1f}{mmap_peak_mb:>9.1f}"
        f"{bytes_rss_mb:>9.1f}{mmap_rss_mb:>9.1f}{(ratio or 0):>9.2f}"
    )


def print_typed_adapter(metrics: Mapping[str, object]) -> None:
    """Print the compact typed-adapter detail line."""

    print(
        f"  {metrics['format']} typed adapter:"
        f" read={metrics['read_mbps']:.0f} MB/s"
        f" write={metrics['write_mbps']:.0f} MB/s"
        f" inspect={metrics['inspect_ms']:.3f} ms"
        f" traced read/write="
        f"{metrics['read_peak_mb']:.3f}/"
        f"{metrics['write_peak_mb']:.3f} MB"
    )


def print_encoding_variants(
    label: str,
    variants: Mapping[str, Mapping[str, float]],
    *,
    noun: str = "encodings",
) -> None:
    """Print one compact codec-variant summary."""

    summary = ", ".join(
        f"{encoding}: W={metrics['write_mbps']:.0f}/"
        f"R={metrics['read_mbps']:.0f} MB/s"
        for encoding, metrics in variants.items()
    )
    print(f"  {label} {noun}: {summary}")


def print_colmap_db_row(display: Sequence[float | None]) -> None:
    """Print the COLMAP database row, whose byte-path columns are unavailable."""

    (
        payload_mb,
        file_mb,
        write_mbps,
        read_mbps,
        oracle_write_mbps,
        oracle_read_mbps,
        read_peak_mb,
        read_rss_mb,
    ) = display
    print(
        f"{'colmap_db':<14}{payload_mb:>10.1f}{file_mb:>9.1f}"
        f"{write_mbps:>9.0f}{read_mbps:>9.0f}{read_mbps:>9.0f}"
        f"{(oracle_write_mbps or 0):>9.0f}{(oracle_read_mbps or 0):>9.0f}"
        f"{'-':>9}{read_peak_mb:>9.1f}{'-':>9}{read_rss_mb:>9.1f}{'-':>9}"
    )


def print_path_row(
    codec_id: str,
    display: Sequence[float | None],
) -> None:
    """Print one path-native row with independent path-provider metrics."""

    (
        payload_mb,
        file_mb,
        write_mbps,
        read_mbps,
        oracle_write_mbps,
        oracle_read_mbps,
        read_peak_mb,
        read_rss_mb,
    ) = display
    ratio = (
        read_mbps / oracle_read_mbps
        if oracle_read_mbps is not None
        else None
    )
    print(
        f"{codec_id:<14}{payload_mb:>10.1f}{file_mb:>9.1f}"
        f"{write_mbps:>9.0f}{read_mbps:>9.0f}{read_mbps:>9.0f}"
        f"{(oracle_write_mbps or 0):>9.0f}{(oracle_read_mbps or 0):>9.0f}"
        f"{'-':>9}{read_peak_mb:>9.1f}{'-':>9}{read_rss_mb:>9.1f}"
        f"{(ratio or 0):>9.2f}"
    )


def print_directory_row(
    codec_id: str,
    payload_mb: float,
    file_mb: float,
    write_mbps: float,
    read_mbps: float,
    path_read_mbps: float,
    read_peak_mb: float,
    read_rss_mb: float,
) -> None:
    """Print one directory-backed codec row."""

    print(
        f"{codec_id:<14}{payload_mb:>10.1f}{file_mb:>9.1f}{write_mbps:>9.0f}"
        f"{read_mbps:>9.0f}{path_read_mbps:>9.0f}"
        f"{'-':>9}{'-':>9}{'-':>9}{read_peak_mb:>9.1f}"
        f"{'-':>9}{read_rss_mb:>9.1f}{'-':>9}"
    )


def print_primary_error(codec_id: str, error: Exception) -> None:
    """Print one primary-table failure row."""

    print(f"{codec_id:<14} ERROR: {type(error).__name__}: {error}")


def print_summary(
    write_rows: Sequence[tuple],
    o4_rows: Sequence[tuple],
    inspect_rows: Sequence[tuple],
    partial_rows: Sequence[tuple],
) -> None:
    """Print the O1/O3/O4/O5 explanatory and comparison tables."""

    print("\nMB/s over raw payload; fileMB = encoded size (= the whole-file copy O1/O3 remove).")
    print("sioR = in-memory copy decode; pathR = public registry mmap read/view.")
    print("bPeakMB/mPeakMB = peak Python allocation for bytes/mmap reads (O1 delta).")
    print("bRSSMB/mRSSMB = sampled resident-set growth for bytes/mmap reads.")
    print("\nO3 write-path delta:")
    write_header = (
        f"{'codec':<18}{'payloadMB':>10}{'fileMB':>9}{'bytesW':>9}{'sinkW':>9}"
        f"{'bPeakMB':>9}{'sPeakMB':>9}{'bRSSMB':>9}{'sRSSMB':>9}"
    )
    print(write_header)
    print("-" * len(write_header))
    for row in write_rows:
        codec_id, pmb, fmb, bufw, sinkw, bpeak, speak, brss, srss = row
        print(
            f"{codec_id:<18}{pmb:>10.1f}{fmb:>9.1f}"
            f"{(f'{bufw:.0f}' if bufw is not None else '-'):>9}"
            f"{sinkw:>9.0f}"
            f"{(f'{bpeak:.1f}' if bpeak is not None else '-'):>9}"
            f"{speak:>9.1f}"
            f"{(f'{brss:.1f}' if brss is not None else '-'):>9}"
            f"{srss:>9.1f}"
        )
    print("bytesW/sinkW = legacy bytes+file/public file-sink write MB/s.")
    print("bPeakMB/sPeakMB = peak Python allocation for bytes/file-sink writes (O3 delta).")
    print("bRSSMB/sRSSMB = sampled resident-set growth for bytes/file-sink writes.")
    print("\nO4 one-lane/old-setting delta:")
    o4_header = (
        f"{'codec':<12}{'operation':<18}{'base MB/s':>12}"
        f"{'opt MB/s':>12}{'gain':>9}{'identity':>11}"
    )
    print(o4_header)
    print("-" * len(o4_header))
    for codec_id, operation, base, optimized, identity in o4_rows:
        print(
            f"{codec_id:<12}{operation:<18}{base:>12.0f}"
            f"{optimized:>12.0f}{optimized / base:>8.2f}x"
            f"{identity:>11}"
        )
    print(
        "Identity is encoded bytes where compression settings are unchanged; "
        "otherwise decoded values/pixels."
    )
    print("\nO5 metadata-only inspection delta:")
    inspect_header = (
        f"{'codec':<18}{'full ms':>11}{'inspect ms':>12}{'speedup':>10}"
        f"{'fullPeak':>11}{'inspPeak':>10}{'fullRSS':>10}{'inspRSS':>9}"
    )
    print(inspect_header)
    print("-" * len(inspect_header))
    for codec_id, full, inspected, full_peak, inspected_peak, full_rss, inspected_rss in (
        inspect_rows
    ):
        print(
            f"{codec_id:<18}{full * 1000:>11.3f}{inspected * 1000:>12.3f}"
            f"{full / inspected:>9.2f}x{full_peak:>11.1f}{inspected_peak:>10.1f}"
            f"{full_rss:>10.1f}{inspected_rss:>9.1f}"
        )
    print("Inspection reads headers/streamed metadata and constructs no compiled record arrays.")
    print("\nO5 partial-read delta:")
    partial_header = (
        f"{'codec':<18}{'full ms':>11}{'partial ms':>12}{'speedup':>10}"
        f"{'fullPeak':>11}{'partPeak':>10}{'fullRSS':>10}{'partRSS':>9}"
    )
    print(partial_header)
    print("-" * len(partial_header))
    for codec_id, full, partial_time, full_peak, part_peak, full_rss, part_rss in partial_rows:
        print(
            f"{codec_id:<18}{full * 1000:>11.3f}{partial_time * 1000:>12.3f}"
            f"{full / partial_time:>9.2f}x{full_peak:>11.1f}{part_peak:>10.1f}"
            f"{full_rss:>10.1f}{part_rss:>9.1f}"
        )
    print(
        "Partial reads return the normal record type while materializing only "
        "the selected pixel, point, face, state, frame, tensor, COLMAP-image, or "
        "match-pair subset."
    )


def print_regression_guard_passed() -> None:
    """Print the complete-sweep guard confirmation."""

    print(
        "CI regression guard: stable O4 gains and mmap/sink memory "
        "bounds passed."
    )


def print_cold_cache_unavailable() -> None:
    """Print the existing platform fallback notice."""

    print("WARNING: this platform has no POSIX_FADV_DONTNEED; cold-cache hint was unavailable.")
