from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .cohort import (
    FORWARD50_SEED,
    CohortCandidate,
    EvidenceRef,
    EvidenceTier,
    select_forward50,
)


AAVE_V3_ETHEREUM_POOL = "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
AAVE_V3_ETHEREUM_ADDRESSES_PROVIDER = "0x2f39d218133AFaB8F2B819B1066c7E434Ad94E9e"
BORROW_EVENT_SIGNATURE = "Borrow(address,address,address,uint256,uint8,uint256,uint16)"
SECONDS_PER_DAY = 86_400
HEALTH_FACTOR_UNIT = 10**18
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# Explicit core-address denylist only. Smart-contract borrowers are otherwise allowed.
PROTOCOL_SYSTEM_ADDRESSES = {
    AAVE_V3_ETHEREUM_POOL.lower(),
    AAVE_V3_ETHEREUM_ADDRESSES_PROVIDER.lower(),
}


class RpcLike(Protocol):
    def block_number(self) -> int: ...
    def block(self, number: int) -> dict: ...
    def logs(self, *, address: str, from_block: int, to_block: int, topics: list[str | None]) -> list[dict]: ...
    def eth_call(self, *, to: str, data: str, block_number: int) -> str: ...
    def keccak_text(self, text: str) -> str: ...


@dataclass(frozen=True)
class BorrowHistory:
    wallet_address: str
    earliest_borrow_block: int
    earliest_borrow_tx: str


@dataclass(frozen=True)
class AccountState:
    total_collateral_base: int
    total_debt_base: int
    available_borrows_base: int
    current_liquidation_threshold_bps: int
    ltv_bps: int
    health_factor_raw: int


@dataclass(frozen=True)
class LiveCandidateRecord:
    wallet_address: str
    snapshot_block: int
    snapshot_block_hash: str
    snapshot_at: str
    earliest_borrow_block: int
    earliest_borrow_tx: str
    protocol_history_days: int
    collateral_usd: float
    active_debt_usd: float
    health_factor: float
    selection_rank: str
    evidence: tuple[dict, ...]


def _selector(rpc: RpcLike, signature: str) -> str:
    return rpc.keccak_text(signature)[:10]


def _encode_address(address: str) -> str:
    clean = address.lower().removeprefix("0x")
    if len(clean) != 40:
        raise ValueError("invalid EVM address")
    int(clean, 16)
    return clean.rjust(64, "0")


def _decode_words(data: str, count: int) -> list[int]:
    clean = data.removeprefix("0x")
    expected = count * 64
    if len(clean) < expected:
        raise ValueError(f"eth_call returned {len(clean)} hex chars; expected at least {expected}")
    return [int(clean[i * 64 : (i + 1) * 64], 16) for i in range(count)]


def _decode_address_word(data: str) -> str:
    clean = data.removeprefix("0x")
    if len(clean) < 64:
        raise ValueError("address return value is too short")
    return "0x" + clean[24:64]


def _topic_address(topic: str) -> str:
    clean = topic.removeprefix("0x")
    if len(clean) != 64:
        raise ValueError("indexed address topic must be 32 bytes")
    return "0x" + clean[-40:]


def _rank(wallet_address: str, snapshot_block: int, seed: str = FORWARD50_SEED) -> str:
    import hashlib

    payload = f"{seed}|{wallet_address.lower()}|{snapshot_block}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def find_block_at_or_before_timestamp(rpc: RpcLike, timestamp: int, latest_block: int) -> int:
    low, high = 0, latest_block
    best = 0
    while low <= high:
        mid = (low + high) // 2
        mid_ts = int(rpc.block(mid)["timestamp"], 16)
        if mid_ts <= timestamp:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    return best


