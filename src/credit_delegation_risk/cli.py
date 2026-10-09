from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .portfolio import build_paper_portfolio
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="credit-risk")
    sub = parser.add_subparsers(dest="command", required=True)

    synthetic = sub.add_parser("synthetic100", help="Generate the deterministic Synthetic 100 benchmark")
    synthetic.add_argument("--out", default="data/generated")
    synthetic.add_argument("--seed", type=int, default=42)

    args = parser.parse_args()
    if args.command == "synthetic100":
        print(json.dumps(run_synthetic100(args.out, args.seed), indent=2))


if __name__ == "__main__":
    main()
