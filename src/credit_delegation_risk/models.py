from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Decision(str, Enum):
    APPROVE = "APPROVE"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


@dataclass(frozen=True)
class BorrowerSnapshot:
    borrower_id: str
    archetype: str
    wallet_age_days: int
    net_worth_usd: float
    stable_asset_ratio: float
    leverage_ratio: float
    concentration_ratio: float
    protocol_count: int
    liquidation_count: int
    prior_repayments: int
    suspicious_activity: bool

    def validate(self) -> None:
        if not self.borrower_id:
            raise ValueError("borrower_id is required")
        if self.wallet_age_days < 0:
            raise ValueError("wallet_age_days must be >= 0")
        if self.net_worth_usd < 0:
            raise ValueError("net_worth_usd must be >= 0")
        for field_name in ("stable_asset_ratio", "leverage_ratio", "concentration_ratio"):
            value = getattr(self, field_name)
            if not 0 <= value <= 1:
                raise ValueError(f"{field_name} must be between 0 and 1")
        if self.protocol_count < 0 or self.liquidation_count < 0 or self.prior_repayments < 0:
            raise ValueError("count fields must be >= 0")


@dataclass(frozen=True)
class CreditDecision:
    borrower_id: str
    risk_score: int
    risk_grade: str
    decision: Decision
    estimated_pd: float
    credit_limit_usd: int
    term_days: int
    annual_premium_bps: int
    reasons: tuple[str, ...]
