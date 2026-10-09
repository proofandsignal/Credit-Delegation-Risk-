from datetime import datetime, timezone

import pytest

from credit_delegation_risk.forward import (
    OutcomeLedger,
    OutcomeObservation,
    calibration_summary,
    freeze_decision,
)
from credit_delegation_risk.models import BorrowerSnapshot


def _borrower() -> BorrowerSnapshot:
    return BorrowerSnapshot(
        borrower_id="FORWARD-001",
        archetype="public_wallet",
        wallet_age_days=1200,
        net_worth_usd=150_000,
        stable_asset_ratio=0.35,
        leverage_ratio=0.15,
        concentration_ratio=0.25,
        protocol_count=5,
        liquidation_count=0,
        prior_repayments=3,
        suspicious_activity=False,
    )


def test_frozen_decision_is_deterministic_for_same_t0_input():
    observed_at = datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc)

    first = freeze_decision(_borrower(), observed_at)
    second = freeze_decision(_borrower(), observed_at)

    assert first == second
    assert first.input_fingerprint == second.input_fingerprint
    assert len(first.decision_id) == 24


def test_snapshot_change_changes_fingerprint():
    observed_at = datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc)
    original = _borrower()
    changed = BorrowerSnapshot(**{**original.__dict__, "leverage_ratio": 0.55})

    first = freeze_decision(original, observed_at)
    second = freeze_decision(changed, observed_at)

    assert first.input_fingerprint != second.input_fingerprint
    assert first.decision_id != second.decision_id


def test_outcome_ledger_rejects_overwrite():
    decision = freeze_decision(
        _borrower(),
        datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc),
    )
    observation = OutcomeObservation(
        decision_id=decision.decision_id,
        horizon_days=30,
        observed_at="2026-11-08T06:00:00+00:00",
        adverse_outcome=False,
        outcome_reason="no adverse event observed",
        evidence_ref="evidence://forward-001/30d",
    )

    ledger = OutcomeLedger()
    ledger.append(observation)

    with pytest.raises(ValueError, match="already recorded"):
        ledger.append(observation)


def test_outcome_requires_valid_horizon():
    observation = OutcomeObservation(
        decision_id="abc",
        horizon_days=45,
        observed_at="2026-11-23T06:00:00+00:00",
        adverse_outcome=False,
        outcome_reason="test",
        evidence_ref="evidence://test",
    )

    with pytest.raises(ValueError, match="horizon_days"):
        observation.validate()


def test_calibration_uses_frozen_pd():
    decision = freeze_decision(
        _borrower(),
        datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc),
    )
    outcome = OutcomeObservation(
        decision_id=decision.decision_id,
        horizon_days=30,
        observed_at="2026-11-08T06:00:00+00:00",
        adverse_outcome=True,
        outcome_reason="paper adverse outcome",
        evidence_ref="evidence://forward-001/30d",
    )

    summary = calibration_summary([decision], [outcome], horizon_days=30)

    assert summary["observations"] == 1
    assert summary["adverse_outcomes"] == 1
    assert summary["mean_predicted_pd"] == decision.estimated_pd
    assert summary["brier_score"] > 0
