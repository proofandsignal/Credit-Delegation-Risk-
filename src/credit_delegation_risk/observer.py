from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from .forward import PositionOutcomeMetrics, classify_position_outcome
from .live_aave import (
    AAVE_V3_ETHEREUM_POOL,
    HEALTH_FACTOR_UNIT,
    ZERO_ADDRESS,
    _decode_address_array,
    _decode_address_word,
    _encode_address,
    _selector,
    _topic_address,
    get_account_state,
    get_base_currency_unit,
)


T0_BLOCK = 26_167_261
T0_BLOCK_HASH = "0xbed220d742b21a51da74801865c30bb05bd8eda7c1a4a5715cc85cb1037716a1"
T0_AT = "2026-10-11T05:57:11+00:00"
T0_DATASET_SHA256 = "aa02bbee8382908068bfb36e4ec7b853da9adac089516668c2fca7a9ef9a8313"
DECISION_ARTIFACT_SHA256 = "e7d604f28a85721ec8443056830a09a7e406a101241a2d89fc95b0ea340c66c9"
MODEL_VERSION = "forward-position-risk-v0.2.0"
LIQUIDATION_CALL_EVENT_SIGNATURE = (
    "LiquidationCall(address,address,address,uint256,uint256,address,bool)"
)
VALID_HORIZONS = (30, 60, 90)
MIN_COVERAGE_RATIO = 0.80
FINAL_SAMPLE_MAX_DELAY_HOURS = 6


class ObserverRpcLike(Protocol):
    def block_number(self) -> int: ...
    def block(self, number: int) -> dict: ...
    def eth_call(self, *, to: str, data: str, block_number: int) -> str: ...
    def transaction_receipt(self, tx_hash: str) -> dict: ...
    def asset_transfers(self, params: dict[str, Any]) -> dict: ...
    def keccak_text(self, text: str) -> str: ...


@dataclass(frozen=True)
class DailyPositionObservation:
    decision_id: str
    wallet_address: str
    paper_decision: str
    risk_score: int
    model_risk_probability: float
    observed_block: int
    observed_block_hash: str
    observed_at: str
    collateral_usd: float
    active_debt_usd: float
    health_factor: float
    collateral_drawdown_pct_from_t0: float
    sampled_health_factor_below_1_0: bool
    liquidation_event_since_t0: bool
    liquidation_tx_hashes: tuple[str, ...]
    state_evidence_ref: str


