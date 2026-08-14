# Historical path redaction record

On 2026-08-14, local absolute workspace prefixes were replaced with portable repository-relative
paths in the archived 100k TD3 report. No model, dataset, metric, timestamp, policy decision,
admission check, trajectory, or artifact SHA-256 value was changed.

| File | Original file SHA-256 | Portable file SHA-256 | Redacted fields |
| --- | --- | --- | --- |
| `evaluation.json` | `ba57a7116da2eae33c45fbe4f54cdca092394167db4e4ac85da02c12dfb47197` | `1ac1f74a962271a74d431fc659a6e6b7650c2f543b620c50473abbca7c32e824` | `policy.artifact_path` |
| `manifest.json` | `b2580c63469a2d8a88bd5fe30d3ad8c15e50f9b80f77383b42700ba3663bfa1d` | `c82b2cc7ecf16999bd2e6799358f76d29c65664ce60c20348d8381e1a7127c8d` | `run_dir`, `artifact_path` |
| `verification.json` | `160ad2152acbf0ac0c2131aa0afa6a666994cf65b04b3b7e99c9c063dfed1fa8` | `919d704cb7e15539ff6024433f8020de3d5883103695ba5f7c658763dd5662ab` | `evaluation.policy.artifact_path` |

The trained artifact remains identified by SHA-256
`d2b5e4881ef3753b3be02df45dd84951bf0d1507d92adb1c708d4a90caf3efa6`, and the dataset remains
identified by SHA-256 `fbb3d1c34ccad61214119b600f09e8a6c37c13826fad6e4dde0c33cdc821758e`.
