"""Unit tests for smartess_local.protocol."""

from __future__ import annotations

import pytest

from smartess_local.protocol import (
    build_read_request,
    crc16,
    parse_payload,
    parse_response_frame,
)
from smartess_local.registers import RegisterDef


def test_crc16_canonical_check_value() -> None:
    # CRC-16/MODBUS canonical check: CRC of ASCII "123456789" is 0x4B37.
    # This nails the algorithm down regardless of any brittle byte vectors.
    assert crc16(b"123456789") == 0x4B37


def test_crc16_read_holding_201_34() -> None:
    # Modbus PDU for read holding (DeviceId=01, Func=03, Reg=00C9=201, Count=0022=34).
    # CRC-16/MODBUS value is 0xED15 — written as 15 ED in the frame (low-byte first).
    # Matches the donor .NET algorithm byte-for-byte.
    data = bytes.fromhex("0103 00C9 0022".replace(" ", ""))
    assert crc16(data) == 0xED15


def test_crc16_empty_input_returns_init_value() -> None:
    # CRC starts at 0xFFFF; with no bytes consumed it must stay at init.
    assert crc16(b"") == 0xFFFF


def test_crc16_matches_vendor_read_example() -> None:
    # Vendor doc "寄存器读示例": request bytes are 01 03 00 CA 00 03 25 F5,
    # i.e. read 3 registers starting at 202 from slave 1. The trailing 25 F5
    # are CRC LO-first, so the CRC int is 0xF525.
    assert crc16(bytes.fromhex("010300CA0003")) == 0xF525


def test_crc16_matches_vendor_response_example() -> None:
    # Vendor doc "寄存器读示例": response bytes 01 03 06 08 FC 13 88 04 B0 F7 F3.
    # CRC is computed over everything before the trailing F7 F3 (LO-first),
    # i.e. CRC int = 0xF3F7. This also pins down the response layout that has
    # a byte-count byte (here 06H = 6 data bytes) right after the function code.
    assert crc16(bytes.fromhex("01030608FC138804B0")) == 0xF3F7


def test_build_read_request_matches_vendor_read_example_bytes() -> None:
    # If we strip the dongle's 8-byte wrapper, build_read_request must produce
    # the exact pure-Modbus PDU + CRC that the vendor doc prints in 寄存器读示例:
    # 01 03 00 CA 00 03 25 F5 (slave=1, read 3 regs from 202).
    frame = build_read_request(tid=1, dev_code=0xABCD, register=202, count=3)
    # bytes 8..15 in our 16-byte wrapped frame are the pure Modbus PDU + CRC
    # that the dongle will forward to the inverter.
    assert frame[8:] == bytes.fromhex("010300CA000325F5")


def test_build_read_request_block_201_34() -> None:
    # TID=1, DevCode=12345 (0x3039), Reg=201, Count=34.
    # Header layout: TID(BE) DevCode(BE) Size(BE)=000A FF 04 01 03 RegBE CountBE CRClo CRChi
    # CRC of [01 03 00 C9 00 22] is 0xED15 (see crc16 tests), serialised as 15 ED.
    expected_hex = "0001 3039 000A FF 04 01 03 00C9 0022 15ED".replace(" ", "")
    expected = bytes.fromhex(expected_hex)
    assert len(expected) == 16
    assert build_read_request(tid=1, dev_code=12345, register=201, count=34) == expected


def test_build_read_request_independent_tid_only_changes_first_two_bytes() -> None:
    # TID is a header field, not derived - caller controls it. Two distinct TIDs
    # must produce frames differing only in the first two bytes (CRC region
    # excludes the header, so the tail stays identical).
    f1 = build_read_request(tid=1, dev_code=12345, register=201, count=34)
    f2 = build_read_request(tid=2, dev_code=12345, register=201, count=34)
    assert f1[:2] == b"\x00\x01"
    assert f2[:2] == b"\x00\x02"
    assert f1[2:] == f2[2:]


def test_parse_payload_decodes_signed_and_scaled_int16_in_order() -> None:
    # Three consecutive registers: signed scale=10 (V), unsigned scale=1 (enum),
    # signed scale=100 (Hz). int16 BE.
    regs = [
        RegisterDef(address=205, name="inverter_voltage", scale=10, unit="V", signed=True),
        RegisterDef(address=201, name="working_mode", scale=1, unit=None, signed=False),
        RegisterDef(address=207, name="inverter_frequency", scale=100, unit="Hz", signed=True),
    ]
    # Raw int16 BE: 2305 -> 230.5; 2 -> 2; 5000 -> 50.0
    raw = bytes.fromhex("0901 0002 1388".replace(" ", ""))
    assert parse_payload(raw, regs) == {
        "inverter_voltage": 230.5,
        "working_mode": 2,
        "inverter_frequency": 50.0,
    }


