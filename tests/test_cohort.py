import random

import pytest

from credit_delegation_risk.cohort import (
    CohortCandidate,
    EvidenceRef,
    EvidenceTier,
    evidence_supports_primary_endpoint,
    select_forward50,
)


def _candidate(index: int, tier: EvidenceTier = EvidenceTier.A_DIRECT_ONCHAIN) -> CohortCandidate:
    address = f"0x{index:040x}"
    evidence = EvidenceRef(
        evidence_id=f"E-{index}",
        tier=tier,
        source="ethereum-json-rpc" if tier is EvidenceTier.A_DIRECT_ONCHAIN else "aave-derived",
        locator=f"evidence://wallet/{index}",
        observed_at="2026-10-09T12:00:00+00:00",
        block_number=24_000_000 if tier is EvidenceTier.A_DIRECT_ONCHAIN else None,
    )
    return CohortCandidate(
        wallet_address=address,
        snapshot_block=24_000_000,
        snapshot_at="2026-10-09T12:00:00+00:00",
        wallet_history_days=365,
        active_debt_usd=5_000,
        collateral_usd=12_000,
        health_factor=1.5,
        protocol="aave-v3",
        is_protocol_system_address=False,
        evidence=(evidence,),
    )


def test_forward50_selection_is_deterministic_and_input_order_independent():
    candidates = [_candidate(i) for i in range(1, 61)]
    first = select_forward50(candidates)

    shuffled = candidates.copy()
    random.Random(123).shuffle(shuffled)
    second = select_forward50(shuffled)

    assert [item.wallet_address for item in first] == [item.wallet_address for item in second]
    assert len(first) == 50


def test_forward50_requires_large_enough_eligible_pool():
    with pytest.raises(ValueError, match="need 50"):
        select_forward50([_candidate(i) for i in range(1, 40)])


def test_secondary_evidence_alone_cannot_support_primary_endpoint():
    items = (_candidate(1, EvidenceTier.C_SECONDARY).evidence[0],)
    assert evidence_supports_primary_endpoint(items) is False


def test_direct_onchain_evidence_supports_primary_endpoint():
    items = (_candidate(1).evidence[0],)
    assert evidence_supports_primary_endpoint(items) is True


def test_direct_onchain_evidence_requires_block_number():
    item = EvidenceRef(
        evidence_id="E",
        tier=EvidenceTier.A_DIRECT_ONCHAIN,
        source="rpc",
        locator="evidence://bad",
        observed_at="2026-10-09T12:00:00+00:00",
        block_number=None,
    )
    with pytest.raises(ValueError, match="block_number"):
        item.validate()
