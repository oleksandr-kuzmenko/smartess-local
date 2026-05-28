"""Wire-format helpers for the Eybond/SmartESS Solarman-like Modbus protocol.

Pure functions - no I/O. Tested by tests/test_protocol.py against vectors
from the vendor doc (docs/vendor/modbus-protocol-v11.html) and from manual
CRC computations. See docs/protocol.md for the byte-level reference.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

from smartess_local.registers import RegisterDef


def crc16(data: bytes) -> int:
    """Modbus RTU CRC16 (poly 0xA001, init 0xFFFF). Returns CRC as int.

    Callers must serialise the result low-byte-first when writing it
    into a frame.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


_READ_SIZE_FIELD = 0x000A
_DEV_ADR = 0xFF
_FUNC_CODE_WRAPPER = 0x04
_MODBUS_READ_HOLDING = 0x03


def build_read_request(
    *,
    tid: int,
    dev_code: int,
    register: int,
    count: int,
    slave_id: int = 1,
) -> bytes:
    """Build a 16-byte read-holding request frame.

    CRC is computed over the Modbus PDU bytes [slave_id, function, register_hi,
    register_lo, count_hi, count_lo] and serialised low-byte-first.
    See docs/protocol.md for the full byte layout.
    """
    pdu = struct.pack(
        ">BBHH",
        slave_id,
        _MODBUS_READ_HOLDING,
        register,
        count,
    )
    crc = crc16(pdu)
    header = struct.pack(
        ">HHHBB",
        tid,
        dev_code,
        _READ_SIZE_FIELD,
        _DEV_ADR,
        _FUNC_CODE_WRAPPER,
    )
    crc_bytes = struct.pack("<H", crc)
    return header + pdu + crc_bytes


_HEADER_SIZE = 10
_CRC_SIZE = 2


def parse_payload(
    data: bytes,
    registers: Sequence[RegisterDef],
) -> dict[str, int | float]:
    """Decode sequential int16 BE values into a name -> scaled-value dict.

    Each `RegisterDef` consumes 2 bytes from `data` in order. Slots whose
    `name` is None are consumed but omitted from the result. When `scale == 1`
    the value is returned as `int`; otherwise as `float` (raw / scale).
    """
    expected_len = len(registers) * 2
    if len(data) < expected_len:
        raise ValueError(
            f"payload buffer too short: expected {expected_len} bytes, got {len(data)}"
        )
    result: dict[str, int | float] = {}
    for offset, reg in zip(range(0, expected_len, 2), registers, strict=True):
        if reg.name is None:
            continue
        raw = int.from_bytes(data[offset : offset + 2], "big", signed=reg.signed)
        result[reg.name] = raw if reg.scale == 1 else raw / reg.scale
    return result


# How many bytes sit between the 10-byte header and the register data:
# layout A (donor-repo form) has none; layout B (vendor pure-Modbus) has a
# single byte_count byte. See docs/protocol.md.
_BYTE_COUNT_SIZE: dict[str, int] = {"A": 0, "B": 1}


def parse_response_frame(
    frame: bytes,
    *,
    expected_data_words: int,
) -> tuple[bytes, str]:
    """Validate CRC and return (payload, layout_name), auto-detecting the layout.

    CRC is computed over offsets [8 .. end-of-data] (so the byte_count byte in
    layout B is included) and serialised low-byte first. Raises ValueError if the
    frame length matches no layout, or matches one but the CRC is wrong. The caller
    (Inverter.read) handles "len matches A but CRC fails -> read one more byte,
    try B" by retrying.
    """
    data_bytes = expected_data_words * 2
    for name, byte_count_size in _BYTE_COUNT_SIZE.items():
        if len(frame) != _HEADER_SIZE + byte_count_size + data_bytes + _CRC_SIZE:
            continue
        payload_start = _HEADER_SIZE + byte_count_size
        crc_expected = int.from_bytes(frame[-2:], "little")
        if crc16(frame[8 : payload_start + data_bytes]) != crc_expected:
            raise ValueError(f"CRC mismatch (layout {name})")
        return frame[payload_start : payload_start + data_bytes], name
    valid_lengths = {
        _HEADER_SIZE + bcs + data_bytes + _CRC_SIZE for bcs in _BYTE_COUNT_SIZE.values()
    }
    raise ValueError(f"frame length {len(frame)} not in expected {valid_lengths}")
