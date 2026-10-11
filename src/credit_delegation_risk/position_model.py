from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


MODEL_VERSION = "forward-position-risk-v0.2.0"
PROBABILITY_SEMANTICS = (
    "proxy_probability_of_registered_onchain_adverse_credit_risk_event_"
    "not_borrower_default"
)


@dataclass(frozen=True)
class PositionRiskDecision:
    decision_id: str
    wallet_address: str
    snapshot_block: int
    snapshot_block_hash: str
    snapshot_at: str
    protocol_history_days: int
    collateral_usd: float
    active_debt_usd: float
    health_factor: float
    debt_to_collateral: float
    model_version: str
    risk_score: int
    paper_decision: str
    model_risk_probability: float
    probability_semantics: str
    reason_codes: tuple[str, ...]


def _decision_id(wallet_address: str, snapshot_block: int) -> str:
    payload = f"{MODEL_VERSION}|{wallet_address.lower()}|{snapshot_block}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def assess_position(record: dict[str, Any]) -> PositionRiskDecision:
    collateral = float(record["collateral_usd"])
    debt = float(record["active_debt_usd"])
    health_factor = float(record["health_factor"])
    history_days = int(record["protocol_history_days"])

    if collateral <= 0:
        raise ValueError("collateral_usd must be > 0")
    if debt < 0:
        raise ValueError("active_debt_usd must be >= 0")
    if health_factor <= 0:
        raise ValueError("health_factor must be > 0")
    if history_days < 0:
        raise ValueError("protocol_history_days must be >= 0")

    debt_to_collateral = debt / collateral
    penalties: list[tuple[str, int]] = []

    if health_factor < 1.05:
        penalties.append(("health_factor_under_1_05", 55))
    elif health_factor < 1.10:
        penalties.append(("health_factor_under_1_10", 45))
    elif health_factor < 1.25:
        penalties.append(("health_factor_under_1_25", 30))
    elif health_factor < 1.50:
        penalties.append(("health_factor_under_1_50", 20))
    elif health_factor < 2.00:
        penalties.append(("health_factor_under_2_00", 10))

    if debt_to_collateral > 0.85:
        penalties.append(("debt_to_collateral_over_0_85", 20))
    elif debt_to_collateral > 0.70:
        penalties.append(("debt_to_collateral_over_0_70", 12))
    elif debt_to_collateral > 0.50:
        penalties.append(("debt_to_collateral_over_0_50", 5))

    if history_days < 120:
        penalties.append(("protocol_history_under_120d", 8))
    elif history_days < 180:
        penalties.append(("protocol_history_under_180d", 4))

    score = max(0, min(100, 100 - sum(value for _, value in penalties)))

    if score >= 70:
        paper_decision = "APPROVE_PAPER"
    elif score >= 55:
        paper_decision = "REVIEW_PAPER"
    else:
        paper_decision = "REJECT_PAPER"

    probability = 0.01 + (((100 - score) / 100) ** 2) * 0.34
    probability = round(min(max(probability, 0.01), 0.35), 4)

    reasons = tuple(
        name for name, _ in sorted(penalties, key=lambda item: item[1], reverse=True)
    )

    return PositionRiskDecision(
        decision_id=_decision_id(record["wallet_address"], int(record["snapshot_block"])),
        wallet_address=record["wallet_address"].lower(),
        snapshot_block=int(record["snapshot_block"]),
        snapshot_block_hash=record["snapshot_block_hash"],
        snapshot_at=record["snapshot_at"],
        protocol_history_days=history_days,
        collateral_usd=round(collateral, 2),
        active_debt_usd=round(debt, 2),
        health_factor=round(health_factor, 8),
        debt_to_collateral=round(debt_to_collateral, 8),
        model_version=MODEL_VERSION,
        risk_score=score,
        paper_decision=paper_decision,
        model_risk_probability=probability,
        probability_semantics=PROBABILITY_SEMANTICS,
        reason_codes=reasons,
    )


def build_frozen_decisions(t0_payload: dict[str, Any]) -> dict[str, Any]:
    records = t0_payload.get("records", [])
    if t0_payload.get("record_count") != 50 or len(records) != 50:
        raise ValueError("Forward 50 T0 source must contain exactly 50 records")

    source_bytes = (json.dumps(t0_payload, indent=2) + "\n").encode("utf-8")
    decisions = [assess_position(record) for record in records]

    wallets = [item.wallet_address for item in decisions]
    if len(set(wallets)) != 50:
        raise ValueError("Forward 50 decision source must contain 50 unique wallets")

    return {
        "dataset": "forward50-t0-frozen-decisions",
        "model_version": MODEL_VERSION,
        "model_semantics": PROBABILITY_SEMANTICS,
        "source_dataset_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "snapshot_block": decisions[0].snapshot_block,
        "snapshot_block_hash": decisions[0].snapshot_block_hash,
        "snapshot_at": decisions[0].snapshot_at,
        "record_count": len(decisions),
        "model_registration": {
            "t0_cohort_data_seen": True,
            "future_outcome_data_seen": False,
            "pre_cohort_preregistered": False,
            "note": (
                "Baseline model frozen after cohort T0 collection but before any "
                "T+30/T+60/T+90 outcome observation."
            ),
        },
        "records": [asdict(item) for item in decisions],
    }


def freeze_decisions_file(t0_path: str | Path, out_path: str | Path) -> dict[str, Any]:
    source_path = Path(t0_path)
    output_path = Path(out_path)

    raw = source_path.read_bytes()
    t0_payload = json.loads(raw)
    frozen = build_frozen_decisions(t0_payload)

    # Hash the exact source file bytes rather than only a re-serialized object.
    frozen["source_dataset_sha256"] = hashlib.sha256(raw).hexdigest()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_bytes = (json.dumps(frozen, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output_path.write_bytes(output_bytes)

    decisions = frozen["records"]
    counts = {
        label: sum(1 for item in decisions if item["paper_decision"] == label)
        for label in ("APPROVE_PAPER", "REVIEW_PAPER", "REJECT_PAPER")
    }
    return {
        "records": len(decisions),
        "model_version": MODEL_VERSION,
        "source_dataset_sha256": frozen["source_dataset_sha256"],
        "decision_artifact_sha256": hashlib.sha256(output_bytes).hexdigest(),
        "decisions": counts,
        "average_risk_score": round(
            sum(item["risk_score"] for item in decisions) / len(decisions), 2
        ),
    }
