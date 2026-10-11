# BUILD v0.3 — Forward Outcome Observer

## Purpose

Forward Outcome Observer collects prospective evidence for the already-frozen
Forward 50 experiment.

It is deliberately **not** a new scoring model. The v0.2 T0 cohort, model,
predictions and hashes remain immutable.

## Why daily observations are required

A single Health Factor reading at T+30 could miss a temporary deterioration that
occurred earlier in the window.

v0.3 therefore uses two complementary evidence paths:

1. **Daily best-effort block-pinned account samples**
   - Aave `getUserAccountData`
   - collateral
   - debt
   - Health Factor
   - collateral drawdown versus T0

2. **Cumulative liquidation detection**
   - find debt-token transfers associated with each frozen wallet through Alchemy
     Transfers API;
   - treat these transfers only as discovery candidates;
   - fetch the transaction receipt directly;
   - accept a liquidation only when the Aave Pool emitted a
     `LiquidationCall` whose indexed `user` equals the frozen wallet.

The Transfers API is an indexing accelerator. The final liquidation label is
anchored to direct on-chain receipt evidence.

## Operational definition of the primary endpoint

The frozen primary endpoint is positive if either is observed:

- a directly verified Aave liquidation after T0; or
- Health Factor below 1.0 at any retained scheduled daily block-pinned sample.

This remains an **on-chain adverse credit-risk event proxy**, not borrower default.

## Sampling contract

Daily observation target: **06:15 UTC**.

GitHub Actions scheduling is best-effort, therefore checkpoint quality reports
coverage explicitly.

A checkpoint is complete only when:

- a final sample exists at or after the exact checkpoint timestamp and no more than
  six hours late; and
- at least 80% of expected UTC-day samples are present.

Missing coverage is never silently treated as a negative outcome.

## Private observation history

The raw 50-wallet cohort and observation history are not committed to the public
repository.

GitHub Actions artifacts carry:

- the frozen T0 source;
- frozen T0 decisions;
- daily observations;
- later checkpoint bundles.

Public git history retains only hashes, model contracts and aggregate commitments.

## Checkpoints

- T+30: 2026-11-10 05:57:11 UTC
- T+60: 2026-12-10 05:57:11 UTC
- T+90: 2027-01-09 05:57:11 UTC

At each checkpoint the observer computes:

- primary event rate
- Brier score
- calibration gap
- absolute calibration gap
- performance by APPROVE / REVIEW / REJECT
- false negatives
- secondary distress labels
- sampling coverage

A false negative is pre-defined as:

> `APPROVE_PAPER` at T0 + primary adverse event observed by the checkpoint.

## Incremental checkpoint integrity

T+60 may carry forward T+30 minima and liquidation evidence. T+90 may carry
forward T+60. This prevents early daily artifacts approaching retention expiry
from erasing already-observed distress.

Later model versions may be evaluated separately, but cannot replace the
`forward-position-risk-v0.2.0` baseline in the primary Forward 50 results.
