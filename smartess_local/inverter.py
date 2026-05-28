"""Async client for the Eybond/SmartESS reverse-tunnel inverter dongle.

Lifecycle:

    async with Inverter(inverter_ip=..., local_ip=...) as inv:
        state = await inv.read()             # one snapshot
        async for state in inv.stream():     # continuous
            ...

`__aenter__` does the UDP `set>server=...` handshake, then opens a TCP
listener and waits for the dongle to dial back. `read()` writes a request
frame and decodes the response (auto-detecting the byte_count layout).
See docs/architecture.md and docs/protocol.md for the byte-level details.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import TracebackType
from typing import Final, Self

from smartess_local.protocol import build_read_request, parse_payload, parse_response_frame
from smartess_local.registers import REGISTERS_201_234
from smartess_local.state import InverterState


class InverterError(Exception):
    """Raised on CRC mismatch, timeout, unknown WorkingMode, or disconnect.

    For diagnostics, callers may pass a hex-encoded frame as the second
    positional argument (available as ``err.args[1]``).
    """


_DEFAULT_LOGGER: Final = logging.getLogger("smartess_local.inverter")

_REGISTER_BLOCK_START: Final = 201
_REGISTER_BLOCK_COUNT: Final = 34
_RESPONSE_LAYOUT_A_LEN: Final = 10 + _REGISTER_BLOCK_COUNT * 2 + 2  # 80

# UDP bootstrap reply has the form "rsp>server=<int>;" with an optional CRLF
# tail on real dongles. Match the integer after the '=' tolerantly.
_DEV_CODE_RE: Final = re.compile(rb"=\s*(\d+)")


class _UdpReplyCollector(asyncio.DatagramProtocol):
    """Datagram protocol that captures the first reply into a future."""

    def __init__(self) -> None:
        self.reply: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if not self.reply.done():
            self.reply.set_result(data)

    def error_received(self, exc: Exception) -> None:
        if not self.reply.done():
            self.reply.set_exception(exc)


@dataclass(slots=True)
class _Connection:
    """Live reverse-tunnel state set by the dongle's TCP dial-back."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter


