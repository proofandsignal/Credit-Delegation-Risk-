from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

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

PROTOCOL_SYSTEM_ADDRESSES = {
    AAVE_V3_ETHEREUM_POOL.lower(),
    AAVE_V3_ETHEREUM_ADDRESSES_PROVIDER.lower(),
}


class RpcLike(Protocol):
    def block_number(self) -> int: ...
    def block(self, number: int) -> dict: ...
    def eth_call(self, *, to: str, data: str, block_number: int) -> str: ...
    def transaction_receipt(self, tx_hash: str) -> dict: ...
    def asset_transfers(self, params: dict[str, Any]) -> dict: ...
    def keccak_text(self, text: str) -> str: ...


@dataclass(frozen=True)
class BorrowHistory:
    wallet_address: str
    earliest_borrow_block: int
    earliest_borrow_tx: str
    variable_debt_token: str


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
    variable_debt_token: str
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


def _decode_address_word(data: str, word_index: int = 0) -> str:
    clean = data.removeprefix("0x")
    start = word_index * 64
    word = clean[start : start + 64]
    if len(word) != 64:
        raise ValueError("address return value is too short")
    return "0x" + word[-40:]


def _decode_address_array(data: str) -> list[str]:
    clean = data.removeprefix("0x")
    if len(clean) < 128:
        raise ValueError("dynamic address array return value is too short")

    offset_bytes = int(clean[0:64], 16)
    offset = offset_bytes * 2
    if len(clean) < offset + 64:
        raise ValueError("invalid dynamic array offset")

    length = int(clean[offset : offset + 64], 16)
    cursor = offset + 64
    addresses: list[str] = []
    for index in range(length):
        word = clean[cursor + index * 64 : cursor + (index + 1) * 64]
        if len(word) != 64:
            raise ValueError("truncated dynamic address array")
        addresses.append("0x" + word[-40:])
    return addresses


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


def get_variable_debt_tokens(
    rpc: RpcLike,
    snapshot_block: int,
) -> dict[str, str]:
    reserves_selector = _selector(rpc, "getReservesList()")
    reserves_raw = rpc.eth_call(
        to=AAVE_V3_ETHEREUM_POOL,
        data=reserves_selector,
        block_number=snapshot_block,
    )
    reserves = _decode_address_array(reserves_raw)

    provider_selector = _selector(rpc, "ADDRESSES_PROVIDER()")
    provider_raw = rpc.eth_call(
        to=AAVE_V3_ETHEREUM_POOL,
        data=provider_selector,
        block_number=snapshot_block,
    )
    provider = _decode_address_word(provider_raw)

    data_provider_selector = _selector(rpc, "getPoolDataProvider()")
    data_provider_raw = rpc.eth_call(
        to=provider,
        data=data_provider_selector,
        block_number=snapshot_block,
    )
    data_provider = _decode_address_word(data_provider_raw)

    tokens: dict[str, str] = {}
    reserve_tokens_selector = _selector(rpc, "getReserveTokensAddresses(address)")
    for reserve in reserves:
        raw = rpc.eth_call(
            to=data_provider,
            data=reserve_tokens_selector + _encode_address(reserve),
            block_number=snapshot_block,
        )
        variable_debt = _decode_address_word(raw, 2).lower()
        if variable_debt != ZERO_ADDRESS:
            tokens[variable_debt] = reserve.lower()
    return tokens


