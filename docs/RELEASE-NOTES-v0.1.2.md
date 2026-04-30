# v0.1.2

Security hardening + e2e test coverage. No API or CLI break.

## Security

- **CRIT-1**: validate `REF` env var — reject git-ref injection (`install.sh`).
- **CRIT-2**: commit message newline injection blocked (`commit.py`).
- **RT-H1**: warn + interactive confirm when running unpinned branch.
- **RT-H2**: scrub Claude subprocess environment (drop secrets/tokens).
- **RT-H3**: NUL-delimited blast guard for staged path enumeration.
- Hardened `review` flow against prompt-injection vectors.

See `docs/SECURITY-FIX-PLAN-v0.1.1.md` and `docs/SECURITY-REVIEW-v0.1.1.md`.

## Features

- Stage `create-readme` skill into target repo (`4edab42`).
- End-to-end security test suite (`452000c`).

## Fixes

- README curl link points at correct repo slug.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/salamientark/writeme/release/v0.1.2/install.sh | bash
```

`EXPECTED_SHA` pinned by CI on the `release/v0.1.2` branch.

## Verify

- Tampered SHA → exit `3`.
- Sandbox wiped on success, preserved on failure.
