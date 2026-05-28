"""Declarative register table for the inverter's holding registers.

Defines the `RegisterDef` slot type and `REGISTERS_201_234`, the vendor-corrected
table for holding registers 201..234. `parse_payload` in `protocol.py` walks this
table positionally to turn the raw payload into named, scaled values.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RegisterDef:
    """One register slot in the sequential int16 payload.

    Attributes
    ----------
    address:
        Modbus register number, e.g. 201. Informational; the parser walks the
        payload by list position, not by address.
    name:
        Output key in the parsed dict. `None` means a reserved slot - bytes are
        consumed but the value is dropped.
    scale:
        Divisor applied after int16 decoding. E.g. 10 for voltages/currents
        (raw 2305 -> 230.5 V), 100 for frequencies, 1 for raw counts/percent.
    unit:
        Free-form unit string (V, A, Hz, W, VA, %, degC). Informational.
    signed:
        True for int16, False for uint16. Affects sign extension at decode time.
    """

    address: int
    name: str | None
    scale: int
    unit: str | None
    signed: bool


def _reg(
    address: int,
    name: str | None = None,
    *,
    scale: int = 1,
    unit: str | None = None,
    signed: bool = True,
) -> RegisterDef:
    """Concise builder for the register table. Most slots are signed int16."""
    return RegisterDef(address=address, name=name, scale=scale, unit=unit, signed=signed)


# Vendor reserved slots are represented as nameless entries with default flags.
# The few non-default conventions are: `signed=False` for the enum/bitmap/percent
# registers, `scale=10` for voltages/currents, `scale=100` for frequencies.
REGISTERS_201_234: tuple[RegisterDef, ...] = (
    _reg(201, "working_mode", signed=False),
    _reg(202, "grid_voltage", scale=10, unit="V"),
    _reg(203, "grid_frequency", scale=100, unit="Hz"),
    _reg(204, "grid_load_power", unit="W"),
    _reg(205, "inverter_voltage", scale=10, unit="V"),
    _reg(206, "inverter_current", scale=10, unit="A"),
    _reg(207, "inverter_frequency", scale=100, unit="Hz"),
    _reg(208, "inverter_power", unit="W"),
    _reg(209, "inverter_charging_power", unit="W"),
    _reg(210, "output_voltage", scale=10, unit="V"),
    _reg(211, "output_current", scale=10, unit="A"),
    _reg(212, "output_frequency", scale=100, unit="Hz"),
    _reg(213, "output_power", unit="W"),
    _reg(214, "output_apparent_power", unit="VA"),
    _reg(215, "battery_voltage", scale=10, unit="V"),
    _reg(216),  # vendor reserved
    _reg(217, "battery_power", unit="W"),
    _reg(218),  # vendor reserved (implicit gap)
    _reg(219, "pv_voltage", scale=10, unit="V"),
    _reg(220, "pv_current", scale=10, unit="A"),
    _reg(221),  # vendor reserved
    _reg(222),  # vendor reserved
    _reg(223, "pv_power", unit="W"),
    _reg(224, "pv_charging_power", unit="W"),
    _reg(225, "load_percentage", unit="%"),
    _reg(226, "dcdc_temperature", unit="C"),
    _reg(227, "inverter_temperature", unit="C"),
    _reg(228, "pv_temperature", unit="C"),
    # Vendor says UInt; range is 0..100 % so it does not matter on the wire,
    # but type honesty matters.
    _reg(229, "battery_percentage", unit="%", signed=False),
    _reg(230),  # vendor reserved
    # Raw uint16 bitmap; bit decoder is intentionally not part of MVP.
    _reg(231, "power_flow_status", signed=False),
    _reg(232, "battery_average_current", scale=10, unit="A"),
    _reg(233, "inverter_charging_average_current", scale=10, unit="A"),
    # 234: units are 0.1 A per vendor.
    _reg(234, "pv_charging_average_current", scale=10, unit="A"),
)
