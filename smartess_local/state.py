"""Typed inverter state and enums.

Pure-data layer. `inverter.py` converts the raw `dict[str, int | float]` from
`parse_payload` into an `InverterState` via `from_registers`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Any, Self, get_type_hints


class WorkingMode(IntEnum):
    """Operating mode at register 201, per vendor 工作模式 table."""

    POWER_ON = 0
    STANDBY = 1
    MAINS = 2
    OFF_GRID = 3
    BYPASS = 4
    CHARGING = 5
    FAULT = 6


@dataclass(frozen=True, slots=True)
class InverterState:
    """One snapshot of named readings from the inverter.

    Field set follows the vendor register map for block 201..234 with
    reserved slots dropped. Floats indicate scaled values (V, A, Hz); ints
    indicate raw counts (W, %, C, raw bitmap).
    """

    timestamp: datetime
    working_mode: WorkingMode
    grid_voltage: float
    grid_frequency: float
    grid_load_power: int
    inverter_voltage: float
    inverter_current: float
    inverter_frequency: float
    inverter_power: int
    inverter_charging_power: int
    output_voltage: float
    output_current: float
    output_frequency: float
    output_power: int
    output_apparent_power: int
    battery_voltage: float
    battery_power: int
    pv_voltage: float
    pv_current: float
    pv_power: int
    pv_charging_power: int
    load_percentage: int
    dcdc_temperature: int
    inverter_temperature: int
    pv_temperature: int
    battery_percentage: int
    power_flow_status: int
    battery_average_current: float
    inverter_charging_average_current: float
    pv_charging_average_current: float

    @classmethod
    def from_registers(
        cls,
        values: dict[str, int | float],
        *,
        timestamp: datetime,
    ) -> Self:
        """Build an InverterState from the dict returned by `parse_payload`.

        Each non-timestamp field is constructed by calling its annotated type
        on the corresponding raw value: `int`/`float` accept the union directly,
        and `WorkingMode(int_value)` enforces the vendor enum.
        """
        coerced: dict[str, Any] = {
            name: target_type(values[name])
            for name, target_type in _REGISTER_FIELD_TYPES.items()
        }
        return cls(timestamp=timestamp, **coerced)


_REGISTER_FIELD_TYPES: dict[str, type] = {
    name: target_type
    for name, target_type in get_type_hints(InverterState).items()
    if name != "timestamp"
}
