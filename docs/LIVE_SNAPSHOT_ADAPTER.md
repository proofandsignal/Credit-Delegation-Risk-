# Forward 50 — Live Aave Snapshot Adapter

## Purpose

Create the first real Forward 50 cohort without manual wallet selection.

The adapter is **read-only**. It does not sign transactions, custody funds, execute Aave credit delegation, or infer wallet-owner identity.

## Official protocol anchors

Forward 50 v0.2 is pinned to:

- Ethereum chain ID: `1`
- Aave v3 Ethereum Pool: `0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2`
- PoolAddressesProvider: `0x2f39d218133AFaB8F2B819B1066c7E434Ad94E9e`

The adapter validates the market base currency from the Aave oracle before interpreting the account-data base unit as USD.

## Discovery rule

At the start of a run:

1. freeze one Ethereum snapshot block;
2. locate the blocks corresponding to T0-365 days and T0-90 days;
3. scan Aave Pool `Borrow` events only within that pre-T0 discovery window;
4. extract indexed `onBehalfOf`, the address receiving the debt;
5. deduplicate addresses;
6. rank them with the pre-registered SHA-256 rule;
7. query current `getUserAccountData(address)` at the frozen T0 block;
8. take the first 50 ranked addresses that pass the pre-registered eligibility contract.

Scanning stops once 50 eligible addresses are found. This is mathematically equivalent to ranking the candidate universe and then taking the first 50 eligible candidates because eligibility is evaluated independently of the rank.

## Why Borrow events

The Aave v3 Pool emits `Borrow` with indexed `onBehalfOf`. That field represents the address receiving the debt, including delegated-credit cases where the transaction caller differs from the debt holder.

For Forward 50 we are studying active Aave borrowing positions, not trying to identify natural persons.

## T0 state

The adapter calls the Pool's:

`getUserAccountData(address)`

at the frozen block and records:

- total collateral in market base currency
- total active debt in market base currency
- available borrowing capacity
- liquidation threshold
- LTV
- Health Factor

The raw result is converted using the Aave oracle's `BASE_CURRENCY_UNIT()`, after confirming `BASE_CURRENCY()` is the USD sentinel address.

## Evidence

Every accepted record contains two Tier A references:

1. earliest observed qualifying Borrow transaction within the discovery window;
2. block-pinned `eth_call` evidence for the T0 account state.

It also records:

- snapshot block
- snapshot block hash
- snapshot UTC timestamp
- earliest qualifying Borrow block
- transaction hash
- protocol history days
- collateral USD
- debt USD
- Health Factor
- deterministic selection rank

## Running

Use a reliable archive-capable Ethereum RPC. Do not commit the RPC URL.

```bash
export AAVE_RPC_URL="..."
credit-risk forward50-live --out data/forward50/t0.json
```

To reproduce against an already frozen block:

```bash
credit-risk forward50-live \
  --snapshot-block <BLOCK_NUMBER> \
  --out data/forward50/t0.json
```

## GitHub Actions

A manual workflow is provided. It expects the repository secret:

`AAVE_RPC_URL`

The workflow uploads the resulting T0 JSON as an artifact. Review the generated cohort and provenance before committing any dataset into the repository.

## Data-quality gate

A run is not accepted merely because it produced 50 rows.

Before freezing the dataset:

- every address must pass the contract eligibility thresholds;
- every record must have a block hash and Tier A evidence;
- the snapshot block must be identical across all 50 records;
- candidate selection must reproduce at the same fixed block;
- no outcome information may be used during selection.
