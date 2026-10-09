from credit_delegation_risk.engine import assess_borrower
from credit_delegation_risk.models import BorrowerSnapshot, Decision


def test_low_risk_borrower_is_approved():
    borrower = BorrowerSnapshot(
        borrower_id="TEST-LOW",
        archetype="test",
        wallet_age_days=1200,
        net_worth_usd=200_000,
        stable_asset_ratio=0.40,
        leverage_ratio=0.10,
        concentration_ratio=0.20,
        protocol_count=5,
        liquidation_count=0,
        prior_repayments=5,
        suspicious_activity=False,
    )
    result = assess_borrower(borrower)

    assert result.decision is Decision.APPROVE
    assert result.risk_score >= 90
    assert result.credit_limit_usd == 10_000
    assert result.estimated_pd <= 0.02


def test_suspicious_borrower_is_rejected():
    borrower = BorrowerSnapshot(
        borrower_id="TEST-HIGH",
        archetype="test",
        wallet_age_days=30,
        net_worth_usd=50_000,
        stable_asset_ratio=0.02,
        leverage_ratio=0.90,
        concentration_ratio=0.95,
        protocol_count=1,
        liquidation_count=3,
        prior_repayments=0,
        suspicious_activity=True,
    )
    result = assess_borrower(borrower)

    assert result.decision is Decision.REJECT
    assert result.credit_limit_usd == 0
    assert "suspicious_activity" in result.reasons
