#!/usr/bin/env python3
"""Run the Python supply-chain gate with one documented local exception.

Intel macOS cannot resolve a supported modern PyTorch wheel for this repository's
optional neural-RL compatibility environment. That platform may keep the
known-vulnerable ``torch==2.2.2`` package for trusted, local-only compatibility,
but every core/data dependency must remain clean. Linux and Apple Silicon fail
closed on every reported vulnerability.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from typing import Any


def _audit() -> tuple[int, dict[str, Any], str]:
    result = subprocess.run(
        [sys.executable, "-m", "pip_audit", "--skip-editable", "-f", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        detail = result.stderr.strip() or result.stdout.strip() or "no audit output"
        raise RuntimeError(f"pip-audit did not return JSON: {detail}") from exc
    return result.returncode, payload, result.stderr.strip()


def _findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for dependency in payload.get("dependencies", []):
        vulnerabilities = dependency.get("vulns", [])
        if vulnerabilities:
            findings.append(
                {
                    "name": dependency.get("name", "unknown"),
                    "version": dependency.get("version", "unknown"),
                    "ids": [item.get("id", "unknown") for item in vulnerabilities],
                }
            )
    return findings


def main() -> int:
    try:
        returncode, payload, stderr = _audit()
    except (OSError, RuntimeError) as exc:
        print(f"python dependency audit: FAIL: {exc}", file=sys.stderr)
        return 1

    findings = _findings(payload)
    if not findings:
        if returncode not in (0, 1):
            print(
                f"python dependency audit: FAIL: pip-audit exited {returncode}: {stderr}",
                file=sys.stderr,
            )
            return 1
        print("python dependency audit: PASS (no known vulnerabilities)")
        return 0

    intel_macos = platform.system() == "Darwin" and platform.machine() == "x86_64"
    torch_only = all(item["name"].lower() == "torch" for item in findings)
    if intel_macos and torch_only:
        count = sum(len(item["ids"]) for item in findings)
        versions = ", ".join(
            f"{item['name']}=={item['version']}" for item in findings
        )
        print(
            "python dependency audit: PASS WITH DOCUMENTED LOCAL EXCEPTION "
            f"({count} finding(s) confined to {versions} on Intel macOS; "
            "neural training is disabled here and Linux CI/container is authoritative)"
        )
        return 0

    print("python dependency audit: FAIL", file=sys.stderr)
    for item in findings:
        print(
            f"- {item['name']}=={item['version']}: {', '.join(item['ids'])}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
