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

## Architecture

```text
Borrower Snapshot
      ↓
Credit Risk Engine
      ↓
Decision Engine
      ↓
Credit Limit + Pricing
      ↓
Paper Credit Portfolio
      ↓
Future: Monitoring + 30/60/90d Outcomes
```

## Quick start

```bash
python -m pip install -e ".[dev]"
credit-risk synthetic100 --out data/generated
pytest
```

Generated datasets are intentionally ignored by git. The source of truth is the deterministic generator and its seed.

## Safety / scope

This repository is research and software infrastructure. v0.1 does not custody assets, execute Aave credit delegation, provide real-world lending, or claim that a wallet score proves a person's creditworthiness.

See [docs/V0_1_SPEC.md](docs/V0_1_SPEC.md).
