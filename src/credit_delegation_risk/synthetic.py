from __future__ import annotations

import random

from .models import BorrowerSnapshot


ARCHETYPES = (
    "seasoned_low_risk",
    "leveraged_active",
    "new_wallet",
    "concentrated_speculator",
    "suspicious_high_risk",
)


def _r(rng: random.Random, low: float, high: float) -> float:
    return round(rng.uniform(low, high), 4)


def generate_borrowers(count: int = 100, seed: int = 42) -> list[BorrowerSnapshot]:
    if count <= 0:
        raise ValueError("count must be > 0")

    rng = random.Random(seed)
    rows: list[BorrowerSnapshot] = []

    for i in range(count):
        archetype = ARCHETYPES[i % len(ARCHETYPES)]

        if archetype == "seasoned_low_risk":
            values = dict(
                wallet_age_days=rng.randint(730, 2400),
                net_worth_usd=round(rng.uniform(50_000, 500_000), 2),
                stable_asset_ratio=_r(rng, 0.25, 0.70),
                leverage_ratio=_r(rng, 0.00, 0.20),
                concentration_ratio=_r(rng, 0.10, 0.38),
                protocol_count=rng.randint(3, 8),
                liquidation_count=0,
                prior_repayments=rng.randint(2, 10),
                suspicious_activity=False,
            )
        elif archetype == "leveraged_active":
            values = dict(
                wallet_age_days=rng.randint(400, 1800),
                net_worth_usd=round(rng.uniform(30_000, 300_000), 2),
                stable_asset_ratio=_r(rng, 0.10, 0.35),
                leverage_ratio=_r(rng, 0.45, 0.82),
                concentration_ratio=_r(rng, 0.25, 0.60),
                protocol_count=rng.randint(3, 10),
                liquidation_count=rng.randint(0, 2),
                prior_repayments=rng.randint(0, 6),
                suspicious_activity=False,
            )
        elif archetype == "new_wallet":
            values = dict(
                wallet_age_days=rng.randint(7, 180),
                net_worth_usd=round(rng.uniform(5_000, 120_000), 2),
                stable_asset_ratio=_r(rng, 0.05, 0.50),
                leverage_ratio=_r(rng, 0.05, 0.55),
                concentration_ratio=_r(rng, 0.20, 0.75),
                protocol_count=rng.randint(1, 4),
                liquidation_count=rng.randint(0, 1),
                prior_repayments=0,
                suspicious_activity=False,
            )
        elif archetype == "concentrated_speculator":
            values = dict(
                wallet_age_days=rng.randint(180, 1500),
                net_worth_usd=round(rng.uniform(8_000, 220_000), 2),
                stable_asset_ratio=_r(rng, 0.00, 0.18),
                leverage_ratio=_r(rng, 0.20, 0.70),
                concentration_ratio=_r(rng, 0.65, 0.98),
                protocol_count=rng.randint(1, 5),
                liquidation_count=rng.randint(0, 2),
                prior_repayments=rng.randint(0, 3),
                suspicious_activity=False,
            )
        else:
            values = dict(
                wallet_age_days=rng.randint(10, 900),
                net_worth_usd=round(rng.uniform(2_000, 150_000), 2),
                stable_asset_ratio=_r(rng, 0.00, 0.30),
                leverage_ratio=_r(rng, 0.20, 0.95),
                concentration_ratio=_r(rng, 0.30, 0.99),
                protocol_count=rng.randint(1, 5),
                liquidation_count=rng.randint(0, 3),
                prior_repayments=rng.randint(0, 2),
                suspicious_activity=True,
            )

        rows.append(
            BorrowerSnapshot(
                borrower_id=f"SYN-{i + 1:03d}",
                archetype=archetype,
                **values,
            )
        )

    return rows
