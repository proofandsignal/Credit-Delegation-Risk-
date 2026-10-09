from __future__ import annotations

from .models import BorrowerSnapshot, CreditDecision, Decision


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 55:
        return "D"
    return "E"


def _estimated_pd(score: int) -> float:
    # v0.1 calibration placeholder: monotonic, deterministic and intentionally conservative.
    raw = 0.01 + (((100 - score) / 100) ** 2) * 0.34
    return round(min(max(raw, 0.01), 0.35), 4)


def _credit_limit(snapshot: BorrowerSnapshot, score: int, decision: Decision) -> int:
    if decision is Decision.REJECT:
        return 0

    if decision is Decision.REVIEW:
        raw = min(2_500, snapshot.net_worth_usd * 0.015)
        return int(max(1_000, raw)) if snapshot.net_worth_usd >= 10_000 else 0

    if score >= 90:
        pct = 0.08
    elif score >= 80:
        pct = 0.05
    else:
        pct = 0.03

    raw = snapshot.net_worth_usd * pct
    return int(min(10_000, max(1_000, raw)))


def assess_borrower(snapshot: BorrowerSnapshot) -> CreditDecision:
    snapshot.validate()
    penalties: list[tuple[str, int]] = []

    if snapshot.wallet_age_days < 90:
        penalties.append(("wallet_age_under_90d", 25))
    elif snapshot.wallet_age_days < 365:
        penalties.append(("wallet_age_under_1y", 10))

    if snapshot.leverage_ratio > 0.75:
        penalties.append(("very_high_leverage", 25))
    elif snapshot.leverage_ratio > 0.50:
        penalties.append(("high_leverage", 15))
    elif snapshot.leverage_ratio > 0.25:
        penalties.append(("moderate_leverage", 5))

    if snapshot.stable_asset_ratio < 0.10:
        penalties.append(("low_stable_asset_buffer", 10))

    if snapshot.concentration_ratio > 0.80:
        penalties.append(("very_high_concentration", 15))
    elif snapshot.concentration_ratio > 0.60:
        penalties.append(("high_concentration", 10))
    elif snapshot.concentration_ratio > 0.40:
        penalties.append(("moderate_concentration", 5))

    liquidation_penalty = min(snapshot.liquidation_count * 10, 20)
    if liquidation_penalty:
        penalties.append(("prior_liquidations", liquidation_penalty))

    if snapshot.protocol_count < 2:
        penalties.append(("low_protocol_diversification", 5))

    if snapshot.suspicious_activity:
        penalties.append(("suspicious_activity", 45))

    repayment_bonus = min(snapshot.prior_repayments * 2, 10)
    score = 100 - sum(value for _, value in penalties) + repayment_bonus
    score = max(0, min(100, score))

    if score >= 70 and not snapshot.suspicious_activity:
        decision = Decision.APPROVE
    elif score >= 55 and not snapshot.suspicious_activity:
        decision = Decision.REVIEW
    else:
        decision = Decision.REJECT

    pd = _estimated_pd(score)
    premium_bps = 450 + (100 - score) * 18
    if decision is Decision.REVIEW:
        premium_bps += 200
    elif decision is Decision.REJECT:
        premium_bps = 0

    term_days = 90 if score >= 80 and decision is Decision.APPROVE else 30
    if decision is Decision.REJECT:
        term_days = 0

    reasons = tuple(name for name, _ in sorted(penalties, key=lambda item: item[1], reverse=True))
    if repayment_bonus:
        reasons += ("positive_repayment_history",)

    return CreditDecision(
        borrower_id=snapshot.borrower_id,
        risk_score=score,
        risk_grade=_grade(score),
        decision=decision,
        estimated_pd=pd,
        credit_limit_usd=_credit_limit(snapshot, score, decision),
        term_days=term_days,
        annual_premium_bps=premium_bps,
        reasons=reasons,
    )
