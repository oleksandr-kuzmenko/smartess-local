"""Unit tests for smartess_local.inverter."""

from __future__ import annotations

import asyncio
import logging

import pytest

from smartess_local.inverter import Inverter, InverterError
from tests.conftest import FakeDongle, fake_dongle, find_free_port


def test_inverter_init_stores_args() -> None:
    inv = Inverter(inverter_ip="1.2.3.4", local_ip="5.6.7.8")
    assert inv.inverter_ip == "1.2.3.4"
    assert inv.local_ip == "5.6.7.8"
    assert inv.local_port == 8899
    assert inv.inverter_udp_port == 58899
    assert inv.timeout == 5.0
    assert inv.slave_id == 1
    assert inv.dev_code is None


def test_inverter_init_accepts_custom_logger() -> None:
    logger = logging.getLogger("custom.smartess")
    inv = Inverter(inverter_ip="h", local_ip="b", logger=logger)
    assert inv.logger is logger


@pytest.mark.parametrize(
    "reply, expected",
    [
        (b"rsp>server=12345;", 12345),
        (b"rsp>server=1;\r\n", 1),
        (b"rsp>server=42;\n", 42),
        (b"  rsp>server= 99 ;\r\n", 99),
    ],
)
def test_parse_dev_code_accepts_real_dongle_trailers(reply: bytes, expected: int) -> None:
    # Real Eybond/SmartESS dongles terminate the UDP reply with CRLF after the
    # semicolon; the previous rstrip(";") parser tripped on that and raised
    # InverterError. The parser must accept whitespace/CRLF around the integer.
    assert Inverter._parse_dev_code(reply) == expected


def test_parse_dev_code_raises_on_garbage() -> None:
    with pytest.raises(InverterError):
        Inverter._parse_dev_code(b"hello world")


def test_inverter_error_is_exception_subclass() -> None:
    assert issubclass(InverterError, Exception)
    err = InverterError("boom", "deadbeef")
    assert err.args == ("boom", "deadbeef")


@pytest.mark.asyncio
async def test_probe_returns_dev_code_without_starting_tcp_server() -> None:
    # `probe()` must complete the UDP handshake on its own — no TCP listener,
    # no dial-back wait. Useful when the dongle is reachable by UDP but the
    # local-ip is on a network the dongle cannot route back to.
    async with fake_dongle(dev_code=12345) as fd:
        inv = Inverter(
            inverter_ip="127.0.0.1",
            local_ip="127.0.0.1",
            inverter_udp_port=fd.udp_port,
            timeout=2.0,
        )
        assert await inv.probe() == 12345
        assert inv.dev_code == 12345
        assert inv._server is None
        assert inv._conn is None


@pytest.mark.asyncio
async def test_aenter_full_lifecycle_completes_when_dongle_dials_back() -> None:
    async with fake_dongle(dev_code=12345) as fd:
        local_port = find_free_port()
        inv = Inverter(
            inverter_ip="127.0.0.1",
            local_ip="127.0.0.1",
            local_port=local_port,
            inverter_udp_port=fd.udp_port,
            timeout=2.0,
        )
        async with inv:
            assert inv.dev_code == 12345
            assert inv._conn is not None
        # After exit, server is closed and the connection is released.
        assert inv._server is None
        assert inv._conn is None


@pytest.mark.asyncio
async def test_aexit_idempotent_when_no_dongle_connects() -> None:
    # If no dongle dials in within timeout, __aenter__ raises; __aexit__ runs anyway.
    local_port = find_free_port()
    inv = Inverter(
        inverter_ip="127.0.0.1",
        local_ip="127.0.0.1",
        local_port=local_port,
        inverter_udp_port=find_free_port(),  # no dongle listens here
        timeout=0.2,
    )
    with pytest.raises((InverterError, asyncio.TimeoutError, ConnectionError, OSError)):
        async with inv:
            pass


def _canned_register_payload() -> bytes:
    # 34 registers, big-endian int16. Hand-picked values that pin every
    # InverterState field to something realistic.
    values = [
        2,      # 201 working_mode = MAINS
        2305,   # 202 grid_voltage = 230.5 V
        5000,   # 203 grid_frequency = 50.0 Hz
        100,    # 204 grid_load_power = 100 W
        2300,   # 205 inverter_voltage = 230.0 V
        10,     # 206 inverter_current = 1.0 A
        5000,   # 207 inverter_frequency = 50.0 Hz
        500,    # 208 inverter_power = 500 W
        0,      # 209 inverter_charging_power = 0 W
        2300,   # 210 output_voltage = 230.0 V
        20,     # 211 output_current = 2.0 A
        5000,   # 212 output_frequency = 50.0 Hz
        460,    # 213 output_power = 460 W
        500,    # 214 output_apparent_power = 500 VA
        510,    # 215 battery_voltage = 51.0 V
        0,      # 216 reserved
        300,    # 217 battery_power = 300 W
        0,      # 218 reserved
        3200,   # 219 pv_voltage = 320.0 V
        25,     # 220 pv_current = 2.5 A
        0, 0,   # 221, 222 reserved
        800,    # 223 pv_power = 800 W
        300,    # 224 pv_charging_power = 300 W
        45,     # 225 load_percentage = 45 %
        35,     # 226 dcdc_temperature = 35 C
        40,     # 227 inverter_temperature = 40 C
        30,     # 228 pv_temperature = 30 C
        78,     # 229 battery_percentage = 78 %
        0,      # 230 reserved
        0,      # 231 power_flow_status (raw bitmap, 0 for test)
        15,     # 232 battery_average_current = 1.5 A
        12,     # 233 inverter_charging_average_current = 1.2 A
        30,     # 234 pv_charging_average_current = 3.0 A
    ]
    return b"".join(v.to_bytes(2, "big", signed=(v < 0)) for v in values)


