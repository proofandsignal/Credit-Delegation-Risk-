import json
from datetime import datetime, timedelta, timezone

import pytest

from credit_delegation_risk.observer import (
    AAVE_V3_ETHEREUM_POOL,
    DECISION_ARTIFACT_SHA256,
    T0_AT,
    T0_BLOCK,
    T0_DATASET_SHA256,
    aggregate_checkpoint,
    verify_liquidation_receipt,
)


class ReceiptRpc:
    def keccak_text(self, text: str) -> str:
        return "0x" + "aa" * 32

    def transaction_receipt(self, tx_hash: str) -> dict:
        wallet = "0x" + "11" * 20
        return {
            "logs": [
                {
                    "address": AAVE_V3_ETHEREUM_POOL,
                    "topics": [
                        "0x" + "aa" * 32,
                        "0x" + "00" * 12 + "22" * 20,
                        "0x" + "00" * 12 + "33" * 20,
                        "0x" + "00" * 12 + wallet[2:],
                    ],
                }
            ]
        }


def _decisions() -> dict:
    records = []
    for index in range(1, 51):
        label = "APPROVE_PAPER"
        score = 90
        probability = 0.02
        if index == 50:
            label = "REJECT_PAPER"
            score = 30
            probability = 0.20
        records.append(
            {
                "decision_id": f"D-{index:03d}",
                "wallet_address": f"0x{index:040x}",
                "paper_decision": label,
                "risk_score": score,
                "model_risk_probability": probability,
            }
        )
    return {"record_count": 50, "records": records}


def _observation(day: int, unhealthy_wallet: int | None = None) -> dict:
    t0 = datetime.fromisoformat(T0_AT)
    observed = t0 + timedelta(days=day, minutes=20)
    records = []
    for index in range(1, 51):
        hf = 1.50
        if unhealthy_wallet == index:
            hf = 0.99
        records.append(
            {
                "decision_id": f"D-{index:03d}",
                "wallet_address": f"0x{index:040x}",
                "paper_decision": "APPROVE_PAPER" if index != 50 else "REJECT_PAPER",
                "risk_score": 90 if index != 50 else 30,
                "model_risk_probability": 0.02 if index != 50 else 0.20,
                "observed_block": T0_BLOCK + day * 100,
                "observed_block_hash": "0x" + f"{day:064x}",
                "observed_at": observed.isoformat(),
                "collateral_usd": 10_000.0,
                "active_debt_usd": 4_000.0,
                "health_factor": hf,
                "collateral_drawdown_pct_from_t0": 0.0,
                "sampled_health_factor_below_1_0": hf < 1.0,
                "liquidation_event_since_t0": False,
                "liquidation_tx_hashes": [],
                "state_evidence_ref": f"evidence://day/{day}/wallet/{index}",
            }
        )
    return {
        "dataset": "forward50-daily-observation",
        "observer_version": "forward-outcome-observer-v0.3.0",
        "source_t0_sha256": T0_DATASET_SHA256,
        "source_decision_sha256": DECISION_ARTIFACT_SHA256,
        "model_version": "forward-position-risk-v0.2.0",
        "t0_block": T0_BLOCK,
        "t0_at": T0_AT,
        "observed_block": T0_BLOCK + day * 100,
        "observed_block_hash": "0x" + f"{day:064x}",
        "observed_at": observed.isoformat(),
        "record_count": 50,
        "records": records,
    }


def test_liquidation_receipt_requires_matching_user_topic():
    wallet = "0x" + "11" * 20
    assert verify_liquidation_receipt(
        ReceiptRpc(),
        tx_hash="0x" + "99" * 32,
        wallet_address=wallet,
    ) is True
    assert verify_liquidation_receipt(
        ReceiptRpc(),
        tx_hash="0x" + "99" * 32,
        wallet_address="0x" + "44" * 20,
    ) is False


def test_t30_checkpoint_detects_temporary_hf_breach_as_false_negative():
    observations = [
        _observation(day, unhealthy_wallet=1 if day == 15 else None)
        for day in range(1, 31)
    ]
    checkpoint = aggregate_checkpoint(
        decisions_payload=_decisions(),
        observation_payloads=observations,
        horizon_days=30,
    )

    assert checkpoint["status"] == "COMPLETE"
    assert checkpoint["coverage"]["coverage_ratio"] == 1.0
    assert checkpoint["overall_performance"]["primary_events"] == 1
    assert checkpoint["false_negative_count"] == 1

    wallet_one = next(
        row
        for row in checkpoint["records"]
        if row["wallet_address"] == f"0x{1:040x}"
    )
    assert wallet_one["min_health_factor"] == 0.99
    assert wallet_one["final_health_factor"] == 1.50
    assert wallet_one["primary_adverse_event"] is True


def test_checkpoint_is_incomplete_below_80_percent_coverage():
    observations = [_observation(day) for day in range(1, 21)]
    observations.append(_observation(30))

    checkpoint = aggregate_checkpoint(
        decisions_payload=_decisions(),
        observation_payloads=observations,
        horizon_days=30,
    )

    assert checkpoint["coverage"]["coverage_ratio"] < 0.8
    assert checkpoint["status"] == "INCOMPLETE"


def test_checkpoint_requires_final_sample_after_target():
    observations = [_observation(day) for day in range(1, 30)]

    checkpoint = aggregate_checkpoint(
        decisions_payload=_decisions(),
        observation_payloads=observations,
        horizon_days=30,
    )

    assert checkpoint["checkpoint_observed_at"] is None
    assert checkpoint["status"] == "INCOMPLETE"


def test_prior_checkpoint_preserves_earlier_minimum_health_factor():
    first_window = [
        _observation(day, unhealthy_wallet=2 if day == 10 else None)
        for day in range(1, 31)
    ]
    t30 = aggregate_checkpoint(
        decisions_payload=_decisions(),
        observation_payloads=first_window,
        horizon_days=30,
    )
    second_window = [_observation(day) for day in range(31, 61)]

    t60 = aggregate_checkpoint(
        decisions_payload=_decisions(),
        observation_payloads=second_window,
        horizon_days=60,
        prior_checkpoint=t30,
    )

    wallet_two = next(
        row
        for row in t60["records"]
        if row["wallet_address"] == f"0x{2:040x}"
    )
    assert t60["status"] == "COMPLETE"
    assert wallet_two["min_health_factor"] == 0.99
    assert wallet_two["primary_adverse_event"] is True
