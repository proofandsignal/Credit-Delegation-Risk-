# Forward 50 — Live Aave Snapshot Adapter

## Purpose

Create the first real Forward 50 cohort without manual wallet selection.

The adapter is **read-only**. It does not sign transactions, custody funds, execute Aave credit delegation, or infer wallet-owner identity.

## Fixed T0 repair rule

Workflow attempt 2 successfully froze Ethereum block **26,167,261** before cohort collection failed on an RPC provider range limit.

No cohort rows or outcomes were observed. Repair retries therefore reuse block 26,167,261 from `config/forward50_runtime.json` instead of drifting T0 during debugging.

## Official protocol anchors

Forward 50 v0.2 is pinned to:

- Ethereum chain ID: `1`
- Aave v3 Ethereum Pool: `0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2`
- PoolAddressesProvider: `0x2f39d218133AFaB8F2B819B1066c7E434Ad94E9e`

The adapter validates the market base currency from the Aave oracle before interpreting the account-data base unit as USD.

## Discovery rule

Alchemy Free limits wide `eth_getLogs` ranges, so Forward 50 does not brute-force millions of blocks.

At the fixed T0 block the adapter:

1. reads Aave's reserve list on-chain;
2. obtains each reserve's VariableDebtToken address from Aave's protocol data provider;
3. maps T0-365d and T0-90d timestamps to Ethereum blocks;
4. queries Alchemy Transfers API for ERC-20 mints from the zero address for each VariableDebtToken inside that pre-T0 window;
5. treats the recipient as a **candidate debt-holder**, not yet accepted evidence;
6. ranks candidates with the pre-registered SHA-256 rule;
7. verifies each candidate's discovery transaction through a direct Ethereum transaction receipt and requires an Aave Pool `Borrow` event whose indexed `onBehalfOf` equals the candidate wallet;
8. queries `getUserAccountData(address)` at the fixed T0 block;
9. takes the first 50 ranked addresses that pass the pre-registered eligibility contract.

The indexed Transfers API is therefore a discovery accelerator only. Acceptance is re-anchored to direct on-chain evidence.

## Why VariableDebtToken mints

Aave variable-rate borrowing mints VariableDebtToken debt to the address receiving the debt. In delegated-credit cases this is still the debt-holder / `onBehalfOf` address.

The final receipt verification prevents an indexed-provider record from being accepted unless the same transaction contains the canonical Aave Pool Borrow event for that wallet.

## Evidence

Every accepted record contains:

- Tier B: Alchemy indexed VariableDebtToken mint discovery reference;
- Tier A: direct Ethereum transaction receipt containing the matching Aave Borrow event;
- Tier A: block-pinned `getUserAccountData` state evidence.

It also records the VariableDebtToken used for discovery, snapshot block/hash, earliest qualifying Borrow block/transaction, protocol history days, collateral, debt, Health Factor and deterministic selection rank.

## GitHub Actions

The repository secret remains:

`AAVE_RPC_URL`

The current workflow reuses the fixed candidate T0 block from `config/forward50_runtime.json` unless an explicit block is supplied by manual dispatch.

## Data-quality gate

A run is not accepted merely because it produced 50 rows.

Before freezing the dataset:

- every address must pass the contract eligibility thresholds;
- every record must have the same block hash;
- every record must have direct receipt verification of its Aave Borrow history;
- every record must have block-pinned T0 account-state evidence;
- candidate selection must reproduce at the same fixed block;
- no outcome information may be used during selection.
