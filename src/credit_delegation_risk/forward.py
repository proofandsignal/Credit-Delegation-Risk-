from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .engine import assess_borrower
from .models import BorrowerSnapshot, CreditDecision


VALID_HORIZONS = (30, 60, 90)


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _snapshot_fingerprint(snapshot: BorrowerSnapshot) -> str:
    payload = json.dumps(asdict(snapshot), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FrozenDecision:
    decision_id: str
    borrower_id: str
    observed_at: str
    input_fingerprint: str
    risk_score: int
    risk_grade: str
    decision: str
    estimated_pd: float
    credit_limit_usd: int
    term_days: int
    annual_premium_bps: int
    reasons: tuple[str, ...]

    @classmethod
    def from_credit_decision(
        cls,
        snapshot: BorrowerSnapshot,
        decision: CreditDecision,
        observed_at: datetime,
    ) -> "FrozenDecision":
        timestamp = _iso_utc(observed_at)
        fingerprint = _snapshot_fingerprint(snapshot)
        decision_id = hashlib.sha256(
            f"{snapshot.borrower_id}|{timestamp}|{fingerprint}".encode("utf-8")
        ).hexdigest()[:24]

        return cls(
            decision_id=decision_id,
            borrower_id=snapshot.borrower_id,
            observed_at=timestamp,
            input_fingerprint=fingerprint,
            risk_score=decision.risk_score,
            risk_grade=decision.risk_grade,
            decision=decision.decision.value,
            estimated_pd=decision.estimated_pd,
            credit_limit_usd=decision.credit_limit_usd,
            term_days=decision.term_days,
            annual_premium_bps=decision.annual_premium_bps,
            reasons=decision.reasons,
        )


def freeze_decision(snapshot: BorrowerSnapshot, observed_at: datetime) -> FrozenDecision:
    return FrozenDecision.from_credit_decision(
        snapshot=snapshot,
        decision=assess_borrower(snapshot),
        observed_at=observed_at,
    )


@dataclass(frozen=True)
class OutcomeObservation:
    decision_id: str
    horizon_days: int
    observed_at: str
    adverse_outcome: bool
    outcome_reason: str
    evidence_ref: str

    def validate(self) -> None:
        if self.horizon_days not in VALID_HORIZONS:
            raise ValueError(f"horizon_days must be one of {VALID_HORIZONS}")
        if not self.decision_id:
            raise ValueError("decision_id is required")
        if not self.outcome_reason:
            raise ValueError("outcome_reason is required")
        if not self.evidence_ref:
            raise ValueError("evidence_ref is required")


class OutcomeLedger:
    """In-memory append-only ledger for one experiment run.

    Persistence can be layered on top later. Duplicate decision+horizon entries are
    rejected so an observed outcome cannot be silently overwritten.
    """

    def __init__(self) -> None:
        self._rows: dict[tuple[str, int], OutcomeObservation] = {}

    def append(self, observation: OutcomeObservation) -> None:
        observation.validate()
        key = (observation.decision_id, observation.horizon_days)
        if key in self._rows:
            raise ValueError("outcome already recorded for decision+horizon")
        self._rows[key] = observation

    def rows(self) -> tuple[OutcomeObservation, ...]:
        return tuple(
            self._rows[key]
            for key in sorted(self._rows, key=lambda item: (item[0], item[1]))
        )


def calibration_summary(
    decisions: list[FrozenDecision],
    outcomes: list[OutcomeObservation],
    horizon_days: int,
) -> dict[str, float | int]:
    if horizon_days not in VALID_HORIZONS:
        raise ValueError(f"horizon_days must be one of {VALID_HORIZONS}")

    decision_map = {item.decision_id: item for item in decisions}
    horizon_outcomes = [item for item in outcomes if item.horizon_days == horizon_days]

    scored: list[tuple[float, int]] = []
    for outcome in horizon_outcomes:
        decision = decision_map.get(outcome.decision_id)
        if decision is None:
            continue
        scored.append((decision.estimated_pd, 1 if outcome.adverse_outcome else 0))

    if not scored:
        return {
            "horizon_days": horizon_days,
            "observations": 0,
            "adverse_outcomes": 0,
            "observed_adverse_rate": 0.0,
            "mean_predicted_pd": 0.0,
            "brier_score": 0.0,
        }

    observations = len(scored)
    adverse = sum(label for _, label in scored)
    mean_pd = sum(pd for pd, _ in scored) / observations
    brier = sum((pd - label) ** 2 for pd, label in scored) / observations

    return {
        "horizon_days": horizon_days,
        "observations": observations,
        "adverse_outcomes": adverse,
        "observed_adverse_rate": round(adverse / observations, 4),
        "mean_predicted_pd": round(mean_pd, 4),
        "brier_score": round(brier, 6),
    }
