from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .engine import assess_borrower
from .models import BorrowerSnapshot, CreditDecision


VALID_HORIZONS = (30, 60, 90)
MODEL_PROBABILITY_SEMANTICS = "v0.1_proxy_probability_not_default_pd"


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
    model_risk_probability: float
    model_probability_semantics: str
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
            model_risk_probability=decision.estimated_pd,
            model_probability_semantics=MODEL_PROBABILITY_SEMANTICS,
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
class PositionOutcomeMetrics:
    liquidation_event: bool
    min_health_factor: float | None
    final_health_factor: float | None
    collateral_drawdown_pct: float | None
    final_debt_usd: float

    def validate(self) -> None:
        if self.min_health_factor is not None and self.min_health_factor < 0:
            raise ValueError("min_health_factor must be >= 0")
        if self.final_health_factor is not None and self.final_health_factor < 0:
            raise ValueError("final_health_factor must be >= 0")
        if self.collateral_drawdown_pct is not None and not 0 <= self.collateral_drawdown_pct <= 1:
            raise ValueError("collateral_drawdown_pct must be between 0 and 1")
        if self.final_debt_usd < 0:
            raise ValueError("final_debt_usd must be >= 0")


@dataclass(frozen=True)
class EndpointClassification:
    primary_adverse_event: bool
    secondary_distress_event: bool
    reasons: tuple[str, ...]


def classify_position_outcome(metrics: PositionOutcomeMetrics) -> EndpointClassification:
    metrics.validate()
    reasons: list[str] = []

    primary = metrics.liquidation_event or (
        metrics.min_health_factor is not None and metrics.min_health_factor < 1.0
    )
    if metrics.liquidation_event:
        reasons.append("aave_liquidation_event")
    if metrics.min_health_factor is not None and metrics.min_health_factor < 1.0:
        reasons.append("health_factor_below_1_0")

    secondary = primary
    if (
        metrics.final_health_factor is not None
        and metrics.final_health_factor < 1.10
        and metrics.final_debt_usd >= 500
    ):
        secondary = True
        reasons.append("final_health_factor_below_1_10_with_debt")

    if (
        metrics.collateral_drawdown_pct is not None
        and metrics.collateral_drawdown_pct >= 0.50
        and metrics.final_debt_usd >= 500
    ):
        secondary = True
        reasons.append("collateral_drawdown_at_least_50pct_with_debt")

    return EndpointClassification(
        primary_adverse_event=primary,
        secondary_distress_event=secondary,
        reasons=tuple(dict.fromkeys(reasons)),
    )


@dataclass(frozen=True)
class OutcomeObservation:
    decision_id: str
    horizon_days: int
    observed_at: str
    adverse_event: bool
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
    """In-memory append-only ledger for one experiment run."""

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
) -> dict[str, float | int | str]:
    if horizon_days not in VALID_HORIZONS:
        raise ValueError(f"horizon_days must be one of {VALID_HORIZONS}")

    decision_map = {item.decision_id: item for item in decisions}
    horizon_outcomes = [item for item in outcomes if item.horizon_days == horizon_days]

    scored: list[tuple[float, int]] = []
    for outcome in horizon_outcomes:
        decision = decision_map.get(outcome.decision_id)
        if decision is None:
            continue
        scored.append((decision.model_risk_probability, 1 if outcome.adverse_event else 0))

    if not scored:
        return {
            "horizon_days": horizon_days,
            "observations": 0,
            "adverse_events": 0,
            "observed_event_rate": 0.0,
            "mean_model_risk_probability": 0.0,
            "brier_score": 0.0,
            "probability_semantics": MODEL_PROBABILITY_SEMANTICS,
        }

    observations = len(scored)
    adverse = sum(label for _, label in scored)
    mean_probability = sum(probability for probability, _ in scored) / observations
    brier = sum((probability - label) ** 2 for probability, label in scored) / observations

    return {
        "horizon_days": horizon_days,
        "observations": observations,
        "adverse_events": adverse,
        "observed_event_rate": round(adverse / observations, 4),
        "mean_model_risk_probability": round(mean_probability, 4),
        "brier_score": round(brier, 6),
        "probability_semantics": MODEL_PROBABILITY_SEMANTICS,
    }
