"""Unit tests for smartess_local.state."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from smartess_local.state import InverterState, WorkingMode


@pytest.mark.parametrize(
    "value, member",
    [
        (0, WorkingMode.POWER_ON),
        (1, WorkingMode.STANDBY),
        (2, WorkingMode.MAINS),
        (3, WorkingMode.OFF_GRID),
        (4, WorkingMode.BYPASS),
        (5, WorkingMode.CHARGING),
        (6, WorkingMode.FAULT),
    ],
)
def test_working_mode_values_match_vendor_spec(value: int, member: WorkingMode) -> None:
    # Vendor doc register 201 enumerates 0..6 exactly. IntEnum so the raw int
    # read off the wire can be compared/assigned directly.
    assert WorkingMode(value) is member
    assert int(member) == value


def test_working_mode_rejects_unknown_value() -> None:
    # 7+ is undefined per vendor; constructing an enum member must raise so
    # bad payloads fail loudly instead of silently producing a sentinel value.
    with pytest.raises(ValueError):
        WorkingMode(7)


def test_inverter_state_is_frozen_dataclass_with_expected_fields() -> None:
    # Construction with the full set of fields must succeed; frozen so callers
    # cannot mutate values after a read.
    state = InverterState(
        timestamp=datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC),
        working_mode=WorkingMode.MAINS,
        grid_voltage=230.5,
        grid_frequency=50.0,
        grid_load_power=1500,
        inverter_voltage=229.8,
        inverter_current=6.5,
        inverter_frequency=50.01,
        inverter_power=-200,
        inverter_charging_power=800,
        output_voltage=230.0,
        output_current=7.0,
        output_frequency=50.0,
        output_power=1610,
        output_apparent_power=1700,
        battery_voltage=53.2,
        battery_power=-250,
        pv_voltage=180.0,
        pv_current=3.5,
        pv_power=630,
        pv_charging_power=580,
        load_percentage=47,
        dcdc_temperature=38,
        inverter_temperature=42,
        pv_temperature=51,
        battery_percentage=78,
        power_flow_status=0x0455,
        battery_average_current=4.2,
        inverter_charging_average_current=3.8,
        pv_charging_average_current=3.5,
    )
    assert state.working_mode is WorkingMode.MAINS
    assert state.battery_percentage == 78
    assert state.pv_charging_average_current == 3.5
    with pytest.raises((AttributeError, TypeError)):
        # frozen=True raises FrozenInstanceError (subclass of AttributeError).
        state.battery_percentage = 0  # type: ignore[misc]


def test_from_registers_converts_dict_to_typed_state() -> None:
    # The dict shape here is exactly what parse_payload(REGISTERS_201_234, ...)
    # returns. from_registers must coerce working_mode int -> WorkingMode and
    # attach the supplied timestamp; every other field is a 1:1 copy.
    values: dict[str, int | float] = {
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
    ts = datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC)
    state = InverterState.from_registers(values, timestamp=ts)

    assert state.timestamp == ts
    assert state.working_mode is WorkingMode.MAINS
    assert state.grid_voltage == 230.5
    assert state.battery_percentage == 78
    assert state.power_flow_status == 0x0455
    assert state.pv_charging_average_current == 3.5


def test_from_registers_rejects_unknown_working_mode() -> None:
    # Reading garbage from the wire must fail loudly rather than land
    # an out-of-range WorkingMode into a frozen state.
    values: dict[str, int | float] = {
        "working_mode": 7,
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
    with pytest.raises(ValueError):
        InverterState.from_registers(
            values, timestamp=datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC)
        )


def test_from_registers_round_trips_via_parse_payload() -> None:
    # End-to-end: synthetic 68-byte payload -> parse_payload -> from_registers
    # -> InverterState. Ensures the parse_payload key set and InverterState
    # field set stay in lockstep - any drift between the register table and
    # the dataclass surfaces here as a TypeError or AssertionError.
    from smartess_local.protocol import parse_payload
    from smartess_local.registers import REGISTERS_201_234

    # Build a payload where every named slot has a distinct sentinel value
    # and reserved slots are arbitrary filler.
    raw_words = [
        2, 2305, 5000, 1500, 2298, 65, 5001, -200, 800, 2300, 70, 5000,
        1610, 1700, 532, 0xDEAD, -250, 0xDEAD, 1800, 35, 0xDEAD, 0xDEAD,
        630, 580, 47, 38, 42, 51, 78, 0xDEAD, 0x0455, 42, 38, 35,
    ]
    payload = b"".join(int(w).to_bytes(2, "big", signed=w < 0) for w in raw_words)

    parsed = parse_payload(payload, REGISTERS_201_234)
    ts = datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC)
    state = InverterState.from_registers(parsed, timestamp=ts)

    assert state.working_mode is WorkingMode.MAINS
    assert state.battery_percentage == 78
    assert state.pv_temperature == 51
    # scale=10 vendor fix in action.
    assert state.pv_charging_average_current == 3.5


def test_public_re_exports() -> None:
    # Public API: from smartess_local import Inverter, InverterError,
    # InverterState, WorkingMode.
    import smartess_local

    assert smartess_local.InverterState is InverterState
    assert smartess_local.WorkingMode is WorkingMode
