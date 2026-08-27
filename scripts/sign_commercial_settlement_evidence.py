#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.schemas.commercial_settlement import (  # noqa: E402
    SOURCE_DOMAINS,
    CommercialSettlementRequest,
)
from app.services.commercial_settlement import (  # noqa: E402
    canonical_sha256,
    source_domain_payload,
)


def _mapping(values: list[str], option: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        domain, separator, mapped = value.partition("=")
        if not separator or domain not in SOURCE_DOMAINS or not mapped:
            raise ValueError(f"{option} must use DOMAIN=VALUE for every required domain")
        if domain in result:
            raise ValueError(f"duplicate {option} domain: {domain}")
        result[domain] = mapped
    missing = SOURCE_DOMAINS - set(result)
    if missing:
        raise ValueError(f"{option} missing domains: {', '.join(sorted(missing))}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sign all eight commercial-settlement source domains with Ed25519 keys."
    )
    parser.add_argument("--input", required=True, help="Unsigned JSON evidence package")
    parser.add_argument(
        "--private-key",
        action="append",
        required=True,
        metavar="DOMAIN=PEM_PATH",
        help="Repeat once for each of the eight source domains",
    )
    parser.add_argument(
        "--key-id",
        action="append",
        required=True,
        metavar="DOMAIN=KEY_ID",
        help="Repeat once for each of the eight source domains",
    )
    parser.add_argument("--output", required=True, help="Signed JSON output path")
    args = parser.parse_args()

    private_key_paths = _mapping(args.private_key, "--private-key")
    key_ids = _mapping(args.key_id, "--key-id")
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    attestations = {
        item.get("domain"): dict(item) for item in payload.get("source_attestations", [])
    }
    if set(attestations) != SOURCE_DOMAINS:
        raise ValueError("input source_attestations must contain every source domain exactly once")

    for domain in SOURCE_DOMAINS:
        attestations[domain]["key_id"] = key_ids[domain]
        attestations[domain]["signed_payload_sha256"] = "0" * 64
        attestations[domain]["signature"] = base64.b64encode(b"0" * 64).decode("ascii")
    payload["source_attestations"] = [attestations[item] for item in sorted(SOURCE_DOMAINS)]
    provisional = CommercialSettlementRequest(**payload)

    public_keys: dict[str, str] = {}
    for domain in sorted(SOURCE_DOMAINS):
        digest = canonical_sha256(source_domain_payload(provisional, domain))
        private_key_path = Path(private_key_paths[domain]).expanduser().resolve()
        private_key = serialization.load_pem_private_key(
            private_key_path.read_bytes(),
            password=None,
        )
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError(f"private key for {domain} must be Ed25519")
        attestations[domain]["signed_payload_sha256"] = digest
        attestations[domain]["signature"] = base64.b64encode(
            private_key.sign(bytes.fromhex(digest))
        ).decode("ascii")
        public_keys[key_ids[domain]] = base64.b64encode(
            private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")

    payload["source_attestations"] = [attestations[item] for item in sorted(SOURCE_DOMAINS)]
    CommercialSettlementRequest(**payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output_path),
                "domains": sorted(SOURCE_DOMAINS),
                "commercial_settlement_public_keys_json": json.dumps(
                    public_keys, separators=(",", ":")
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
