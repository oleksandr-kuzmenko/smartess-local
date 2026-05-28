"""Shared test fixtures for smartess-local."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field

from smartess_local.protocol import crc16


def find_free_port() -> int:
    """Return an OS-assigned free TCP port on 127.0.0.1, then release it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class FakeDongle:
    """Loopback stand-in for a real Eybond/SmartESS dongle.

    Replies to one UDP `set>server=IP:PORT;` datagram with `rsp>server=N;`,
    then dials the parsed IP:PORT via TCP (reverse-tunnel emulation).
    Test code drives the TCP side via `expect_read_request` / `respond`.
    """

    udp_port: int
    dev_code: int = 12345
    _tcp_reader: asyncio.StreamReader | None = field(default=None, init=False)
    _tcp_writer: asyncio.StreamWriter | None = field(default=None, init=False)
    _requests: asyncio.Queue[bytes] = field(default_factory=asyncio.Queue, init=False)
    _tcp_ready: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    async def expect_read_request(self, *, timeout: float = 2.0) -> bytes:
        await asyncio.wait_for(self._tcp_ready.wait(), timeout)
        return await asyncio.wait_for(self._requests.get(), timeout)

    async def respond(self, frame: bytes) -> None:
        await asyncio.wait_for(self._tcp_ready.wait(), 2.0)
        assert self._tcp_writer is not None
        self._tcp_writer.write(frame)
        await self._tcp_writer.drain()

    @staticmethod
    def make_layout_a(*, tid: int, dev_code: int, data: bytes) -> bytes:
        header = bytes.fromhex(f"{tid:04X}{dev_code:04X}004A") + bytes(
            [0xFF, 0x04, 0x01, 0x03]
        )
        crc = crc16(header[8:] + data).to_bytes(2, "little")
        return header + data + crc

    @staticmethod
    def make_layout_b(*, tid: int, dev_code: int, data: bytes) -> bytes:
        header = bytes.fromhex(f"{tid:04X}{dev_code:04X}004B") + bytes(
            [0xFF, 0x04, 0x01, 0x03]
        )
        byte_count = bytes([len(data)])
        crc = crc16(header[8:] + byte_count + data).to_bytes(2, "little")
        return header + byte_count + data + crc


@asynccontextmanager
async def fake_dongle(*, dev_code: int = 12345) -> AsyncIterator[FakeDongle]:
    """Loopback dongle: UDP reply + TCP dial-back. Test code drives the TCP side."""
    loop = asyncio.get_running_loop()
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.bind(("127.0.0.1", 0))
    udp_sock.setblocking(False)
    fd = FakeDongle(udp_port=udp_sock.getsockname()[1], dev_code=dev_code)

    async def udp_handler() -> None:
        data, addr = await loop.sock_recvfrom(udp_sock, 256)
        reply = f"rsp>server={dev_code};".encode("ascii")
        await loop.sock_sendto(udp_sock, reply, addr)
        text = data.decode("ascii")
        host_port = text.split("=", 1)[1].rstrip(";")
        host_str, port_str = host_port.rsplit(":", 1)
        # The Inverter starts its TCP listener AFTER receiving this UDP reply,
        # so the first open_connection often races and gets ConnectionRefused.
        reader: asyncio.StreamReader | None = None
        writer: asyncio.StreamWriter | None = None
        for _ in range(50):
            try:
                reader, writer = await asyncio.open_connection(host_str, int(port_str))
                break
            except (ConnectionRefusedError, OSError):
                await asyncio.sleep(0.02)
        if reader is None or writer is None:
            return
        fd._tcp_reader = reader
        fd._tcp_writer = writer
        fd._tcp_ready.set()
        try:
            while True:
                req = await reader.readexactly(16)
                await fd._requests.put(req)
        except asyncio.IncompleteReadError:
            return

    handler_task = asyncio.create_task(udp_handler())
    try:
        yield fd
    finally:
        handler_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await handler_task
        if fd._tcp_writer is not None:
            fd._tcp_writer.close()
            with suppress(Exception):
                await fd._tcp_writer.wait_closed()
        udp_sock.close()
