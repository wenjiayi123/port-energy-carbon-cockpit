#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.schemas.energy_carbon_management import (  # noqa: E402
    EnergyCarbonManagementRequest,
)


def canonical_sha256(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Sign an energy-carbon management-system evidence cycle with an "
            "independent Ed25519 private key."
        )
    )
    parser.add_argument("--input", required=True, help="Unsigned JSON evidence package")
    parser.add_argument("--private-key", required=True, help="PEM Ed25519 private-key file")
    parser.add_argument("--key-id", required=True, help="Trusted assurance key ID")
    parser.add_argument("--output", required=True, help="Signed JSON output path")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    private_key_path = Path(args.private_key).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    assurance = dict(payload.get("independent_assurance") or {})
    assurance["key_id"] = args.key_id
    assurance["signed_evidence_sha256"] = "0" * 64
    assurance["signature"] = base64.b64encode(b"0" * 64).decode("ascii")
    payload["independent_assurance"] = assurance

    provisional = EnergyCarbonManagementRequest(**payload).model_dump(mode="json")
    unsigned_assurance = dict(provisional["independent_assurance"])
    unsigned_assurance.pop("signature")
    unsigned_assurance.pop("signed_evidence_sha256")
    provisional["independent_assurance"] = unsigned_assurance
    signed_evidence_sha256 = canonical_sha256(provisional)

    private_key = serialization.load_pem_private_key(
        private_key_path.read_bytes(),
        password=None,
    )
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("--private-key must contain an Ed25519 private key")
    signature = private_key.sign(bytes.fromhex(signed_evidence_sha256))
    payload["independent_assurance"]["signed_evidence_sha256"] = (
        signed_evidence_sha256
    )
    payload["independent_assurance"]["signature"] = base64.b64encode(
        signature
    ).decode("ascii")
    EnergyCarbonManagementRequest(**payload)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    public_key = private_key.public_key()
    if not isinstance(public_key, Ed25519PublicKey):
        raise ValueError("unable to derive Ed25519 public key")
    public_key_b64 = base64.b64encode(
        public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    print(
        json.dumps(
            {
                "output": str(output_path),
                "key_id": args.key_id,
                "signed_evidence_sha256": signed_evidence_sha256,
                "public_key_base64": public_key_b64,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