def test_parse_payload_skips_reserved_slots() -> None:
    # Middle slot is reserved -> bytes consumed, key absent from result.
    regs = [
        RegisterDef(address=219, name="pv_voltage", scale=10, unit="V", signed=True),
        RegisterDef(address=221, name=None, scale=1, unit=None, signed=False),
        RegisterDef(address=223, name="pv_power", scale=1, unit="W", signed=True),
    ]
    # 2400 -> 240.0; reserved=0xBEEF (discarded); 1500 -> 1500
    raw = bytes.fromhex("0960 BEEF 05DC".replace(" ", ""))
    assert parse_payload(raw, regs) == {"pv_voltage": 240.0, "pv_power": 1500}


def test_parse_payload_decodes_negative_signed_values() -> None:
    # Power can be negative (export to grid). int16 BE 0xFFFE = -2.
    regs = [
        RegisterDef(address=204, name="grid_load_power", scale=1, unit="W", signed=True),
    ]
    assert parse_payload(bytes.fromhex("FFFE"), regs) == {"grid_load_power": -2}


def test_parse_payload_returns_int_when_scale_is_one() -> None:
    # Avoid spurious floats when no scaling is applied.
    # Vendor: 电池百分比 is UInt — match the real signedness in the fixture.
    regs = [
        RegisterDef(address=229, name="battery_percentage", scale=1, unit="%", signed=False),
    ]
    result = parse_payload(bytes.fromhex("0064"), regs)
    assert result == {"battery_percentage": 100}
    assert isinstance(result["battery_percentage"], int)


def test_parse_payload_rejects_buffer_length_mismatch() -> None:
    regs = [
        RegisterDef(address=201, name="working_mode", scale=1, unit=None, signed=False),
        RegisterDef(address=202, name="grid_voltage", scale=10, unit="V", signed=True),
    ]
    with pytest.raises(ValueError, match="expected 4 bytes"):
        parse_payload(b"\x00\x02", regs)


def _make_response_layout_a(*, tid: int, dev_code: int, data: bytes) -> bytes:
    # Donor-repo wrapper layout, response form: 10-byte header + N data bytes + CRC.
    # CRC is computed over slave_id..end-of-data (offsets 8 onward) and serialised LE.
    header = bytes.fromhex(f"{tid:04X}{dev_code:04X}004A") + bytes([0xFF, 0x04, 0x01, 0x03])
    crc = crc16(header[8:] + data).to_bytes(2, "little")
    return header + data + crc


def _make_response_layout_b(*, tid: int, dev_code: int, data: bytes) -> bytes:
    # Vendor pure-Modbus form: header + byte_count + data + CRC.
    header = bytes.fromhex(f"{tid:04X}{dev_code:04X}004B") + bytes([0xFF, 0x04, 0x01, 0x03])
    byte_count = bytes([len(data)])
    crc = crc16(header[8:] + byte_count + data).to_bytes(2, "little")
    return header + byte_count + data + crc


def test_parse_response_frame_layout_a_returns_payload_and_layout() -> None:
    data = b"\x00\x02" + b"\x09\x01" + b"\x00" * 64  # 68 bytes
    frame = _make_response_layout_a(tid=1, dev_code=0x3039, data=data)
    assert len(frame) == 80
    payload, layout = parse_response_frame(frame, expected_data_words=34)
    assert payload == data
    assert layout == "A"


def test_parse_response_frame_layout_b_strips_byte_count() -> None:
    data = b"\x00\x05" + b"\x00" * 66  # 68 bytes
    frame = _make_response_layout_b(tid=2, dev_code=0x3039, data=data)
    assert len(frame) == 81
    payload, layout = parse_response_frame(frame, expected_data_words=34)
    assert payload == data
    assert layout == "B"


def test_parse_response_frame_invalid_crc_raises_value_error() -> None:
    data = b"\x00" * 68
    frame = bytearray(_make_response_layout_a(tid=1, dev_code=0x3039, data=data))
    frame[20] ^= 0xFF  # bit-flip somewhere in payload
    with pytest.raises(ValueError, match="CRC mismatch"):
        parse_response_frame(bytes(frame), expected_data_words=34)


def test_parse_response_frame_rejects_unexpected_length() -> None:
    # 75 bytes: neither layout A (80) nor layout B (81) for 34 words.
    with pytest.raises(ValueError, match="frame length"):
        parse_response_frame(b"\x00" * 75, expected_data_words=34)
