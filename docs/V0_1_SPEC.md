# v0.1 — Synthetic 100 Specification

## Goal

Build the first reproducible benchmark for delegated DeFi credit risk without real lending, custody, smart-contract execution, or capital at risk.

## Inputs

Each borrower snapshot contains:

- borrower ID
- synthetic archetype
- wallet age
- modeled net worth
- stable-asset ratio
- leverage ratio
- concentration ratio
- protocol count
- prior liquidation count
- prior repayment count
- suspicious-activity flag

These are model inputs, not identity claims.

## Decision output

The engine produces:

- risk score: 0–100
- risk grade: A–E
- decision: APPROVE / REVIEW / REJECT
- estimated PD
- paper credit limit
- paper term
- indicative annual premium in basis points
- explainable reason codes

## Synthetic 100

The benchmark uses seed 42 and five balanced archetypes:

1. seasoned low risk
2. leveraged active
3. new wallet
4. concentrated speculator
5. suspicious high risk

Twenty profiles are generated per archetype.

## Acceptance gate

v0.1 passes when:

- 100 profiles are produced deterministically
- the same input produces the same decision
- every score stays within 0–100
- every PD stays within 1–35%
- paper limits never exceed $10,000
- suspicious high-risk cases cannot be automatically approved
- unit tests and CI pass

## Explicit non-goals

v0.1 does not:

- execute Aave `approveDelegation`
- lend real funds
- custody assets or keys
- identify the legal owner of a wallet
- claim regulatory compliance
- claim a calibrated real-world probability of default

The v0.1 PD function is a model placeholder to be replaced or calibrated using historical and forward outcome data in later versions.

## Next gate

After Synthetic 100:

**v0.2 — Historical / Forward 50**

Freeze real public-wallet snapshots at T0, issue paper decisions, then measure 30/60/90-day outcomes without retroactively changing the original decision.