def discover_established_borrowers(
    rpc: RpcLike,
    *,
    snapshot_block: int,
    snapshot_timestamp: int,
    lookback_days: int = 365,
    minimum_history_days: int = 90,
    chunk_blocks: int = 25_000,
) -> dict[str, BorrowHistory]:
    if lookback_days <= minimum_history_days:
        raise ValueError("lookback_days must exceed minimum_history_days")
    if chunk_blocks <= 0:
        raise ValueError("chunk_blocks must be positive")

    oldest_ts = snapshot_timestamp - lookback_days * SECONDS_PER_DAY
    cutoff_ts = snapshot_timestamp - minimum_history_days * SECONDS_PER_DAY
    start_block = find_block_at_or_before_timestamp(rpc, oldest_ts, snapshot_block)
    cutoff_block = find_block_at_or_before_timestamp(rpc, cutoff_ts, snapshot_block)

    borrow_topic = rpc.keccak_text(BORROW_EVENT_SIGNATURE)
    found: dict[str, BorrowHistory] = {}

    cursor = start_block
    while cursor <= cutoff_block:
        end = min(cursor + chunk_blocks - 1, cutoff_block)
        logs = rpc.logs(
            address=AAVE_V3_ETHEREUM_POOL,
            from_block=cursor,
            to_block=end,
            topics=[borrow_topic],
        )
        for log in logs:
            topics = log.get("topics", [])
            if len(topics) < 3:
                continue
            wallet = _topic_address(topics[2]).lower()
            block_number = int(log["blockNumber"], 16)
            tx_hash = log["transactionHash"]
            previous = found.get(wallet)
            if previous is None or block_number < previous.earliest_borrow_block:
                found[wallet] = BorrowHistory(wallet, block_number, tx_hash)
        cursor = end + 1

    return found


def get_account_state(rpc: RpcLike, wallet_address: str, snapshot_block: int) -> AccountState:
    selector = _selector(rpc, "getUserAccountData(address)")
    data = selector + _encode_address(wallet_address)
    raw = rpc.eth_call(to=AAVE_V3_ETHEREUM_POOL, data=data, block_number=snapshot_block)
    values = _decode_words(raw, 6)
    return AccountState(*values)


def get_base_currency_unit(rpc: RpcLike, snapshot_block: int) -> int:
    provider_selector = _selector(rpc, "ADDRESSES_PROVIDER()")
    provider_raw = rpc.eth_call(
        to=AAVE_V3_ETHEREUM_POOL,
        data=provider_selector,
        block_number=snapshot_block,
    )
    provider = _decode_address_word(provider_raw)

    oracle_selector = _selector(rpc, "getPriceOracle()")
    oracle_raw = rpc.eth_call(to=provider, data=oracle_selector, block_number=snapshot_block)
    oracle = _decode_address_word(oracle_raw)

    base_currency_selector = _selector(rpc, "BASE_CURRENCY()")
    base_currency_raw = rpc.eth_call(
        to=oracle,
        data=base_currency_selector,
        block_number=snapshot_block,
    )
    base_currency = _decode_address_word(base_currency_raw)
    if base_currency.lower() != ZERO_ADDRESS:
        raise ValueError("Forward 50 v0.2 expects an Aave market with USD base currency")

    unit_selector = _selector(rpc, "BASE_CURRENCY_UNIT()")
    unit_raw = rpc.eth_call(to=oracle, data=unit_selector, block_number=snapshot_block)
    unit = _decode_words(unit_raw, 1)[0]
    if unit <= 0:
        raise ValueError("invalid Aave base currency unit")
    return unit


