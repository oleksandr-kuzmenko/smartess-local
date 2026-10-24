"""Unit tests for smartess_local.cli."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import UTC
from datetime import datetime as _datetime

import pytest

from smartess_local.cli import _build_parser, _state_to_jsonable
from smartess_local.state import InverterState
from smartess_local.state import WorkingMode as _WM


def test_build_parser_accepts_minimal_args() -> None:
    parser = _build_parser()
    args = parser.parse_args(["--inverter-ip", "1.2.3.4", "--local-ip", "5.6.7.8"])
    assert args.inverter_ip == "1.2.3.4"
    assert args.local_ip == "5.6.7.8"
    assert args.local_port == 8899
    assert args.timeout == 5.0
    assert args.interval == 10.0
    assert args.log_level == "INFO"
    assert args.probe is False
    assert args.stream is False


def test_build_parser_probe_and_stream_are_mutually_exclusive() -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["--inverter-ip", "h", "--local-ip", "b", "--probe", "--stream"]
        )


def test_state_to_jsonable_converts_datetime_and_working_mode() -> None:
    # WorkingMode -> str (IntEnum bypasses json default hook); datetime -> ISO.
    state = _canned_state()
    result = _state_to_jsonable(state)
    assert result["working_mode"] == "MAINS"
    assert result["timestamp"] == "2026-05-21T12:00:00+00:00"
    # Non-special fields pass through untouched.
    assert result["battery_percentage"] == 78
    assert result["grid_voltage"] == 230.5


@dataclass
class _FakeInverter:
    inverter_ip: str
    local_ip: str
    local_port: int = 8899
    inverter_udp_port: int = 58899
    timeout: float = 5.0
    slave_id: int = 1
    logger: object = None
    dev_code: int | None = field(default=None, init=False)

    async def __aenter__(self) -> _FakeInverter:
        self.dev_code = 12345
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def probe(self) -> int:
        self.dev_code = 12345
        return self.dev_code

    async def read(self) -> InverterState:
        return _canned_state()

    async def stream(self, *, interval: float = 10.0) -> AsyncIterator[InverterState]:
        while True:
            yield await self.read()
            await asyncio.sleep(interval)


def _canned_state() -> InverterState:
    return InverterState(
        timestamp=_datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC),
        working_mode=_WM.MAINS,
        grid_voltage=230.5,
        grid_frequency=50.0,
        grid_load_power=100,
        inverter_voltage=230.0,
        inverter_current=1.0,
        inverter_frequency=50.0,
        inverter_power=500,
        inverter_charging_power=0,
        output_voltage=230.0,
        output_current=2.0,
        output_frequency=50.0,
        output_power=460,
        output_apparent_power=500,
        battery_voltage=51.0,
        battery_power=300,
        pv_voltage=320.0,
        pv_current=2.5,
        pv_power=800,
        pv_charging_power=300,
        load_percentage=45,
        dcdc_temperature=35,
        inverter_temperature=40,
        pv_temperature=30,
        battery_percentage=78,
        power_flow_status=0,
        battery_average_current=1.5,
        inverter_charging_average_current=1.2,
        pv_charging_average_current=3.0,
    )


def test_probe_mode_prints_dev_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from smartess_local import cli as cli_module

    monkeypatch.setattr(cli_module, "Inverter", _FakeInverter)
    exit_code = asyncio.run(
        cli_module.main(["--inverter-ip", "h", "--local-ip", "b", "--probe"])
    )
    assert exit_code == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed == {"dev_code": 12345}


def test_one_shot_prints_state_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from smartess_local import cli as cli_module

    monkeypatch.setattr(cli_module, "Inverter", _FakeInverter)
    exit_code = asyncio.run(cli_module.main(["--inverter-ip", "h", "--local-ip", "b"]))
    assert exit_code == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["battery_percentage"] == 78
    assert parsed["pv_power"] == 800
    assert parsed["working_mode"] == "MAINS"
    assert parsed["timestamp"] == "2026-05-21T12:00:00+00:00"
    # Sanity: the snapshot was reconstructable from the JSON.
    assert set(asdict(_canned_state()).keys()) == set(parsed.keys())


def test_stream_prints_jsonlines_until_cancelled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from smartess_local import cli as cli_module

    call_count = {"n": 0}

    class _StreamingFakeInverter(_FakeInverter):
        async def read(self) -> InverterState:
            call_count["n"] += 1
            if call_count["n"] > 3:
                raise asyncio.CancelledError()
            return _canned_state()

    monkeypatch.setattr(cli_module, "Inverter", _StreamingFakeInverter)
    exit_code = asyncio.run(
        cli_module.main(
            ["--inverter-ip", "h", "--local-ip", "b", "--stream", "--interval", "0.001"]
        )
    )
    assert exit_code == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 3
    for line in lines:
        parsed = json.loads(line)
        assert parsed["working_mode"] == "MAINS"

@pytest.mark.parametrize("during_connect", [False, True])
@pytest.mark.parametrize("error", [TimeoutError(), asyncio.IncompleteReadError(b"abc", 80)])
def test_stream_reconnects_with_fresh_client(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    during_connect: bool,
    error: Exception,
) -> None:
    from smartess_local import cli

    clients = []
    closed = []
    reads = 0

    class RecoveringInverter(_FakeInverter):
        async def __aenter__(self):
            clients.append(self)
            if during_connect and len(clients) == 1:
                raise error
            return await super().__aenter__()

        async def __aexit__(self, *_: object) -> None:
            closed.append(self)

        async def read(self) -> InverterState:
            nonlocal reads
            reads += 1
            if not during_connect and len(clients) == 1:
                if reads == 1:
                    return _canned_state()
                raise error
            if reads <= 3:
                return _canned_state()
            raise asyncio.CancelledError()

    monkeypatch.setattr(cli, "_RETRY_DELAY", 0.001)
    monkeypatch.setattr(cli, "Inverter", RecoveringInverter)
    result = asyncio.run(
        cli.main(
            [
                "--inverter-ip",
                "h",
                "--local-ip",
                "b",
                "--stream",
                "--interval",
                "0.001",
            ]
        )
    )
    assert result == 0
    assert len(clients) == 2
    assert clients[0] is not clients[1]
    assert any(client is clients[-1] for client in closed)
    if not during_connect:
        assert closed[0] is clients[0]
    assert type(error).__name__ in caplog.text
    assert "reconnecting" in caplog.text
    assert len(capsys.readouterr().out.splitlines()) >= 2


def test_one_shot_timeout_has_nonempty_diagnostic(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from smartess_local import cli

    class TimeoutInverter(_FakeInverter):
        async def read(self) -> InverterState:
            raise TimeoutError()

    monkeypatch.setattr(cli, "Inverter", TimeoutInverter)
    assert asyncio.run(cli.main(["--inverter-ip", "h", "--local-ip", "b"])) == 1
    assert "TimeoutError" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_stream_cancellation_during_backoff_does_not_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from smartess_local import cli

    failed = asyncio.Event()
    attempts = 0

    class UnreachableInverter(_FakeInverter):
        async def __aenter__(self):
            nonlocal attempts
            attempts += 1
            failed.set()
            raise TimeoutError()

    monkeypatch.setattr(cli, "Inverter", UnreachableInverter)
    task = asyncio.create_task(
        cli.main(
            [
                "--inverter-ip",
                "h",
                "--local-ip",
                "b",
                "--stream",
            ]
        )
    )
    await asyncio.wait_for(failed.wait(), 1)
    task.cancel()
    assert await asyncio.wait_for(task, 1) == 0
    assert attempts == 1
