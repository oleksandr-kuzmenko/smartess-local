# Wire-format reference

This document describes the bytes that go on the wire between the
client and an Eybond/SmartESS dongle on the LAN. For the authoritative
vendor description, see [`vendor/modbus-protocol-v11.html`](vendor/modbus-protocol-v11.html).

## Handshake (UDP)

The dongle listens on UDP port `58899` for short ASCII commands. The
client sends:

```
set>server=<local_ip>:<local_port>;
```

The dongle replies with:

```
rsp>server=<dev_code>;
```

`<dev_code>` is a numeric device identifier the dongle expects to see
echoed back in every TCP request frame. After replying, the dongle
opens a TCP connection from itself to `<local_ip>:<local_port>` —
the client is the TCP *server*. All Modbus traffic flows over that
single connection until either side closes it.

## Request frame (16 bytes)

```
| offset | bytes | field      | value / notes               |
|--------|-------|------------|-----------------------------|
|   0    |   2   | TID        | big-endian, client-chosen   |
|   2    |   2   | DevCode    | big-endian, from rsp>server |
|   4    |   2   | Size       | 0x000A (constant)           |
|   6    |   1   | DevAdr     | 0xFF (constant)             |
|   7    |   1   | FuncCode   | 0x04 (wrapper, constant)    |
|   8    |   1   | SlaveID    | 0x01 (configurable)         |
|   9    |   1   | Function   | 0x03 read holding           |
|  10    |   2   | Register   | big-endian (e.g. 0x00C9=201)|
|  12    |   2   | Count      | big-endian (e.g. 0x0022=34) |
|  14    |   2   | CRC        | little-endian, see below    |
```

Offsets 0..7 are the dongle's wrapper header. Offsets 8..13 are a
standard Modbus PDU. The CRC at offsets 14..15 is computed over the
six PDU bytes (`SlaveID..Count`) only, **not** over the wrapper header.

Example (TID=1, DevCode=12345, read 34 regs starting at 201):

```
00 01 30 39 00 0A FF 04 01 03 00 C9 00 22 15 ED
└tid┘ └DevCode┘ └Sz─┘ AR FC SI FN └Reg┘ └Cnt┘ └CRC LE┘
```

## Response frame — two layouts

The dongle uses one of two response framings. Which one a given dongle
uses is not declared in the handshake, so the client must detect it
from the first response.

### Layout A — donor-repo form (80 bytes for 34 registers)

```
| offset | bytes | field        |
|--------|-------|--------------|
|   0    |  10   | Header       |  (mirrors request offsets 0..9)
|  10    | 2*N   | Register data | big-endian int16 values
|  ...   |   2   | CRC (LE)     |
```

Total length = `10 + 2*N + 2`. CRC is computed over offsets `[8 ..
end-of-data]` (header bytes 8..9, then all register data).

### Layout B — vendor pure-Modbus form (81 bytes for 34 registers)

```
| offset | bytes | field        |
|--------|-------|--------------|
|   0    |  10   | Header       |
|  10    |   1   | byte_count   |  = 2*N (e.g. 0x44 for 34 regs)
|  11    | 2*N   | Register data |
|  ...   |   2   | CRC (LE)     |
```

Total length = `10 + 1 + 2*N + 2`. CRC is computed over offsets
`[8 .. end-of-data]` including the byte_count byte. This shape matches
the vendor's `01 03 06 08 FC 13 88 04 B0 F7 F3` example for a
3-register read (where `06H` is the byte_count).

## CRC-16/Modbus

Standard Modbus RTU CRC: polynomial `0xA001`, init `0xFFFF`, serialised
low-byte-first in the frame. The canonical check value for ASCII
`"123456789"` is `0x4B37`. See `crc16` in `smartess_local/protocol.py`.

## Layout auto-detection

`Inverter.read()` reads `10 + 2*N + 2` bytes and tries layout A; if the CRC
fails it reads one more byte and tries layout B. If neither matches it raises
`InverterError` carrying the hex frame. The first successful read logs one INFO
line — `first read OK, layout=<A|B>, frame=<hex>` — so you can see which framing
your dongle uses.

**Verified:** the Aninerel 6.2kW dongle uses layout B; auto-detection of
layout A is kept for donor-repo-style firmware.

## Register map

Registers `201..234` (34 holding registers) are read in one shot per
snapshot. See `smartess_local/registers.py` for the
`(address, name, scale, unit, signed)` tuple per slot, and
[`data-source.md`](data-source.md) for the provenance trail of the
five scale/signedness corrections we applied during the vendor-doc audit.
