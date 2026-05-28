"""Command-line entry point for the smartess_local package.

Invoked as `python -m smartess_local --inverter-ip ... --local-ip ...`. See the
`_build_parser` source for the full flag list.

Three modes (mutually exclusive):
  - `--probe`: UDP bootstrap only; print the dev_code and exit.
  - `--stream`: continuous JSON Lines, one per read, until Ctrl+C.
  - default (no flag): one read, pretty-printed JSON, exit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import asdict
from typing import Any

from smartess_local.inverter import Inverter, InverterError
from smartess_local.state import InverterState

_JSON_INDENT = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smartess_local",
        description="Local-network client for Eybond/SmartESS hybrid inverters.",
    )
    parser.add_argument(
        "--inverter-ip", required=True, help="Inverter dongle's IP address on your LAN."
    )
    parser.add_argument(
        "--local-ip",
        required=True,
        help="This machine's IP that the dongle dials back to over TCP.",
    )
    parser.add_argument("--local-port", type=int, default=8899)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument(
        "--interval", type=float, default=10.0, help="Seconds between reads in --stream."
    )
    parser.add_argument("--log-level", default="INFO")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--probe",
        action="store_true",
        help="Only perform UDP bootstrap; print dev_code and exit.",
    )
    mode.add_argument(
        "--stream",
        action="store_true",
        help="Stream readings forever as JSON Lines.",
    )
    return parser


def _state_to_jsonable(state: InverterState) -> dict[str, Any]:
    """Convert an InverterState into a plain JSON-serialisable dict.

    Only two fields aren't JSON-native: working_mode (a WorkingMode IntEnum,
    which json.dumps would emit as a bare int) and the datetime timestamp.
    """
    data = asdict(state)
    data["working_mode"] = state.working_mode.name
    data["timestamp"] = state.timestamp.isoformat()
    return data


async def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    inverter = Inverter(
        inverter_ip=args.inverter_ip,
        local_ip=args.local_ip,
        local_port=args.local_port,
        timeout=args.timeout,
    )
    try:
        if args.probe:
            # Probe only does UDP — no TCP listener, no dial-back. This works
            # even when the dongle's subnet can't route back to --local-ip.
            dev_code = await inverter.probe()
            print(json.dumps({"dev_code": dev_code}, indent=_JSON_INDENT))
            return 0
        async with inverter:
            if args.stream:
                with suppress(KeyboardInterrupt, asyncio.CancelledError):
                    async for state in inverter.stream(interval=args.interval):
                        print(json.dumps(_state_to_jsonable(state)), flush=True)
                return 0
            state = await inverter.read()
            print(json.dumps(_state_to_jsonable(state), indent=_JSON_INDENT))
            return 0
    except (InverterError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