def _sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_frozen_baseline_files(
    t0_path: str | Path,
    decisions_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if _sha256_file(t0_path) != T0_DATASET_SHA256:
        raise ValueError("T0 dataset hash does not match frozen commitment")
    if _sha256_file(decisions_path) != DECISION_ARTIFACT_SHA256:
        raise ValueError("decision artifact hash does not match frozen commitment")

    t0 = json.loads(Path(t0_path).read_text(encoding="utf-8"))
    decisions = json.loads(Path(decisions_path).read_text(encoding="utf-8"))

    if t0.get("record_count") != 50 or len(t0.get("records", [])) != 50:
        raise ValueError("frozen T0 dataset must contain exactly 50 records")
    if decisions.get("record_count") != 50 or len(decisions.get("records", [])) != 50:
        raise ValueError("frozen decision artifact must contain exactly 50 records")
    if decisions.get("model_version") != MODEL_VERSION:
        raise ValueError("unexpected frozen model version")
    if int(decisions.get("snapshot_block", -1)) != T0_BLOCK:
        raise ValueError("unexpected decision snapshot block")
    if decisions.get("snapshot_block_hash") != T0_BLOCK_HASH:
        raise ValueError("unexpected decision snapshot hash")

    t0_wallets = {row["wallet_address"].lower() for row in t0["records"]}
    decision_wallets = {row["wallet_address"].lower() for row in decisions["records"]}
    if t0_wallets != decision_wallets or len(t0_wallets) != 50:
        raise ValueError("T0 cohort and decision wallet sets do not match")

    return t0, decisions


def _get_all_debt_token_addresses(
    rpc: ObserverRpcLike,
    block_number: int,
) -> tuple[str, ...]:
    reserves_raw = rpc.eth_call(
        to=AAVE_V3_ETHEREUM_POOL,
        data=_selector(rpc, "getReservesList()"),
        block_number=block_number,
    )
    reserves = _decode_address_array(reserves_raw)

    provider_raw = rpc.eth_call(
        to=AAVE_V3_ETHEREUM_POOL,
        data=_selector(rpc, "ADDRESSES_PROVIDER()"),
        block_number=block_number,
    )
    provider = _decode_address_word(provider_raw)

    data_provider_raw = rpc.eth_call(
        to=provider,
        data=_selector(rpc, "getPoolDataProvider()"),
        block_number=block_number,
    )
    data_provider = _decode_address_word(data_provider_raw)

    selector = _selector(rpc, "getReserveTokensAddresses(address)")
    tokens: set[str] = set()
    for reserve in reserves:
        raw = rpc.eth_call(
            to=data_provider,
            data=selector + _encode_address(reserve),
            block_number=block_number,
        )
        stable_debt = _decode_address_word(raw, 1).lower()
        variable_debt = _decode_address_word(raw, 2).lower()
        if stable_debt != ZERO_ADDRESS:
            tokens.add(stable_debt)
        if variable_debt != ZERO_ADDRESS:
            tokens.add(variable_debt)
    return tuple(sorted(tokens))


def _candidate_debt_transactions(
    rpc: ObserverRpcLike,
    *,
    wallet_address: str,
    debt_tokens: tuple[str, ...],
    from_block: int,
    to_block: int,
) -> tuple[str, ...]:
    if to_block < from_block:
        return ()

    found: set[str] = set()
    token_chunks = [debt_tokens[i : i + 50] for i in range(0, len(debt_tokens), 50)]

    for contracts in token_chunks:
        page_key: str | None = None
        while True:
            params: dict[str, Any] = {
                "fromBlock": hex(from_block),
                "toBlock": hex(to_block),
                "fromAddress": wallet_address,
                "contractAddresses": list(contracts),
                "category": ["erc20"],
                "excludeZeroValue": False,
                "withMetadata": False,
                "maxCount": "0x3e8",
                "order": "asc",
            }
            if page_key:
                params["pageKey"] = page_key

            result = rpc.asset_transfers(params)
            for transfer in result.get("transfers", []):
                tx_hash = transfer.get("hash") or ""
                if tx_hash.startswith("0x"):
                    found.add(tx_hash.lower())

            page_key = result.get("pageKey")
            if not page_key:
                break

    return tuple(sorted(found))


def verify_liquidation_receipt(
    rpc: ObserverRpcLike,
    *,
    tx_hash: str,
    wallet_address: str,
) -> bool:
    receipt = rpc.transaction_receipt(tx_hash)
    liquidation_topic = rpc.keccak_text(LIQUIDATION_CALL_EVENT_SIGNATURE).lower()

    for log in receipt.get("logs", []):
        if (log.get("address") or "").lower() != AAVE_V3_ETHEREUM_POOL.lower():
            continue
        topics = log.get("topics") or []
        if len(topics) < 4:
            continue
        if topics[0].lower() != liquidation_topic:
            continue
        if _topic_address(topics[3]).lower() != wallet_address.lower():
            continue
        return True
    return False


def _liquidations_since_t0(
    rpc: ObserverRpcLike,
    *,
    wallet_address: str,
    debt_tokens: tuple[str, ...],
    observed_block: int,
) -> tuple[str, ...]:
    candidates = _candidate_debt_transactions(
        rpc,
        wallet_address=wallet_address,
        debt_tokens=debt_tokens,
        from_block=T0_BLOCK + 1,
        to_block=observed_block,
    )
    verified = [
        tx_hash
        for tx_hash in candidates
        if verify_liquidation_receipt(
            rpc,
            tx_hash=tx_hash,
            wallet_address=wallet_address,
        )
    ]
    return tuple(sorted(set(verified)))


def observe_forward50(
    rpc: ObserverRpcLike,
    *,
    t0_payload: dict[str, Any],
    decisions_payload: dict[str, Any],
    observed_block: int | None = None,
) -> dict[str, Any]:
    if observed_block is None:
        observed_block = rpc.block_number()
    if observed_block < T0_BLOCK:
        raise ValueError("observed block cannot be earlier than T0")

    block = rpc.block(observed_block)
    block_hash = block["hash"]
    observed_timestamp = int(block["timestamp"], 16)
    observed_at = datetime.fromtimestamp(
        observed_timestamp, tz=timezone.utc
    ).isoformat()

    base_unit = get_base_currency_unit(rpc, observed_block)
    t0_tokens = set(_get_all_debt_token_addresses(rpc, T0_BLOCK))
    observed_tokens = set(_get_all_debt_token_addresses(rpc, observed_block))
    debt_tokens = tuple(sorted(t0_tokens | observed_tokens))

    t0_by_wallet = {
        row["wallet_address"].lower(): row for row in t0_payload["records"]
    }
    decision_by_wallet = {
        row["wallet_address"].lower(): row for row in decisions_payload["records"]
    }

    rows: list[DailyPositionObservation] = []
    for wallet in sorted(t0_by_wallet):
        t0 = t0_by_wallet[wallet]
        decision = decision_by_wallet[wallet]

        state = get_account_state(rpc, wallet, observed_block)
        collateral = state.total_collateral_base / base_unit
        debt = state.total_debt_base / base_unit
        health_factor = state.health_factor_raw / HEALTH_FACTOR_UNIT

        t0_collateral = float(t0["collateral_usd"])
        drawdown = 0.0
        if t0_collateral > 0:
            drawdown = max(0.0, (t0_collateral - collateral) / t0_collateral)

        liquidation_hashes = _liquidations_since_t0(
            rpc,
            wallet_address=wallet,
            debt_tokens=debt_tokens,
            observed_block=observed_block,
        )

        rows.append(
            DailyPositionObservation(
                decision_id=decision["decision_id"],
                wallet_address=wallet,
                paper_decision=decision["paper_decision"],
                risk_score=int(decision["risk_score"]),
                model_risk_probability=float(decision["model_risk_probability"]),
                observed_block=observed_block,
                observed_block_hash=block_hash,
                observed_at=observed_at,
                collateral_usd=round(collateral, 2),
                active_debt_usd=round(debt, 2),
                health_factor=round(health_factor, 8),
                collateral_drawdown_pct_from_t0=round(drawdown, 8),
                sampled_health_factor_below_1_0=health_factor < 1.0,
                liquidation_event_since_t0=bool(liquidation_hashes),
                liquidation_tx_hashes=liquidation_hashes,
                state_evidence_ref=(
                    f"eth_call:getUserAccountData:{AAVE_V3_ETHEREUM_POOL.lower()}:"
                    f"{wallet}:{observed_block}"
                ),
            )
        )

    return {
        "dataset": "forward50-daily-observation",
        "observer_version": "forward-outcome-observer-v0.3.0",
        "source_t0_sha256": T0_DATASET_SHA256,
        "source_decision_sha256": DECISION_ARTIFACT_SHA256,
        "model_version": MODEL_VERSION,
        "t0_block": T0_BLOCK,
        "t0_at": T0_AT,
        "observed_block": observed_block,
        "observed_block_hash": block_hash,
        "observed_at": observed_at,
        "record_count": len(rows),
        "records": [asdict(row) for row in rows],
    }


def observe_forward50_files(
    rpc: ObserverRpcLike,
    *,
    t0_path: str | Path,
    decisions_path: str | Path,
    out_path: str | Path,
    observed_block: int | None = None,
) -> dict[str, Any]:
    t0, decisions = validate_frozen_baseline_files(t0_path, decisions_path)
    payload = observe_forward50(
        rpc,
        t0_payload=t0,
        decisions_payload=decisions,
        observed_block=observed_block,
    )

    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output.write_bytes(raw)

    rows = payload["records"]
    return {
        "records": len(rows),
        "observed_block": payload["observed_block"],
        "observed_at": payload["observed_at"],
        "sampled_hf_below_1_count": sum(
            1 for row in rows if row["sampled_health_factor_below_1_0"]
        ),
        "liquidation_seen_count": sum(
            1 for row in rows if row["liquidation_event_since_t0"]
        ),
        "observation_sha256": hashlib.sha256(raw).hexdigest(),
        "output": str(output),
    }


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _deduplicate_observations(
    payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_block: dict[int, dict[str, Any]] = {}
    for payload in payloads:
        if payload.get("source_t0_sha256") != T0_DATASET_SHA256:
            raise ValueError("observation has wrong T0 hash")
        if payload.get("source_decision_sha256") != DECISION_ARTIFACT_SHA256:
            raise ValueError("observation has wrong decision hash")
        if payload.get("record_count") != 50 or len(payload.get("records", [])) != 50:
            raise ValueError("observation must contain exactly 50 records")

        block = int(payload["observed_block"])
        previous = by_block.get(block)
        if previous is not None and previous != payload:
            raise ValueError("conflicting observation payloads for same block")
        by_block[block] = payload

    return sorted(by_block.values(), key=lambda item: int(item["observed_block"]))


def _group_performance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "count": 0,
            "primary_events": 0,
            "event_rate": 0.0,
            "mean_model_risk_probability": 0.0,
            "brier_score": 0.0,
            "calibration_gap": 0.0,
            "absolute_calibration_gap": 0.0,
        }

    count = len(rows)
    events = sum(1 for row in rows if row["primary_adverse_event"])
    event_rate = events / count
    mean_probability = sum(row["model_risk_probability"] for row in rows) / count
    brier = sum(
        (
            row["model_risk_probability"]
            - (1 if row["primary_adverse_event"] else 0)
        )
        ** 2
        for row in rows
    ) / count
    gap = event_rate - mean_probability

    return {
        "count": count,
        "primary_events": events,
        "event_rate": round(event_rate, 6),
        "mean_model_risk_probability": round(mean_probability, 6),
        "brier_score": round(brier, 6),
        "calibration_gap": round(gap, 6),
        "absolute_calibration_gap": round(abs(gap), 6),
    }


def aggregate_checkpoint(
    *,
    decisions_payload: dict[str, Any],
    observation_payloads: list[dict[str, Any]],
    horizon_days: int,
    prior_checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if horizon_days not in VALID_HORIZONS:
        raise ValueError(f"horizon_days must be one of {VALID_HORIZONS}")
    if decisions_payload.get("record_count") != 50:
        raise ValueError("decision payload must contain 50 records")

    observations = _deduplicate_observations(observation_payloads)
    t0_dt = _parse_dt(T0_AT)
    target_dt = t0_dt + timedelta(days=horizon_days)
    latest_allowed = target_dt + timedelta(hours=FINAL_SAMPLE_MAX_DELAY_HOURS)

    final_candidates = [
        item
        for item in observations
        if target_dt <= _parse_dt(item["observed_at"]) <= latest_allowed
    ]
    final_observation = final_candidates[0] if final_candidates else None

    window_end = (
        _parse_dt(final_observation["observed_at"])
        if final_observation is not None
        else latest_allowed
    )
    window = [
        item
        for item in observations
        if t0_dt < _parse_dt(item["observed_at"]) <= window_end
    ]

    covered_dates = {
        _parse_dt(item["observed_at"]).date().isoformat()
        for item in window
        if t0_dt.date() < _parse_dt(item["observed_at"]).date() <= target_dt.date()
    }
    if prior_checkpoint:
        covered_dates.update(prior_checkpoint.get("coverage", {}).get("covered_utc_dates", []))

    expected_samples = horizon_days
    observed_samples = min(len(covered_dates), expected_samples)
    coverage_ratio = observed_samples / expected_samples if expected_samples else 0.0

    decisions = {
        row["wallet_address"].lower(): row for row in decisions_payload["records"]
    }
    if len(decisions) != 50:
        raise ValueError("decision payload must have 50 unique wallets")

    observations_by_wallet: dict[str, list[dict[str, Any]]] = {
        wallet: [] for wallet in decisions
    }
    for payload in window:
        for row in payload["records"]:
            wallet = row["wallet_address"].lower()
            if wallet not in observations_by_wallet:
                raise ValueError("observation contains wallet outside frozen cohort")
            observations_by_wallet[wallet].append(row)

    final_by_wallet: dict[str, dict[str, Any]] = {}
    if final_observation is not None:
        final_by_wallet = {
            row["wallet_address"].lower(): row
            for row in final_observation["records"]
        }

    prior_by_wallet: dict[str, dict[str, Any]] = {}
    if prior_checkpoint:
        prior_by_wallet = {
            row["wallet_address"].lower(): row
            for row in prior_checkpoint.get("records", [])
        }

    result_rows: list[dict[str, Any]] = []
    for wallet in sorted(decisions):
        decision = decisions[wallet]
        samples = observations_by_wallet[wallet]
        prior = prior_by_wallet.get(wallet)

        health_samples = [
            (float(row["health_factor"]), row)
            for row in samples
        ]
        min_hf: float | None = None
        min_hf_evidence: str | None = None

        if prior and prior.get("min_health_factor") is not None:
            min_hf = float(prior["min_health_factor"])
            min_hf_evidence = prior.get("min_health_factor_evidence_ref")

        if health_samples:
            sample_hf, sample_row = min(health_samples, key=lambda item: item[0])
            if min_hf is None or sample_hf < min_hf:
                min_hf = sample_hf
                min_hf_evidence = sample_row["state_evidence_ref"]

        liquidation_hashes: set[str] = set()
        if prior:
            liquidation_hashes.update(prior.get("liquidation_tx_hashes", []))
        for row in samples:
            liquidation_hashes.update(row.get("liquidation_tx_hashes", []))

        final = final_by_wallet.get(wallet)
        if final is None:
            final_hf = None
            final_debt = 0.0
            final_drawdown = None
            final_collateral = None
            final_evidence = None
        else:
            final_hf = float(final["health_factor"])
            final_debt = float(final["active_debt_usd"])
            final_drawdown = float(final["collateral_drawdown_pct_from_t0"])
            final_collateral = float(final["collateral_usd"])
            final_evidence = final["state_evidence_ref"]

        classification = classify_position_outcome(
            PositionOutcomeMetrics(
                liquidation_event=bool(liquidation_hashes),
                min_health_factor=min_hf,
                final_health_factor=final_hf,
                collateral_drawdown_pct=final_drawdown,
                final_debt_usd=final_debt,
            )
        )

        result_rows.append(
            {
                "decision_id": decision["decision_id"],
                "wallet_address": wallet,
                "paper_decision": decision["paper_decision"],
                "risk_score": int(decision["risk_score"]),
                "model_risk_probability": float(decision["model_risk_probability"]),
                "min_health_factor": min_hf,
                "min_health_factor_evidence_ref": min_hf_evidence,
                "final_health_factor": final_hf,
                "final_active_debt_usd": round(final_debt, 2),
                "final_collateral_usd": (
                    round(final_collateral, 2)
                    if final_collateral is not None
                    else None
                ),
                "final_collateral_drawdown_pct": final_drawdown,
                "final_state_evidence_ref": final_evidence,
                "liquidation_event": bool(liquidation_hashes),
                "liquidation_tx_hashes": sorted(liquidation_hashes),
                "primary_adverse_event": classification.primary_adverse_event,
                "secondary_distress_event": classification.secondary_distress_event,
                "outcome_reasons": list(classification.reasons),
            }
        )

    final_complete = final_observation is not None and len(final_by_wallet) == 50
    coverage_complete = coverage_ratio >= MIN_COVERAGE_RATIO
    status = "COMPLETE" if final_complete and coverage_complete else "INCOMPLETE"

    overall = _group_performance(result_rows)
    by_decision = {
        label: _group_performance(
            [row for row in result_rows if row["paper_decision"] == label]
        )
        for label in ("APPROVE_PAPER", "REVIEW_PAPER", "REJECT_PAPER")
    }
    false_negatives = [
        {
            "decision_id": row["decision_id"],
            "wallet_address": row["wallet_address"],
            "risk_score": row["risk_score"],
            "model_risk_probability": row["model_risk_probability"],
            "outcome_reasons": row["outcome_reasons"],
        }
        for row in result_rows
        if row["paper_decision"] == "APPROVE_PAPER"
        and row["primary_adverse_event"]
    ]

    return {
        "dataset": f"forward50-t{horizon_days}-checkpoint",
        "status": status,
        "observer_version": "forward-outcome-observer-v0.3.0",
        "model_version": MODEL_VERSION,
        "source_t0_sha256": T0_DATASET_SHA256,
        "source_decision_sha256": DECISION_ARTIFACT_SHA256,
        "horizon_days": horizon_days,
        "target_at": target_dt.isoformat(),
        "checkpoint_observed_at": (
            final_observation["observed_at"] if final_observation else None
        ),
        "checkpoint_observed_block": (
            final_observation["observed_block"] if final_observation else None
        ),
        "coverage": {
            "expected_daily_samples": expected_samples,
            "observed_unique_utc_days": observed_samples,
            "coverage_ratio": round(coverage_ratio, 6),
            "minimum_required_ratio": MIN_COVERAGE_RATIO,
            "covered_utc_dates": sorted(covered_dates),
        },
        "overall_performance": overall,
        "performance_by_paper_decision": by_decision,
        "false_negative_definition": (
            "APPROVE_PAPER at T0 and primary adverse event observed by checkpoint"
        ),
        "false_negative_count": len(false_negatives),
        "false_negative_cases": false_negatives,
        "record_count": len(result_rows),
        "records": result_rows,
    }


def aggregate_checkpoint_files(
    *,
    decisions_path: str | Path,
    observations_dir: str | Path,
    horizon_days: int,
    out_path: str | Path,
    prior_checkpoint_path: str | Path | None = None,
) -> dict[str, Any]:
    if _sha256_file(decisions_path) != DECISION_ARTIFACT_SHA256:
        raise ValueError("decision artifact hash does not match frozen commitment")
    decisions = json.loads(Path(decisions_path).read_text(encoding="utf-8"))

    observation_files = sorted(Path(observations_dir).rglob("observation.json"))
    if not observation_files:
        raise ValueError("no observation.json files found")
    payloads = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in observation_files
    ]

    prior: dict[str, Any] | None = None
    prior_hash: str | None = None
    if prior_checkpoint_path:
        prior_path = Path(prior_checkpoint_path)
        prior_hash = _sha256_file(prior_path)
        prior = json.loads(prior_path.read_text(encoding="utf-8"))

    checkpoint = aggregate_checkpoint(
        decisions_payload=decisions,
        observation_payloads=payloads,
        horizon_days=horizon_days,
        prior_checkpoint=prior,
    )
    if prior_hash:
        checkpoint["prior_checkpoint_sha256"] = prior_hash

    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(checkpoint, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output.write_bytes(raw)

    return {
        "status": checkpoint["status"],
        "horizon_days": horizon_days,
        "record_count": checkpoint["record_count"],
        "event_rate": checkpoint["overall_performance"]["event_rate"],
        "brier_score": checkpoint["overall_performance"]["brier_score"],
        "calibration_gap": checkpoint["overall_performance"]["calibration_gap"],
        "false_negative_count": checkpoint["false_negative_count"],
        "coverage_ratio": checkpoint["coverage"]["coverage_ratio"],
        "checkpoint_sha256": hashlib.sha256(raw).hexdigest(),
        "output": str(output),
    }
