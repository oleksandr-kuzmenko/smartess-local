# Agent guide for `smartess-local`

For AI coding agents asked to extend or fix `smartess-local`. Humans
should start with [`README.md`](README.md) and
[`docs/architecture.md`](docs/architecture.md).

`smartess-local` is a local-network Python client for hybrid inverters
with Eybond/SmartESS WiFi dongles. The MVP is read-only monitoring of
holding registers 201..234 (29 named fields), built to feed Home
Assistant without the vendor cloud. The package is public on PyPI —
assume any change is visible to outside users.

## Toolchain

Python 3.12+. Bootstrap a fresh checkout:

```bash
uv venv --python 3.12 .venv
VIRTUAL_ENV=$PWD/.venv uv pip install -e ".[dev]"
```

## Verification gate

Run all three before every commit; they must all be green:

```bash
.venv/bin/pytest
.venv/bin/ruff check smartess_local tests
.venv/bin/mypy smartess_local
```

mypy runs in strict mode. Don't `--no-verify`; fix the underlying issue.

## TDD

Write the failing test first, implement the minimum to pass, then run
the full gate before committing. Pure functions (`protocol.py`,
`registers.py`, `state.py`) are pinned to vendor vectors. Network code
(`inverter.py`) is exercised via the `FakeDongle` loopback fixture in
`tests/conftest.py` — don't mock sockets; the fixture runs real
localhost UDP+TCP so tests catch asyncio lifecycle bugs.

## Where to look

| Question | File |
|----------|------|
| What is this project? | [`README.md`](README.md) |
| How are the modules wired up? | [`docs/architecture.md`](docs/architecture.md) |
| What do bytes on the wire look like? | [`docs/protocol.md`](docs/protocol.md) |
| Where do the protocol facts come from? | [`docs/data-source.md`](docs/data-source.md) |
| Authoritative wire-format spec | [`docs/vendor/modbus-protocol-v11.html`](docs/vendor/modbus-protocol-v11.html) |

## Don'ts

- No destructive git (`reset --hard`, force-push, branch -D) without
  explicit consent for the specific action.
- No implementation work on `main` without consent; use a branch.
- Don't write comments that restate the code. Save comments for the
  non-obvious *why*.
- Don't put dates, decision logs, or planning artefacts in the repo.
