from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum


FORWARD50_TARGET = 50
FORWARD50_CHAIN_ID = 1
FORWARD50_PROTOCOL = "aave-v3"
FORWARD50_SEED = "forward50-v0.2-pre-registered-2026-10-09"

_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


class EvidenceTier(str, Enum):
    A_DIRECT_ONCHAIN = "A_DIRECT_ONCHAIN"
    B_PROTOCOL_DERIVED = "B_PROTOCOL_DERIVED"
    C_SECONDARY = "C_SECONDARY"


@dataclass(frozen=True)
class EvidenceRef:
    evidence_id: str
    tier: EvidenceTier
    source: str
    locator: str
    observed_at: str
    chain_id: int = FORWARD50_CHAIN_ID
    block_number: int | None = None

    def validate(self) -> None:
        if not self.evidence_id or not self.source or not self.locator or not self.observed_at:
            raise ValueError("evidence_id, source, locator and observed_at are required")
        if self.chain_id <= 0:
            raise ValueError("chain_id must be positive")
        if self.tier is EvidenceTier.A_DIRECT_ONCHAIN and self.block_number is None:
            raise ValueError("direct on-chain evidence requires block_number")


@dataclass(frozen=True)
class CohortCandidate:
    wallet_address: str
    snapshot_block: int
    snapshot_at: str
    wallet_history_days: int
    active_debt_usd: float
    collateral_usd: float
    health_factor: float
    protocol: str
    is_protocol_system_address: bool
    evidence: tuple[EvidenceRef, ...]

    def validate(self) -> None:
        if not _ADDRESS_RE.fullmatch(self.wallet_address):
            raise ValueError("wallet_address must be a valid EVM address")
        if self.snapshot_block <= 0:
            raise ValueError("snapshot_block must be positive")
        if self.wallet_history_days < 0:
            raise ValueError("wallet_history_days must be >= 0")
        if self.active_debt_usd < 0 or self.collateral_usd < 0:
            raise ValueError("USD fields must be >= 0")
        if self.health_factor <= 0:
            raise ValueError("health_factor must be positive")
        if not self.evidence:
            raise ValueError("at least one evidence reference is required")
        for item in self.evidence:
            item.validate()


def is_eligible(candidate: CohortCandidate) -> bool:
    candidate.validate()
    has_primary_or_protocol = any(
        item.tier in {EvidenceTier.A_DIRECT_ONCHAIN, EvidenceTier.B_PROTOCOL_DERIVED}
        for item in candidate.evidence
    )
    return (
        candidate.protocol == FORWARD50_PROTOCOL
        and candidate.wallet_history_days >= 90
        and candidate.active_debt_usd >= 1_000
        and candidate.collateral_usd >= 2_500
        and candidate.health_factor >= 1.0
        and not candidate.is_protocol_system_address
        and has_primary_or_protocol
    )


def _rank(candidate: CohortCandidate, seed: str) -> str:
    payload = f"{seed}|{candidate.wallet_address.lower()}|{candidate.snapshot_block}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def select_forward50(
    candidates: list[CohortCandidate],
    *,
    target_size: int = FORWARD50_TARGET,
    seed: str = FORWARD50_SEED,
) -> list[CohortCandidate]:
    if target_size <= 0:
        raise ValueError("target_size must be > 0")

    by_wallet: dict[str, CohortCandidate] = {}
    for candidate in candidates:
        if not is_eligible(candidate):
            continue
        key = candidate.wallet_address.lower()
        if key in by_wallet:
            raise ValueError("duplicate eligible wallet in candidate pool")
        by_wallet[key] = candidate

    ranked = sorted(by_wallet.values(), key=lambda item: (_rank(item, seed), item.wallet_address.lower()))
    if len(ranked) < target_size:
        raise ValueError(f"eligible candidate pool has {len(ranked)} wallets; need {target_size}")
    return ranked[:target_size]


def evidence_supports_primary_endpoint(items: tuple[EvidenceRef, ...]) -> bool:
    for item in items:
        item.validate()
    return any(item.tier is EvidenceTier.A_DIRECT_ONCHAIN for item in items)
