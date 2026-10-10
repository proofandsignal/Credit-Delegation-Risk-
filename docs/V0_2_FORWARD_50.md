# v0.2 — Historical / Forward 50

## Objective

Move from deterministic synthetic testing to a prospective benchmark based on public on-chain wallet data.

The core rule is:

> **Freeze the model decision at T0 and never rewrite it after observing the future.**

The experiment is still paper-only. No funds are lent and no Aave credit delegation is executed.

## Cohort

Target: **50 public wallets** with evidence-backed snapshots.

Selection should be rules-based and reproducible. Do not infer or publish a natural person's identity from a wallet.

Each T0 record should preserve:

- wallet address / experiment alias
- chain
- observed_at
- data-source references
- borrower snapshot fields
- model version
- input fingerprint
- frozen decision ID
- score / grade / APPROVE-REVIEW-REJECT
- estimated PD
- paper credit limit
- indicative term and premium

## Immutable T0 decision

The v0.2 implementation hashes the normalized T0 borrower snapshot.

A change to the input changes the fingerprint and decision ID. This makes later accidental or hindsight edits detectable.

## Outcome ledger

Only these evaluation horizons are accepted:

- T+30 days
- T+60 days
- T+90 days

Each outcome requires:

- decision ID
- horizon
- observation timestamp
- explicit adverse-outcome boolean
- outcome reason
- evidence reference

The same decision+horizon cannot be overwritten inside an experiment ledger.

## Adverse outcome taxonomy

An adverse outcome must be evidence-backed and defined before the cohort is scored.

Candidate paper-study events include:

- protocol liquidation affecting the monitored wallet
- severe leverage deterioration beyond a pre-declared threshold
- severe solvency / net-asset deterioration beyond a pre-declared threshold
- exploit or protocol event materially impairing the monitored position
- other pre-registered event that invalidates the original credit-risk assumption

These are **study labels**, not legal findings of borrower default.

## Calibration

For each horizon the engine can report:

- number of scored observations
- adverse outcomes
- observed adverse rate
- mean frozen predicted PD
- Brier score

The current v0.1 PD formula is not considered calibrated. v0.2 creates the evidence necessary to begin evaluating it.

## Acceptance gate

v0.2 is not complete until:

1. 50 T0 wallet snapshots have evidence references.
2. Every T0 decision is frozen before its future outcome is evaluated.
3. Cohort-selection rules and adverse-event definitions are documented before scoring.
4. Duplicate outcome overwrite is impossible in the ledger interface.
5. 30-day outcomes are collected for all eligible cases.
6. Calibration output is reproducible.
7. Tests and CI pass.

60/90-day observations continue the same frozen cohort and do not permit retrospective model edits.

## Non-goals

v0.2 does not:

- execute real loans
- custody funds or keys
- execute Aave delegation
- perform KYC
- identify wallet owners
- assert consumer creditworthiness
- present the current PD model as production-calibrated