def discover_established_borrowers(
    rpc: RpcLike,
    *,
    snapshot_block: int,
    snapshot_timestamp: int,
    lookback_days: int = 365,
    minimum_history_days: int = 90,
) -> dict[str, BorrowHistory]:
    if lookback_days <= minimum_history_days:
        raise ValueError("lookback_days must exceed minimum_history_days")

    oldest_ts = snapshot_timestamp - lookback_days * SECONDS_PER_DAY
    cutoff_ts = snapshot_timestamp - minimum_history_days * SECONDS_PER_DAY
    start_block = find_block_at_or_before_timestamp(rpc, oldest_ts, snapshot_block)
    cutoff_block = find_block_at_or_before_timestamp(rpc, cutoff_ts, snapshot_block)

    debt_tokens = get_variable_debt_tokens(rpc, snapshot_block)
    found: dict[str, BorrowHistory] = {}

    for variable_debt_token in sorted(debt_tokens):
        page_key: str | None = None
        while True:
            params: dict[str, Any] = {
                "fromBlock": hex(start_block),
                "toBlock": hex(cutoff_block),
                "fromAddress": ZERO_ADDRESS,
                "contractAddresses": [variable_debt_token],
                "category": ["erc20"],
                "excludeZeroValue": True,
                "withMetadata": False,
                "maxCount": "0x3e8",
                "order": "asc",
            }
            if page_key:
                params["pageKey"] = page_key

            result = rpc.asset_transfers(params)
            for transfer in result.get("transfers", []):
                wallet = (transfer.get("to") or "").lower()
                tx_hash = transfer.get("hash") or ""
                block_hex = transfer.get("blockNum") or ""
                if not wallet.startswith("0x") or len(wallet) != 42:
                    continue
                if not tx_hash.startswith("0x") or not block_hex:
                    continue
                block_number = int(block_hex, 16)
                previous = found.get(wallet)
                if previous is None or block_number < previous.earliest_borrow_block:
                    found[wallet] = BorrowHistory(
                        wallet_address=wallet,
                        earliest_borrow_block=block_number,
                        earliest_borrow_tx=tx_hash,
                        variable_debt_token=variable_debt_token,
                    )

            page_key = result.get("pageKey")
            if not page_key:
                break

    return found


def verify_borrow_history(rpc: RpcLike, history: BorrowHistory) -> bool:
    receipt = rpc.transaction_receipt(history.earliest_borrow_tx)
    borrow_topic = rpc.keccak_text(BORROW_EVENT_SIGNATURE).lower()

    for log in receipt.get("logs", []):
        if (log.get("address") or "").lower() != AAVE_V3_ETHEREUM_POOL.lower():
            continue
        topics = log.get("topics") or []
        if len(topics) < 3:
            continue
        if topics[0].lower() != borrow_topic:
            continue
        if _topic_address(topics[2]).lower() != history.wallet_address.lower():
            continue
        if int(log.get("blockNumber", "0x0"), 16) != history.earliest_borrow_block:
            continue
        return True
    return False


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
        if not verify_borrow_history(rpc, item):
            continue

        state = get_account_state(rpc, item.wallet_address, snapshot_block)
        collateral_usd = state.total_collateral_base / base_unit
        debt_usd = state.total_debt_base / base_unit
        health_factor = state.health_factor_raw / HEALTH_FACTOR_UNIT

        is_system = item.wallet_address.lower() in PROTOCOL_SYSTEM_ADDRESSES

        earliest_block = rpc.block(item.earliest_borrow_block)
        earliest_ts = int(earliest_block["timestamp"], 16)
        history_days = max(0, (snapshot_timestamp - earliest_ts) // SECONDS_PER_DAY)

        discovery_evidence = EvidenceRef(
            evidence_id=(
                f"alchemy-vdebt-mint:{item.variable_debt_token.lower()}:"
                f"{item.earliest_borrow_tx.lower()}"
            ),
            tier=EvidenceTier.B_PROTOCOL_DERIVED,
            source="alchemy-transfers-api",
            locator=(
                f"vdebt-mint:{item.variable_debt_token.lower()}:"
                f"{item.earliest_borrow_tx.lower()}:{item.wallet_address.lower()}"
            ),
            observed_at=datetime.fromtimestamp(earliest_ts, tz=timezone.utc).isoformat(),
            block_number=item.earliest_borrow_block,
        )
        borrow_evidence = EvidenceRef(
            evidence_id=f"borrow:{item.earliest_borrow_tx.lower()}",
            tier=EvidenceTier.A_DIRECT_ONCHAIN,
            source="ethereum-transaction-receipt",
            locator=(
                f"tx:{item.earliest_borrow_tx.lower()}:"
                f"borrow:onBehalfOf:{item.wallet_address.lower()}"
            ),
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
            evidence=(borrow_evidence, state_evidence, discovery_evidence),
        )

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
            variable_debt_token=item.variable_debt_token.lower(),
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
