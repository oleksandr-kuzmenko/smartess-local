"""Unit tests for smartess_local.registers."""

from __future__ import annotations

import pytest

from smartess_local.protocol import parse_payload
from smartess_local.registers import REGISTERS_201_234


def test_register_table_has_exactly_34_slots() -> None:
    # Block 201..234 inclusive = 34 registers. parse_payload requires the
    # table length to match `count` from the read request.
    assert len(REGISTERS_201_234) == 34


def test_register_table_addresses_are_201_through_234_in_order() -> None:
    # Slots are consumed positionally; addresses are informational, but they
    # must still be sequential or the table is mis-aligned.
    expected = tuple(range(201, 235))
    actual = tuple(reg.address for reg in REGISTERS_201_234)
    assert actual == expected


def test_register_table_round_trip_against_golden_buffer() -> None:
    # 34 int16 BE values, one per register. Reserved slots (216, 218, 221, 222, 230)
    # get filler 0xDEAD that should NOT appear in the parsed dict.
    raw_words = {
        201: 2,       # working_mode = Mains (UInt)
        202: 2305,    # grid_voltage 230.5 V
        203: 5000,    # grid_frequency 50.00 Hz
        204: 1500,    # grid_load_power 1500 W
        205: 2298,    # inverter_voltage 229.8 V
        206: 65,      # inverter_current 6.5 A
        207: 5001,    # inverter_frequency 50.01 Hz
        208: -200,    # inverter_power -200 W (importing)
        209: 800,     # inverter_charging_power 800 W
        210: 2300,    # output_voltage 230.0 V
        211: 70,      # output_current 7.0 A
        212: 5000,    # output_frequency 50.00 Hz
        213: 1610,    # output_power 1610 W
        214: 1700,    # output_apparent_power 1700 VA
        215: 532,     # battery_voltage 53.2 V
        216: 0xDEAD,  # reserved - must not appear in result
        217: -250,    # battery_power -250 W (discharging)
        218: 0xDEAD,  # reserved
        219: 1800,    # pv_voltage 180.0 V
        220: 35,      # pv_current 3.5 A
        221: 0xDEAD,  # reserved
        222: 0xDEAD,  # reserved
        223: 630,     # pv_power 630 W
        224: 580,     # pv_charging_power 580 W
        225: 47,      # load_percentage 47 %
        226: 38,      # dcdc_temperature 38 C
        227: 42,      # inverter_temperature 42 C
        228: 51,      # pv_temperature 51 C
        229: 78,      # battery_percentage 78 %
        230: 0xDEAD,  # reserved
        231: 0x0455,  # power_flow_status raw uint16
        232: 42,      # battery_average_current 4.2 A
        233: 38,      # inverter_charging_average_current 3.8 A
        234: 35,      # pv_charging_average_current 3.5 A (scale=10 means 0.1A units)
    }
    payload = b"".join(
        int(raw_words[addr]).to_bytes(2, "big", signed=raw_words[addr] < 0)
        for addr in range(201, 235)
    )
    result = parse_payload(payload, REGISTERS_201_234)

    expected = {
        "working_mode": 2,
        "grid_voltage": 230.5,
        "grid_frequency": 50.0,
        "grid_load_power": 1500,
        "inverter_voltage": 229.8,
        "inverter_current": 6.5,
        "inverter_frequency": 50.01,
        "inverter_power": -200,
        "inverter_charging_power": 800,
        "output_voltage": 230.0,
        "output_current": 7.0,
        "output_frequency": 50.0,
        "output_power": 1610,
        "output_apparent_power": 1700,
        "battery_voltage": 53.2,
        "battery_power": -250,
        "pv_voltage": 180.0,
        "pv_current": 3.5,
        "pv_power": 630,
        "pv_charging_power": 580,
        "load_percentage": 47,
        "dcdc_temperature": 38,
        "inverter_temperature": 42,
        "pv_temperature": 51,
        "battery_percentage": 78,
        "power_flow_status": 0x0455,
        "battery_average_current": 4.2,
        "inverter_charging_average_current": 3.8,
        "pv_charging_average_current": 3.5,
    }
    assert result == expected
    # Reserved slots must not leak into the parsed dict.
    assert len(result) == 29


@pytest.mark.parametrize(
    "address, expected_name, expected_scale, expected_signed",
    [
        # 216: vendor says reserved.
        (216, None,                          1,  True),
        # 228: vendor names this PV temperature.
        (228, "pv_temperature",              1,  True),
        # 229: vendor says battery percentage is UInt.
        (229, "battery_percentage",          1,  False),
        # 231: vendor names this PowerFlowStatus (UInt bitmap).
        (231, "power_flow_status",           1,  False),
        # 234: vendor says units are 0.1 A (scale=10).
        (234, "pv_charging_average_current", 10, True),
    ],
)
def test_register_matches_vendor_correction(
    address: int,
    expected_name: str | None,
    expected_scale: int,
    expected_signed: bool,
) -> None:
    # These five rows are the vendor-doc corrections vs. the earlier
    # donor-repo-derived table. Pinning them with named tests makes any
    # regression to the earlier values fail with a self-explanatory diff.
    reg = next(r for r in REGISTERS_201_234 if r.address == address)
    assert reg.name == expected_name
    assert reg.scale == expected_scale
    assert reg.signed == expected_signed
