# smartess-local

[![Tests](https://github.com/oleksandr-kuzmenko/smartess-local/actions/workflows/test.yml/badge.svg)](https://github.com/oleksandr-kuzmenko/smartess-local/actions/workflows/test.yml)

Local-network Python client for hybrid inverters with Eybond/SmartESS
WiFi dongles (Aninerel 6.2kW, ANENJI 4–7.2kW, and
other Voltronic-based rebrands). Designed as a thin transport layer
for Home Assistant integrations without depending on the vendor cloud.

> **Status:** MVP — read-only monitoring of registers 201–234
> (29 named fields).
>
> **Heads up:** this is a vibe-coded hobby project, not affiliated with
> Eybond/SmartESS and not extensively field-tested. Use it at your own
> risk. Questions, ideas, and pull requests are very welcome — open an
> issue or a discussion.

## Install

```bash
pip install smartess-local   # no runtime dependencies (stdlib only)
```

Python 3.12+ required.

## Quick start

### Python

```python
import asyncio
from smartess_local import Inverter

async def main():
    async with Inverter(inverter_ip="192.168.0.119", local_ip="192.168.0.110") as inv:
        state = await inv.read()
        print(state.battery_percentage, state.pv_power, state.working_mode)

asyncio.run(main())
```

`inverter_ip` is the dongle's IP on your LAN; `local_ip` is this
machine's interface the dongle dials back into over TCP (see
[How it works](#how-it-works)).

### CLI

```bash
# Sanity check: verify the dongle responds and print its DevCode.
python -m smartess_local --inverter-ip 192.168.0.119 --local-ip 192.168.0.110 --probe

# One snapshot of all 29 fields as pretty-printed JSON.
python -m smartess_local --inverter-ip 192.168.0.119 --local-ip 192.168.0.110

# Continuous JSON Lines, one reading per --interval seconds. Ctrl+C to stop.
python -m smartess_local --inverter-ip 192.168.0.119 --local-ip 192.168.0.110 \
    --stream --interval 10
```

Flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--inverter-ip` | (required) | IP of the inverter's dongle on your LAN |
| `--local-ip` | (required) | This machine's IP the dongle dials back into |
| `--local-port` | `8899` | TCP listener port on this machine |
| `--timeout` | `5.0` | Per-operation socket timeout (seconds) |
| `--interval` | `10.0` | Seconds between reads in `--stream` mode |
| `--log-level` | `INFO` | Python logging level (INFO shows the layout hex on the first read) |
| `--probe` | | UDP bootstrap only; print `{"dev_code": N}` and exit |
| `--stream` | | JSON Lines forever (mutually exclusive with `--probe`) |

## Compatible inverters

Any inverter using the Eybond/SmartESS WiFi dongle family. Verified on
Aninerel 6.2kW; the ANENJI 4–7.2kW and other Voltronic-based rebrands of
the same chipset are expected to work.

## How it works

The dongle exposes a reverse-tunnel handshake on the LAN: the client
sends one UDP datagram (`set>server=...`) to tell the dongle where to
connect, the dongle TCP-dials back into that address, and Modbus RTU
frames then flow over the single open TCP connection. `smartess-local`
opens a TCP server (not a client), waits for the dongle to connect,
then reads holding registers 201..234 on demand.

See [`docs/architecture.md`](docs/architecture.md) for the module map
and lifecycle, [`docs/protocol.md`](docs/protocol.md) for the byte-level
frame layout, and [`docs/data-source.md`](docs/data-source.md) for the
provenance of every protocol claim.

## Tip: block the dongle's internet access

Do the dongle's **first-time WiFi setup with internet access** — the initial
pairing through the SmartESS app appears to need the vendor cloud and won't
complete offline. Once it's set up and this integration works, you can block
the dongle from the public internet (block its MAC at the router, or put it on
a LAN-only VLAN). The [.NET donor repo](https://github.com/sabatex/NetDaemonApps.InverterAnenji-4kw-7.2kw)
recommends this: when the dongle is busy talking to Eybond's cloud in parallel,
the LAN-side TCP connection becomes flakier.

## Acknowledgements

- [sabatex/NetDaemonApps.InverterAnenji-4kw-7.2kw](https://github.com/sabatex/NetDaemonApps.InverterAnenji-4kw-7.2kw) —
  the .NET / NetDaemon reference implementation we used as an executable
  specification to pin the CRC algorithm and the reverse-tunnel
  handshake byte-for-byte.
- The Eybond/SmartESS dongle protocol document
  ([`docs/vendor/modbus-protocol-v11.html`](docs/vendor/modbus-protocol-v11.html))
  — authoritative for the wire format and the holding-register table.

## Contributing

This is a hobby project, but contributions are genuinely welcome — open
an issue to discuss an idea or a bug, or send a pull request.

For AI agents (Claude Code, Codex, Copilot, Gemini): see
[`AGENTS.md`](AGENTS.md) for the workflow, verification gate, and
project conventions.

For humans extending the package: start with
[`docs/architecture.md`](docs/architecture.md). The verification gate
(`pytest` + `ruff` + `mypy --strict`) must stay green on every commit.

## License

MIT — see [`LICENSE`](LICENSE).
