# Architecture

`smartess-local` is a thin async client. Each module has one job:

```
smartess_local/
  protocol.py    # pure byte helpers: crc16, frame build/parse
  registers.py   # vendor-corrected register table (34 slots, 201..234)
  state.py       # typed snapshot: InverterState, WorkingMode
  inverter.py    # async client: Inverter context manager (the only I/O)
  cli.py         # argparse + JSON output + main()
```

`protocol.py`, `registers.py`, and `state.py` are pure (no I/O) and pinned to
vendor test vectors. `inverter.py` owns the network lifecycle; `cli.py` glues
it behind a small argparse interface.

## Lifecycle

```
1. async with Inverter(inverter_ip=..., local_ip=...) as inv:
   ├─ UDP send  "set>server=<local_ip>:<local_port>;"  →  dongle :58899
   ├─ UDP recv  "rsp>server=<dev_code>;"
   ├─ asyncio.start_server on local_ip:local_port
   └─ wait for the dongle to TCP-dial-back (timeout = inv.timeout)

2. state = await inv.read()       # build request, decode response → InverterState
3. async for state in inv.stream(interval=10.0): ...
4. __aexit__: close connection + server
```

The dongle is the TCP *client* — the quirk of the local protocol is that you
listen, not connect. Byte-level frame details: [`protocol.md`](protocol.md).

## Limitations

- Read-only; write operations are not implemented.
- No auto-reconnect: a dongle drop raises `InverterError`, and the caller
  restarts the context manager.
