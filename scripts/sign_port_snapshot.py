#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from app.integration.gateway import SnapshotEnvelope, canonical_json


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a signed port-snapshot.v1 envelope without exposing the secret on argv"
    )
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--port-id", required=True)
    parser.add_argument("--source-system", required=True)
    parser.add_argument("--source-record-id", required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--sequence", type=int, required=True)
    parser.add_argument("--observed-at", type=parse_timestamp, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--units", type=Path, required=True)
    parser.add_argument("--secret-env", default="PORT_SNAPSHOT_SIGNING_SECRET")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    secret = os.environ.get(args.secret_env, "")
    if len(secret) < 32:
        parser.error(f"{args.secret_env} must contain at least 32 characters")
    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    units = json.loads(args.units.read_text(encoding="utf-8"))
    envelope = SnapshotEnvelope(
        snapshot_id=args.snapshot_id,
        port_id=args.port_id,
        adapter_id=args.adapter,
        source_system=args.source_system,
        source_record_id=args.source_record_id,
        sequence=args.sequence,
        observed_at=args.observed_at,
        received_at=datetime.now(timezone.utc),
        payload=payload,
        units=units,
        payload_sha256=hashlib.sha256(canonical_json(payload)).hexdigest(),
    ).signed(secret)
    serialized = json.dumps(envelope.model_dump(mode="json"), ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(serialized + "\n", encoding="utf-8")
        temporary.replace(args.output)
    else:
        sys.stdout.write(serialized + "\n")


if __name__ == "__main__":
    main()
