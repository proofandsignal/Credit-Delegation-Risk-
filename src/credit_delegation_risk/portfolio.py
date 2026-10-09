from __future__ import annotations

from dataclasses import asdict

from .engine import assess_borrower
from .models import BorrowerSnapshot


def build_paper_portfolio(borrowers: list[BorrowerSnapshot]) -> list[dict]:
    portfolio: list[dict] = []

    for borrower in borrowers:
        decision = assess_borrower(borrower)
        row = asdict(borrower)
        row.update(
            {
                "paper_loan_id": f"LOAN-{borrower.borrower_id}",
                "risk_score": decision.risk_score,
                "risk_grade": decision.risk_grade,
                "decision": decision.decision.value,
                "estimated_pd": decision.estimated_pd,
                "credit_limit_usd": decision.credit_limit_usd,
                "term_days": decision.term_days,
                "annual_premium_bps": decision.annual_premium_bps,
                "decision_reasons": "|".join(decision.reasons),
                "paper_status": "OPEN" if decision.credit_limit_usd > 0 else "NO_LOAN",
            }
        )
        portfolio.append(row)

    return portfolio
