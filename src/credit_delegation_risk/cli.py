from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

from .live_aave import build_live_forward50, write_forward50
from .observer import aggregate_checkpoint_files, observe_forward50_files
from .portfolio import build_paper_portfolio
from .position_model import freeze_decisions_file
from .rpc import JsonRpcClient
from .synthetic import generate_borrowers


def _write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _summary(rows: list[dict]) -> dict:
    decisions = {"APPROVE": 0, "REVIEW": 0, "REJECT": 0}
    for row in rows:
        decisions[row["decision"]] += 1

    approved_exposure = sum(row["credit_limit_usd"] for row in rows)
    avg_score = round(sum(row["risk_score"] for row in rows) / len(rows), 2)
    avg_pd = round(sum(row["estimated_pd"] for row in rows) / len(rows), 4)

    return {
        "borrowers": len(rows),
        "decisions": decisions,
        "paper_credit_limit_total_usd": approved_exposure,
        "average_risk_score": avg_score,
        "average_estimated_pd": avg_pd,
    }


def run_synthetic100(out_dir: str, seed: int) -> dict:
    borrowers = generate_borrowers(count=100, seed=seed)
    rows = build_paper_portfolio(borrowers)
    out = Path(out_dir)
    _write_csv(rows, out / "synthetic100.csv")

    summary = _summary(rows)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def run_forward50(out_path: str, snapshot_block: int | None) -> dict:
    rpc_url = os.environ.get("AAVE_RPC_URL", "")
    if not rpc_url:
        raise SystemExit("AAVE_RPC_URL is required for live Forward 50 collection")

    rpc = JsonRpcClient(rpc_url)
    records = build_live_forward50(rpc, snapshot_block=snapshot_block)
    path = write_forward50(records, out_path)
    return {
        "records": len(records),
        "snapshot_block": records[0].snapshot_block,
        "snapshot_at": records[0].snapshot_at,
        "output": str(path),
    }


def run_observer(
    t0_path: str,
    decisions_path: str,
    out_path: str,
    observed_block: int | None,
) -> dict:
    rpc_url = os.environ.get("AAVE_RPC_URL", "")
    if not rpc_url:
        raise SystemExit("AAVE_RPC_URL is required for Forward 50 observation")
    rpc = JsonRpcClient(rpc_url)
    return observe_forward50_files(
        rpc,
        t0_path=t0_path,
        decisions_path=decisions_path,
        out_path=out_path,
        observed_block=observed_block,
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="credit-risk")
    sub = parser.add_subparsers(dest="command", required=True)

    synthetic = sub.add_parser("synthetic100", help="Generate the deterministic Synthetic 100 benchmark")
    synthetic.add_argument("--out", default="data/generated")
    synthetic.add_argument("--seed", type=int, default=42)

    forward = sub.add_parser(
        "forward50-live",
        help="Collect the pre-registered live Aave v3 Ethereum Forward 50 T0 cohort",
    )
    forward.add_argument("--out", default="data/forward50/t0.json")
    forward.add_argument("--snapshot-block", type=int, default=None)

    decisions = sub.add_parser(
        "forward50-freeze-decisions",
        help="Freeze the v0.2 position-risk baseline decisions from an existing T0 cohort",
    )
    decisions.add_argument("--t0", default="data/forward50/t0.json")
    decisions.add_argument("--out", default="data/forward50/t0_decisions.json")

    observer = sub.add_parser(
        "forward50-observe",
        help="Observe the frozen Forward 50 cohort without changing T0 predictions",
    )
    observer.add_argument("--t0", required=True)
    observer.add_argument("--decisions", required=True)
    observer.add_argument("--out", default="data/forward50/observation.json")
    observer.add_argument("--observed-block", type=int, default=None)

    checkpoint = sub.add_parser(
        "forward50-checkpoint",
        help="Aggregate retained Forward 50 observations at T+30/T+60/T+90",
    )
    checkpoint.add_argument("--decisions", required=True)
    checkpoint.add_argument("--observations-dir", required=True)
    checkpoint.add_argument("--horizon", type=int, choices=[30, 60, 90], required=True)
    checkpoint.add_argument("--prior-checkpoint", default=None)
    checkpoint.add_argument("--out", default="data/forward50/checkpoint.json")

    args = parser.parse_args()
    if args.command == "synthetic100":
        print(json.dumps(run_synthetic100(args.out, args.seed), indent=2))
    elif args.command == "forward50-live":
        print(json.dumps(run_forward50(args.out, args.snapshot_block), indent=2))
    elif args.command == "forward50-freeze-decisions":
        print(json.dumps(freeze_decisions_file(args.t0, args.out), indent=2))
    elif args.command == "forward50-observe":
        print(
            json.dumps(
                run_observer(
                    args.t0,
                    args.decisions,
                    args.out,
                    args.observed_block,
                ),
                indent=2,
            )
        )
    elif args.command == "forward50-checkpoint":
        print(
            json.dumps(
                aggregate_checkpoint_files(
                    decisions_path=args.decisions,
                    observations_dir=args.observations_dir,
                    horizon_days=args.horizon,
                    out_path=args.out,
                    prior_checkpoint_path=args.prior_checkpoint,
                ),
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
