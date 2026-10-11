# Forward 50 — Position Risk Baseline v0.2.0

## Why this is a separate model

The original Synthetic 100 borrower model expects fields such as wallet-wide net worth,
stable-asset mix, cross-protocol exposure, prior repayment count and suspicious-activity
flags.

The real Forward 50 T0 collector does **not** currently establish those fields with the
same evidence standard. They are therefore not guessed, defaulted or backfilled.

Forward 50 uses a separate, deliberately small position-risk baseline based only on
observed T0 Aave data:

- Health Factor
- active debt / collateral
- Aave protocol-history days

## Registration timing

This baseline is frozen **after** the T0 cohort was collected and reproduced, but
**before** any T+30/T+60/T+90 outcome observation.

That distinction is recorded explicitly. The model is not described as a pre-cohort
preregistered model.

## Target

The target is the already registered:

**on-chain adverse credit-risk event proxy**

It is not borrower default, legal creditworthiness, KYC risk or a consumer credit score.

## Score

Start at 100 and subtract deterministic penalties.

### Health Factor

| T0 Health Factor | Penalty |
| --- | ---: |
| < 1.05 | 55 |
| < 1.10 | 45 |
| < 1.25 | 30 |
| < 1.50 | 20 |
| < 2.00 | 10 |
| >= 2.00 | 0 |

### Debt / collateral

| Ratio | Penalty |
| --- | ---: |
| > 0.85 | 20 |
| > 0.70 | 12 |
| > 0.50 | 5 |
| <= 0.50 | 0 |

### Aave history

| History | Penalty |
| --- | ---: |
| < 120 days | 8 |
| < 180 days | 4 |
| >= 180 days | 0 |

The final score is clamped to 0–100.

## Paper-only decision labels

- score >= 70: `APPROVE_PAPER`
- score >= 55 and < 70: `REVIEW_PAPER`
- score < 55: `REJECT_PAPER`

These are experiment labels only. They do not recommend extending real credit.

## Probability proxy

The baseline converts score to a monotonic proxy:

```
0.01 + ((100 - score) / 100)^2 * 0.34
```

clamped to 1–35%.

Its semantics are fixed as:

`proxy_probability_of_registered_onchain_adverse_credit_risk_event_not_borrower_default`

This number is not considered calibrated until Forward 50 outcomes exist.

## Integrity rule

After the frozen-decision artifact is hashed, model thresholds and T0 decisions cannot
be edited for this Forward 50 cohort. Any later model improvement must use a new model
version and may be evaluated separately without replacing the original prediction.
