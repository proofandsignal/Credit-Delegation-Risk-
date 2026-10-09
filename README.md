# Credit Delegation Risk

Credit intelligence and paper-simulation lab for delegated DeFi credit risk.

## v0.1 — Synthetic 100

The first build deliberately does **not** originate real loans or move funds. It creates a deterministic paper-credit benchmark for testing:

- borrower snapshot normalization
- wallet/borrower risk scoring
- explainable decision rules
- APPROVE / REVIEW / REJECT decisions
- paper credit limits from $1,000 to $10,000
- simple estimated probability of default (PD)
- indicative risk premium
- reproducible Synthetic 100 generation
- CI-backed tests

## v0.2 — Forward 50

The next build freezes real public-wallet decisions at T0 and records 30/60/90-day outcomes without hindsight edits.

Core invariants:

- the original decision is immutable
- the T0 borrower input is fingerprinted
- only 30/60/90-day horizons are accepted
- an outcome for the same decision+horizon cannot be overwritten
- adverse-outcome labels are explicit evidence-backed observations, not claims about a person's legal creditworthiness
- calibration uses the original frozen estimated PD

See [docs/V0_2_FORWARD_50.md](docs/V0_2_FORWARD_50.md).

## Architecture

```text
Borrower Snapshot
      ↓
Credit Risk Engine
      ↓
Decision Engine
      ↓
Frozen T0 Decision
      ↓
30 / 60 / 90d Outcome Ledger
      ↓
Calibration / Model Error
```

## Quick start

```bash
python -m pip install -e ".[dev]"
credit-risk synthetic100 --out data/generated
pytest
```

Generated datasets are intentionally ignored by git. The source of truth for v0.1 is the deterministic generator and its seed. Forward-50 evidence inputs will be versioned separately from derived outputs.

## Safety / scope

This repository is research and software infrastructure. It does not custody assets, execute Aave credit delegation, provide real-world lending, identify the legal owner of a wallet, or claim that a wallet score proves a person's creditworthiness.
