# Forward 50 — Cohort + Evidence Contract

This document is pre-registered before the first real wallet enters the Forward 50 dataset.

The machine-readable companion is `config/forward50_contract.json`.

## 1. Scope

Forward 50 v0.2 studies **public Aave v3 borrowing positions on Ethereum mainnet**.

The unit of analysis is a public on-chain position / wallet address. The experiment does not infer the legal identity behind an address and does not claim consumer creditworthiness.

## 2. Candidate eligibility at T0

A candidate is eligible only when all of the following are true at the frozen snapshot:

- Aave v3 / Ethereum mainnet
- wallet / position history of at least 90 days
- active debt of at least $1,000
- collateral of at least $2,500
- Health Factor at least 1.0 at T0
- not a known protocol/system address
- at least one Tier A or Tier B evidence reference

These thresholds are experiment filters, not lending recommendations.

## 3. Cohort selection

The eligible candidate pool is outcome-blind.

After eligibility filtering, candidates are ranked by SHA-256 of:

```
forward50-v0.2-pre-registered-2026-10-09
| lowercase wallet address
| T0 snapshot block
```

The first 50 become the cohort.

Changing input order does not change the selected cohort. Duplicate eligible wallet addresses are rejected.

This mechanism is deliberately boring: it prevents manual cherry-picking after seeing which wallets look interesting.

## 4. Evidence tiers

### Tier A — DIRECT ON-CHAIN

Preferred evidence.

Examples:

- Ethereum JSON-RPC `eth_call` at an explicit block
- transaction / receipt
- protocol event log
- immutable block / transaction reference

Tier A evidence must record a block number.

### Tier B — PROTOCOL-DERIVED

Accepted for T0 feature construction and cross-checking when tied to a reproducible protocol source.

Examples:

- official Aave data interface / indexer output
- official protocol subgraph or equivalent derived source
- reproducible protocol state calculation tied to block context

Tier B is derived evidence and should retain enough provenance to reconstruct the result.

### Tier C — SECONDARY

Discovery / cross-check only.

Examples:

- explorers
- third-party dashboards
- third-party indexers

Tier C cannot, by itself, prove the Forward 50 **primary endpoint**.

Screenshots, social posts and mutable UI text are not primary evidence.

## 5. Information boundary

T0 scoring and cohort selection may use only information observed at or before the frozen T0 timestamp / block.

Post-T0 data is outcome data and cannot be used to revise:

- the cohort
- the original input snapshot
- the original score
- the original decision
- the original model probability

A corrected data-quality error must be recorded as a new experiment version rather than silently rewriting history.

## 6. Primary endpoint

The primary label is:

**on-chain adverse credit-risk event**

It is **not borrower default**.

The primary endpoint is positive when either occurs during the evaluation window:

1. an Aave liquidation event affecting the monitored position; or
2. an observed Aave Health Factor below 1.0.

Primary-positive labels require Tier A direct on-chain evidence.

## 7. Secondary distress endpoint

Tracked separately from the primary label.

Secondary distress is positive if the primary endpoint is positive, or if either occurs with at least $500 debt still outstanding:

- final Health Factor below 1.10; or
- collateral drawdown of at least 50% versus T0.

The secondary endpoint must never be silently substituted for the primary endpoint.

## 8. 30 / 60 / 90-day observations

The frozen cohort is evaluated at:

- T+30
- T+60
- T+90

A decision+horizon outcome is append-only and cannot be overwritten.

## 9. Probability semantics

The v0.1 field previously called estimated PD is **not yet a validated probability of borrower default**.

For Forward 50 it is frozen and exposed as:

`model_risk_probability`

with explicit semantics:

`v0.1_proxy_probability_not_default_pd`

Forward 50 may evaluate whether that proxy ranks / calibrates to the registered on-chain adverse-event endpoint. It cannot establish true borrower default probability without real repayment/default labels.

## 10. Pre-registered gate

No real wallet should be added to the cohort until this contract is committed.

Any future change to:

- inclusion thresholds
- selection seed
- evidence hierarchy
- primary endpoint
- secondary endpoint

must increment the experiment contract version and must not retroactively alter already frozen observations.
