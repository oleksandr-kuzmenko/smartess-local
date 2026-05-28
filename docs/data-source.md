# Data sources

Two cross-checked sources back every protocol fact.

**Vendor doc (authoritative):**
[`vendor/modbus-protocol-v11.html`](vendor/modbus-protocol-v11.html) — the
official Eybond/SmartESS dongle protocol (v11, Chinese; the byte tables and the
worked example are language-independent). Final word on the handshake, the
10-byte wrapper header, the Modbus PDU + CRC wrapping, and the holding-register
table. On a newer vendor version, replace the file and bump the `v11` suffix so
git diff shows the drift.

**Reference .NET implementation:**
[sabatex/NetDaemonApps.InverterAnenji-4kw-7.2kw](https://github.com/sabatex/NetDaemonApps.InverterAnenji-4kw-7.2kw)
— a NetDaemon integration for the same dongle family, used as an executable spec
to confirm the CRC algorithm and the reverse-tunnel handshake. No code ported.

## Vendor-corrected registers

Five registers differ from a naive reading of the .NET donor repo. The vendor
HTML wins; these are pinned by
`tests/test_registers.py::test_register_matches_vendor_correction`:

| Register | Field | Donor guess | Vendor / correct |
|---------:|-------|-------------|------------------|
| 216 | (unnamed) | `battery_current` | reserved |
| 228 | `pv_temperature` | reserved | int16, °C |
| 229 | `battery_percentage` | signed | UInt (0..100) |
| 231 | `power_flow_status` | reserved | UInt bitmap |
| 234 | `pv_charging_average_current` | scale=1 | scale=10 (0.1 A) |

Found a new discrepancy? Add a pinning test and update `registers.py`.
