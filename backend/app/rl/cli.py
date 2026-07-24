from __future__ import annotations

import argparse
import json
import time

from app.rl.catalog import algorithm_items
from app.rl.dataset import DEFAULT_DATASET_ID, PortDataset
from app.rl.training import training_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Energy/carbon port RL pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("algorithms", help="List the four RL algorithms and MPC baseline")
    validate = subparsers.add_parser("validate-data", help="Validate a replacement port dataset")
    validate.add_argument("dataset")
    train = subparsers.add_parser("train", help="Train on the dataset's train split without rendering")
    train.add_argument("--algorithm", choices=[item["id"] for item in algorithm_items()], default="sac")
    train.add_argument("--dataset", default=DEFAULT_DATASET_ID)
    train.add_argument("--steps", "--total-steps", dest="steps", type=int, default=10_000)
    train.add_argument("--seed", type=int, default=20260720)
    evaluate = subparsers.add_parser("evaluate", help="Render and evaluate a saved policy on the test split")
    evaluate.add_argument("strategy_id", nargs="?", default=None)
    evaluate.add_argument("--strategy", dest="strategy_option", default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "algorithms":
        print(json.dumps(algorithm_items(), ensure_ascii=False, indent=2))
        return
    if args.command == "validate-data":
        print(json.dumps(PortDataset.load(args.dataset).describe(), ensure_ascii=False, indent=2))
        return
    if args.command == "evaluate":
        print(json.dumps(training_service.evaluate(args.strategy_option or args.strategy_id or "auto:latest"), ensure_ascii=False, indent=2))
        return
    status = training_service.start({"algorithm": args.algorithm, "dataset_id": args.dataset, "total_steps": args.steps, "seed": args.seed})
    while status["status"] in {"running", "paused", "stopping"}:
        print(f"{status['status']} step={status['step']}/{status['total_steps']} progress={status['progress']:.2f}%")
        time.sleep(1.0)
        status = training_service.status()
    print(json.dumps(status, ensure_ascii=False, indent=2))
    if status["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
