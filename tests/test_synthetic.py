from credit_delegation_risk.portfolio import build_paper_portfolio
from credit_delegation_risk.synthetic import ARCHETYPES, generate_borrowers


def test_synthetic100_is_deterministic_and_balanced():
    first = generate_borrowers(count=100, seed=42)
    second = generate_borrowers(count=100, seed=42)

    assert first == second
    assert len(first) == 100

    counts = {name: 0 for name in ARCHETYPES}
    for borrower in first:
        counts[borrower.archetype] += 1

    assert set(counts.values()) == {20}


def test_portfolio_contains_all_decision_classes():
    portfolio = build_paper_portfolio(generate_borrowers(count=100, seed=42))
    decisions = {row["decision"] for row in portfolio}

    assert "APPROVE" in decisions
    assert "REJECT" in decisions
    assert len(portfolio) == 100
    assert all(0 <= row["estimated_pd"] <= 0.35 for row in portfolio)
    assert all(0 <= row["credit_limit_usd"] <= 10_000 for row in portfolio)
