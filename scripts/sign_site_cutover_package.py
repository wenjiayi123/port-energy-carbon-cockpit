#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.schemas.site_cutover import SiteCutoverRequest  # noqa: E402
from app.services.site_cutover import (  # noqa: E402
    approval_subject_sha256,
    canonical_sha256,
)


PLACEHOLDER_SIGNATURE = base64.b64encode(b"\x00" * 64).decode("ascii")


def _private_key(value: str) -> Ed25519PrivateKey:
    raw = base64.b64decode(value, validate=True)
    if len(raw) != 32:
        raise ValueError("Ed25519 private keys must contain 32 raw bytes")
    return Ed25519PrivateKey.from_private_bytes(raw)


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _public_key(private_key: Ed25519PrivateKey) -> str:
    return base64.b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")


def sign_package(
    payload: dict[str, Any],
    module_signers: dict[str, dict[str, str]],
    approval_signers: dict[str, dict[str, str]],
) -> tuple[SiteCutoverRequest, dict[str, dict[str, str]]]:
    trusted_signers: dict[str, dict[str, str]] = {}
    for module in payload.get("module_evidence", []):
        domain = str(module.get("domain"))
        signer = module_signers.get(domain)
        if not signer:
            raise ValueError(f"missing module signer for {domain}")
        key_id = str(signer["key_id"])
        private_key = _private_key(str(signer["private_key_base64"]))
        module["key_id"] = key_id
        module.pop("signed_payload_sha256", None)
        module.pop("signature", None)
        digest = canonical_sha256(module)
        module["signed_payload_sha256"] = digest
        module["signature"] = base64.b64encode(
            private_key.sign(bytes.fromhex(digest))
        ).decode("ascii")
        trusted_signers[key_id] = {
            "public_key": _public_key(private_key),
            "authority": domain,
        }

    for approval in payload.get("approvals", []):
        approval["acceptance_package_sha256"] = "0" * 64
        approval["signature"] = PLACEHOLDER_SIGNATURE
    provisional = SiteCutoverRequest(**payload)
    subject = approval_subject_sha256(provisional)

    for approval in payload.get("approvals", []):
        role = str(approval.get("role"))
        signer = approval_signers.get(role)
        if not signer:
            raise ValueError(f"missing approval signer for {role}")
        key_id = str(signer["key_id"])
        private_key = _private_key(str(signer["private_key_base64"]))
        approval["key_id"] = key_id
        approval["acceptance_package_sha256"] = subject
        approval["signature"] = base64.b64encode(
            private_key.sign(bytes.fromhex(subject))
        ).decode("ascii")
        trusted_signers[key_id] = {
            "public_key": _public_key(private_key),
            "authority": role,
        }
    return SiteCutoverRequest(**payload), trusted_signers


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sign a complete site-cutover package with independent Ed25519 authorities."
    )
    parser.add_argument("--input", required=True, help="Unsigned site-cutover JSON package")
    parser.add_argument(
        "--module-signers-json",
        required=True,
        help="JSON mapping each module domain to key_id and private_key_base64",
    )
    parser.add_argument(
        "--approval-signers-json",
        required=True,
        help="JSON mapping each approval role to key_id and private_key_base64",
    )
    parser.add_argument("--output", required=True, help="Signed package output path")
    parser.add_argument(
        "--trusted-signers-output",
        required=True,
        help="Public SITE_CUTOVER_TRUSTED_SIGNERS_JSON output path",
    )
    args = parser.parse_args()

    request, trusted_signers = sign_package(
        _load_json(args.input),
        _load_json(args.module_signers_json),
        _load_json(args.approval_signers_json),
    )
    Path(args.output).write_text(
        json.dumps(request.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    Path(args.trusted_signers_output).write_text(
        json.dumps(trusted_signers, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
