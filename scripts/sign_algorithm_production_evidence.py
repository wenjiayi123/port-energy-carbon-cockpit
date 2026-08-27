#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
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

from app.schemas.algorithm_production import (  # noqa: E402
    SOURCE_DOMAINS,
    AlgorithmProductionQualificationRequest,
)
from app.services.algorithm_production import (  # noqa: E402
    canonical_sha256,
    source_domain_payload,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Sign exactly one algorithm production-evidence domain in a complete "
            "qualification request with its source owner's Ed25519 private key."
        )
    )
    parser.add_argument(
        "--input", required=True, help="Complete qualification request JSON"
    )
    parser.add_argument("--domain", required=True, choices=sorted(SOURCE_DOMAINS))
    parser.add_argument(
        "--private-key", required=True, help="PEM Ed25519 private-key file"
    )
    parser.add_argument("--key-id", required=True, help="Trusted source-system key ID")
    parser.add_argument(
        "--output", required=True, help="Updated qualification request JSON"
    )
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    private_key_path = Path(args.private_key).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    attestations = payload.get("source_attestations")
    if not isinstance(attestations, list):
        parser.error("input must contain source_attestations")
    matches = [item for item in attestations if item.get("domain") == args.domain]
    if len(matches) != 1:
        parser.error(f"input must contain exactly one attestation for {args.domain}")

    target = matches[0]
    target["key_id"] = args.key_id
    target["signed_payload_sha256"] = "0" * 64
    target["signature"] = base64.b64encode(b"0" * 64).decode("ascii")
    request = AlgorithmProductionQualificationRequest(**payload)
    signed_payload_sha256 = canonical_sha256(
        source_domain_payload(request, args.domain)
    )

    private_key = serialization.load_pem_private_key(
        private_key_path.read_bytes(),
        password=None,
    )
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("--private-key must contain an Ed25519 private key")
    target["signed_payload_sha256"] = signed_payload_sha256
    target["signature"] = base64.b64encode(
        private_key.sign(bytes.fromhex(signed_payload_sha256))
    ).decode("ascii")
    AlgorithmProductionQualificationRequest(**payload)

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
                "domain": args.domain,
                "key_id": args.key_id,
                "signed_payload_sha256": signed_payload_sha256,
                "public_key_base64": public_key_b64,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