def build_live_forward50(
    rpc: RpcLike,
    *,
    snapshot_block: int | None = None,
    target_size: int = 50,
    lookback_days: int = 365,
    minimum_history_days: int = 90,
) -> list[LiveCandidateRecord]:
    if snapshot_block is None:
        snapshot_block = rpc.block_number()

    snapshot = rpc.block(snapshot_block)
    snapshot_timestamp = int(snapshot["timestamp"], 16)
    snapshot_hash = snapshot["hash"]
    snapshot_at = datetime.fromtimestamp(snapshot_timestamp, tz=timezone.utc).isoformat()
    base_unit = get_base_currency_unit(rpc, snapshot_block)

    history = discover_established_borrowers(
        rpc,
        snapshot_block=snapshot_block,
        snapshot_timestamp=snapshot_timestamp,
        lookback_days=lookback_days,
        minimum_history_days=minimum_history_days,
    )

    ranked_history = sorted(
        history.values(),
        key=lambda item: (_rank(item.wallet_address, snapshot_block), item.wallet_address),
    )

    eligible: list[CohortCandidate] = []
    records_by_wallet: dict[str, LiveCandidateRecord] = {}

    for item in ranked_history:
        state = get_account_state(rpc, item.wallet_address, snapshot_block)
        collateral_usd = state.total_collateral_base / base_unit
        debt_usd = state.total_debt_base / base_unit
        health_factor = state.health_factor_raw / HEALTH_FACTOR_UNIT

        if item.wallet_address.lower() in PROTOCOL_SYSTEM_ADDRESSES:
            is_system = True
        else:
            is_system = False

        earliest_block = rpc.block(item.earliest_borrow_block)
        earliest_ts = int(earliest_block["timestamp"], 16)
        history_days = max(0, (snapshot_timestamp - earliest_ts) // SECONDS_PER_DAY)

        borrow_evidence = EvidenceRef(
            evidence_id=f"borrow:{item.earliest_borrow_tx.lower()}",
            tier=EvidenceTier.A_DIRECT_ONCHAIN,
            source="ethereum-json-rpc",
            locator=f"tx:{item.earliest_borrow_tx}",
            observed_at=datetime.fromtimestamp(earliest_ts, tz=timezone.utc).isoformat(),
            block_number=item.earliest_borrow_block,
        )
        state_evidence = EvidenceRef(
            evidence_id=f"account-state:{item.wallet_address.lower()}:{snapshot_block}",
            tier=EvidenceTier.A_DIRECT_ONCHAIN,
            source="ethereum-json-rpc",
            locator=(
                f"eth_call:getUserAccountData:{AAVE_V3_ETHEREUM_POOL.lower()}:"
                f"{item.wallet_address.lower()}:{snapshot_block}"
            ),
            observed_at=snapshot_at,
            block_number=snapshot_block,
        )

        candidate = CohortCandidate(
            wallet_address=item.wallet_address,
            snapshot_block=snapshot_block,
            snapshot_at=snapshot_at,
            wallet_history_days=int(history_days),
            active_debt_usd=round(debt_usd, 8),
            collateral_usd=round(collateral_usd, 8),
            health_factor=health_factor,
            protocol="aave-v3",
            is_protocol_system_address=is_system,
            evidence=(borrow_evidence, state_evidence),
        )

        # select_forward50 owns the canonical eligibility predicate.
        try:
            selected = select_forward50([candidate], target_size=1)
        except ValueError:
            continue
        if not selected:
            continue

        eligible.append(candidate)
        records_by_wallet[item.wallet_address.lower()] = LiveCandidateRecord(
            wallet_address=item.wallet_address.lower(),
            snapshot_block=snapshot_block,
            snapshot_block_hash=snapshot_hash,
            snapshot_at=snapshot_at,
            earliest_borrow_block=item.earliest_borrow_block,
            earliest_borrow_tx=item.earliest_borrow_tx,
            protocol_history_days=int(history_days),
            collateral_usd=round(collateral_usd, 2),
            active_debt_usd=round(debt_usd, 2),
            health_factor=round(health_factor, 8),
            selection_rank=_rank(item.wallet_address, snapshot_block),
            evidence=tuple(asdict(e) for e in candidate.evidence),
        )
        if len(eligible) >= target_size:
            break

    if len(eligible) < target_size:
        raise ValueError(
            f"only {len(eligible)} eligible live positions found; need {target_size}"
        )

    canonical = select_forward50(eligible, target_size=target_size)
    return [records_by_wallet[item.wallet_address.lower()] for item in canonical]


def write_forward50(records: list[LiveCandidateRecord], out_path: str | Path) -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset": "forward50-t0",
        "record_count": len(records),
        "records": [asdict(record) for record in records],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
