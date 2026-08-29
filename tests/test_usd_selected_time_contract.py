"""Machine checks for the bounded USD selected-time state-B contract."""

from __future__ import annotations

import inspect
import tomllib
from pathlib import Path

import sceneio
from sceneio.io._usd import animation, provider

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = tomllib.loads(
    (ROOT / "tests/contracts/usd_selected_time_v1.toml").read_text(
        encoding="utf-8"
    )
)


def test_usd_selected_time_contract_matches_api_and_provider_boundary():
    assert CONTRACT["schema_version"] == 1
    assert CONTRACT["close_state"] == "B_selected_time_read_only"
    assert CONTRACT["profile"] == provider.PROFILE_ID
    assert provider.PROVIDER_FLAGS["selected_time"] is True
    assert "SceneAnimation" not in sceneio.__all__
    assert tuple(inspect.signature(sceneio.read_scene).parameters) == (
        "path",
        "time",
        "prims",
        "purposes",
        "variants",
        "load_payloads",
    )


def test_usd_selected_time_contract_matches_parser_limits():
    limits = CONTRACT["limits"]
    assert limits["max_prim_text_chars"] == animation._MAX_PRIM_TEXT_CHARS
    assert limits["max_line_chars"] == animation._MAX_LINE_CHARS
    assert limits["max_samples_per_property"] == (
        animation._MAX_SAMPLES_PER_PROPERTY
    )
    assert limits["max_tokens_per_property"] == (
        animation._MAX_TOKENS_PER_PROPERTY
    )
    assert limits["max_string_chars"] == animation._MAX_STRING_CHARS


def test_usd_selected_time_contract_matches_capabilities():
    for format_id in ("usd", "usdz"):
        capabilities = sceneio.capabilities(format_id)
        assert {
            "direct_usda_selected_time",
            "matrix_transform_time_samples",
            "visibility_time_samples",
        } <= set(capabilities.supported_features)
        assert {
            "authored_animation_preservation",
            "dynamic_write",
            "usdc_selected_time",
            "time_varying_payloads",
            "arbitrary_sampled_xform_stacks",
        } <= set(capabilities.unsupported_features)


def test_usd_selected_time_contract_has_oracle_benchmark_and_docs():
    oracle = CONTRACT["oracle"]
    assert oracle["provider"] == "OpenUSD 26.08"
    assert (ROOT / oracle["suite"]).is_file()
    workflow = (ROOT / ".github/workflows/oracle-openusd.yml").read_text(
        encoding="utf-8"
    )
    assert "test_openusd_animation_oracle.py" in workflow
    assert (ROOT / CONTRACT["benchmark"]["implementation"]).is_file()
    assert (ROOT / CONTRACT["benchmark"]["evidence"]).is_file()
    benchmark = CONTRACT["benchmark"]
    assert benchmark["large_fixture_min_bytes"] == 64 * 1024 * 1024
    assert benchmark["fresh_process_protocol"] == (
        "sceneio-fresh-child-memory-v1"
    )
    assert benchmark["fresh_process_samples"] == 3