@dataclass(kw_only=True, slots=True)
class Inverter:
    """Public async client. See module docstring for lifecycle."""

    inverter_ip: str
    local_ip: str
    local_port: int = 8899
    inverter_udp_port: int = 58899
    timeout: float = 5.0
    slave_id: int = 1
    logger: logging.Logger = _DEFAULT_LOGGER

    dev_code: int | None = field(default=None, init=False)
    _server: asyncio.Server | None = field(default=None, init=False)
    _conn: _Connection | None = field(default=None, init=False)
    _connected: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _closing: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _tid: int = field(default=0, init=False)
    _layout_logged: bool = field(default=False, init=False)

    async def __aenter__(self) -> Self:
        await self._udp_bootstrap()
        self._server = await asyncio.start_server(
            self._on_dongle_connect, self.local_ip, self.local_port
        )
        self.logger.info(
            "TCP listener active on %s:%d, awaiting dongle dial-back (dev_code=%s)",
            self.local_ip,
            self.local_port,
            self.dev_code,
        )
        try:
            await asyncio.wait_for(self._connected.wait(), self.timeout)
        except TimeoutError as exc:
            await self._close_server()
            raise InverterError(
                f"dongle did not dial back to {self.local_ip}:{self.local_port} "
                f"within {self.timeout}s. If tcpdump shows a completed TCP "
                f"handshake but no application data, the OS accepted the "
                f"connection at kernel level but the Python process never "
                f"received it - on macOS this is usually Local Network "
                f"privacy (System Settings -> Privacy & Security -> Local "
                f"Network) or the application firewall blocking inbound TCP."
            ) from exc
        return self

    async def probe(self) -> int:
        """Run only the UDP `set>server` handshake and return the dev_code.

        Unlike ``__aenter__``, no TCP listener is started and no dial-back is
        awaited — handy for verifying that the dongle is reachable on UDP and
        that the bind address was announced correctly, before committing to
        the full reverse-tunnel lifecycle.
        """
        await self._udp_bootstrap()
        assert self.dev_code is not None
        return self.dev_code

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._closing.set()
        if self._conn is not None:
            self._conn.writer.close()
            with suppress(Exception):
                await self._conn.writer.wait_closed()
            self._conn = None
        await self._close_server()

    async def read(self) -> InverterState:
        """Send one read-holding request and decode the response into a state."""
        conn = self._require_conn()
        if self.dev_code is None:
            raise InverterError("read() called before UDP bootstrap set dev_code")
        self._tid = self._tid % 0xFFFF + 1
        request = build_read_request(
            tid=self._tid,
            dev_code=self.dev_code,
            register=_REGISTER_BLOCK_START,
            count=_REGISTER_BLOCK_COUNT,
            slave_id=self.slave_id,
        )
        conn.writer.write(request)
        await conn.writer.drain()
        frame, payload, layout = await self._read_response(conn)
        values = parse_payload(payload, REGISTERS_201_234)
        self.logger.debug("payload hex=%s", payload.hex())
        self.logger.debug("decoded register values: %s", values)
        try:
            state = InverterState.from_registers(values, timestamp=datetime.now(UTC))
        except ValueError as exc:
            # e.g. register 201 carried a WorkingMode the vendor enum doesn't define.
            raise InverterError(str(exc), frame.hex()) from exc
        if not self._layout_logged:
            self.logger.info("first read OK, layout=%s, frame=%s", layout, frame.hex())
            self._layout_logged = True
        return state

    async def stream(
        self,
        *,
        interval: float = 10.0,
    ) -> AsyncIterator[InverterState]:
        """Yield a fresh InverterState every `interval` seconds until cancelled."""
        while True:
            yield await self.read()
            await asyncio.sleep(interval)

    async def _udp_bootstrap(self) -> None:
        """Send `set>server=...`, parse `rsp>server=N;`, remember N as dev_code."""
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            _UdpReplyCollector,
            remote_addr=(self.inverter_ip, self.inverter_udp_port),
        )
        try:
            request = f"set>server={self.local_ip}:{self.local_port};".encode("ascii")
            transport.sendto(request)
            reply = await asyncio.wait_for(protocol.reply, self.timeout)
        finally:
            transport.close()
        self.dev_code = self._parse_dev_code(reply)

    @staticmethod
    def _parse_dev_code(reply: bytes) -> int:
        """Extract the integer dev_code from a `rsp>server=N;` UDP reply.

        Tolerates surrounding whitespace and CRLF trailers that real dongles
        emit after the semicolon.
        """
        match = _DEV_CODE_RE.search(reply)
        if match is None:
            raise InverterError(f"malformed UDP reply: {reply!r}")
        return int(match.group(1))

    async def _on_dongle_connect(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """`asyncio.start_server` callback: record the connection, then wait.

        We block here on ``_closing`` so asyncio keeps the connection open until
        ``__aexit__`` signals shutdown. Returning early would let asyncio close
        the socket out from under ``read()``.
        """
        peer = writer.get_extra_info("peername")
        self.logger.info("dongle dial-back accepted from %s", peer)
        self._conn = _Connection(reader=reader, writer=writer)
        self._connected.set()
        await self._closing.wait()

    async def _read_response(self, conn: _Connection) -> tuple[bytes, bytes, str]:
        """Read one response frame, auto-detecting layout A vs B.

        Returns ``(full_frame, payload, layout_name)``. Tries layout A first
        (80 bytes for the 34-register block); on CRC failure, reads one more
        byte and tries layout B. Surfaces ``InverterError`` if neither works.
        """
        frame = await asyncio.wait_for(
            conn.reader.readexactly(_RESPONSE_LAYOUT_A_LEN), self.timeout
        )
        try:
            payload, layout = parse_response_frame(
                frame, expected_data_words=_REGISTER_BLOCK_COUNT
            )
            return frame, payload, layout
        except ValueError:
            pass
        try:
            extra = await asyncio.wait_for(conn.reader.readexactly(1), self.timeout)
        except (TimeoutError, asyncio.IncompleteReadError) as exc:
            raise InverterError(
                "CRC mismatch (layout A); no extra byte for layout B retry",
                frame.hex(),
            ) from exc
        frame = frame + extra
        try:
            payload, layout = parse_response_frame(
                frame, expected_data_words=_REGISTER_BLOCK_COUNT
            )
        except ValueError as exc:
            raise InverterError("CRC mismatch on both layouts", frame.hex()) from exc
        return frame, payload, layout

    def _require_conn(self) -> _Connection:
        if self._conn is None:
            raise InverterError("read() called before __aenter__ established connection")
        return self._conn

    async def _close_server(self) -> None:
        if self._server is not None:
            self._server.close()
            with suppress(Exception):
                await self._server.wait_closed()
            self._server = None
