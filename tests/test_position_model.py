import hashlib
import json

import pytest

from credit_delegation_risk.position_model import (
    MODEL_VERSION,
    PROBABILITY_SEMANTICS,
    assess_position,
    build_frozen_decisions,
    freeze_decisions_file,
)


def _record(
    *,
    wallet_suffix: int = 1,
    health_factor: float = 2.0,
    debt: float = 2_000,
    collateral: float = 5_000,
    history_days: int = 365,
) -> dict:
    return {
        "wallet_address": f"0x{wallet_suffix:040x}",
        "snapshot_block": 26_167_261,
        "snapshot_block_hash": "0x" + "ab" * 32,
        "snapshot_at": "2026-10-11T05:57:11+00:00",
        "protocol_history_days": history_days,
        "collateral_usd": collateral,
        "active_debt_usd": debt,
        "health_factor": health_factor,
    }


def test_high_health_factor_position_gets_no_hf_penalty():
    result = assess_position(_record(health_factor=2.5, debt=1_000, collateral=10_000))
    assert result.risk_score == 100
    assert result.paper_decision == "APPROVE_PAPER"
    assert result.model_risk_probability == 0.01
    assert result.probability_semantics == PROBABILITY_SEMANTICS


def test_near_liquidation_position_is_not_approved():
    result = assess_position(
        _record(health_factor=1.02, debt=9_000, collateral=10_000, history_days=100)
    )
    assert result.risk_score < 55
    assert result.paper_decision == "REJECT_PAPER"
    assert "health_factor_under_1_05" in result.reason_codes
    assert "debt_to_collateral_over_0_85" in result.reason_codes


def test_model_is_deterministic():
    first = assess_position(_record())
    second = assess_position(_record())
    assert first == second
    assert first.model_version == MODEL_VERSION
    assert len(first.decision_id) == 24


def test_forward50_builder_requires_exactly_50_unique_positions():
    with pytest.raises(ValueError, match="exactly 50"):
        build_frozen_decisions({"record_count": 1, "records": [_record()]})


def test_freeze_file_hashes_exact_source_bytes(tmp_path):
    records = [_record(wallet_suffix=index) for index in range(1, 51)]
    payload = {"dataset": "forward50-t0", "record_count": 50, "records": records}
    source = tmp_path / "t0.json"
    source_bytes = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    source.write_bytes(source_bytes)

    output = tmp_path / "decisions.json"
    summary = freeze_decisions_file(source, output)

    assert summary["records"] == 50
    assert summary["source_dataset_sha256"] == hashlib.sha256(source_bytes).hexdigest()
    assert output.exists()