@pytest.mark.asyncio
async def test_read_returns_inverter_state_layout_a() -> None:
    async with fake_dongle(dev_code=12345) as fd:
        local_port = find_free_port()
        inv = Inverter(
            inverter_ip="127.0.0.1",
            local_ip="127.0.0.1",
            local_port=local_port,
            inverter_udp_port=fd.udp_port,
            timeout=2.0,
        )
        async with inv:
            data = _canned_register_payload()
            response_task = asyncio.create_task(
                _serve_one_response(fd, layout="A", dev_code=12345, data=data)
            )
            state = await inv.read()
            await response_task
        assert state.working_mode.name == "MAINS"
        assert state.battery_percentage == 78
        assert state.grid_voltage == 230.5
        assert state.pv_power == 800


@pytest.mark.asyncio
async def test_read_layout_b_with_byte_count_returns_same_state() -> None:
    async with fake_dongle(dev_code=12345) as fd:
        local_port = find_free_port()
        inv = Inverter(
            inverter_ip="127.0.0.1",
            local_ip="127.0.0.1",
            local_port=local_port,
            inverter_udp_port=fd.udp_port,
            timeout=2.0,
        )
        async with inv:
            data = _canned_register_payload()
            response_task = asyncio.create_task(
                _serve_one_response(fd, layout="B", dev_code=12345, data=data)
            )
            state = await inv.read()
            await response_task
        assert state.battery_percentage == 78
        assert state.pv_power == 800


@pytest.mark.asyncio
async def test_read_crc_mismatch_raises_inverter_error() -> None:
    async with fake_dongle(dev_code=12345) as fd:
        local_port = find_free_port()
        inv = Inverter(
            inverter_ip="127.0.0.1",
            local_ip="127.0.0.1",
            local_port=local_port,
            inverter_udp_port=fd.udp_port,
            timeout=2.0,
        )
        async with inv:
            data = _canned_register_payload()

            async def serve_corrupted() -> None:
                await fd.expect_read_request()
                frame = bytearray(fd.make_layout_a(tid=1, dev_code=12345, data=data))
                frame[20] ^= 0xFF
                await fd.respond(bytes(frame))

            response_task = asyncio.create_task(serve_corrupted())
            with pytest.raises(InverterError, match="CRC mismatch"):
                await inv.read()
            await response_task


@pytest.mark.asyncio
async def test_read_wraps_unknown_working_mode_in_inverter_error() -> None:
    # Register 201 carrying a value the vendor enum doesn't define must surface
    # as InverterError (the documented error type), not a bare ValueError that
    # the CLI's `except (InverterError, OSError)` would miss.
    async with fake_dongle(dev_code=12345) as fd:
        local_port = find_free_port()
        inv = Inverter(
            inverter_ip="127.0.0.1",
            local_ip="127.0.0.1",
            local_port=local_port,
            inverter_udp_port=fd.udp_port,
            timeout=2.0,
        )
        async with inv:
            data = (7).to_bytes(2, "big") + b"\x00" * 66  # working_mode=7 is undefined
            response_task = asyncio.create_task(
                _serve_one_response(fd, layout="A", dev_code=12345, data=data)
            )
            with pytest.raises(InverterError):
                await inv.read()
            await response_task


@pytest.mark.asyncio
async def test_read_logs_layout_on_first_call_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with fake_dongle(dev_code=12345) as fd:
        local_port = find_free_port()
        inv = Inverter(
            inverter_ip="127.0.0.1",
            local_ip="127.0.0.1",
            local_port=local_port,
            inverter_udp_port=fd.udp_port,
            timeout=2.0,
        )
        async with inv:
            data = _canned_register_payload()

            async def serve_two() -> None:
                for tid in (1, 2):
                    await fd.expect_read_request()
                    await fd.respond(fd.make_layout_a(tid=tid, dev_code=12345, data=data))

            response_task = asyncio.create_task(serve_two())
            with caplog.at_level(logging.INFO, logger="smartess_local.inverter"):
                await inv.read()
                await inv.read()
            await response_task

        layout_records = [r for r in caplog.records if "first read OK" in r.message]
        assert len(layout_records) == 1
        assert "layout=A" in layout_records[0].message


@pytest.mark.asyncio
async def test_stream_yields_three_then_cancelled() -> None:
    async with fake_dongle(dev_code=12345) as fd:
        local_port = find_free_port()
        inv = Inverter(
            inverter_ip="127.0.0.1",
            local_ip="127.0.0.1",
            local_port=local_port,
            inverter_udp_port=fd.udp_port,
            timeout=2.0,
        )
        async with inv:
            data = _canned_register_payload()

            async def serve_n(n: int) -> None:
                for tid in range(1, n + 1):
                    await fd.expect_read_request()
                    await fd.respond(fd.make_layout_a(tid=tid, dev_code=12345, data=data))

            response_task = asyncio.create_task(serve_n(3))
            seen = 0
            async for _state in inv.stream(interval=0.001):
                seen += 1
                if seen >= 3:
                    break
            await response_task
        assert seen == 3


async def _serve_one_response(
    fd: FakeDongle,
    *,
    layout: str,
    dev_code: int,
    data: bytes,
) -> None:
    assert layout in {"A", "B"}
    await fd.expect_read_request()
    if layout == "A":
        frame = fd.make_layout_a(tid=1, dev_code=dev_code, data=data)
    else:
        frame = fd.make_layout_b(tid=1, dev_code=dev_code, data=data)
    await fd.respond(frame)
