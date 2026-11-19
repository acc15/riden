# riden

An asynchronous client for Riden laboratory power supplies (RD6006, RD6006P,
RD6006-Max, RD6012, RD6012P, RD6012H, RD6018, RD6018P, RD6024, RD6030, RK6006,
RK6006H, RK6012, RK6018, RK4206H, RK8009).

It speaks Modbus RTU over a regular serial port or Bluetooth Low Energy (BLE).

## Features

- asyncio API: `async with Riden.connect(...) as rd: ...`;
- Bluetooth LE via `bt://` URLs on Linux, macOS and Windows (`bleak`);
- Modbus RTU through `tmodbus`, including CRC/framing, timeouts and automatic
  reconnect;
- batched I/O instead of one transaction per field: any set of fields is read
  in one Modbus transaction, and written in one transaction per contiguous
  register block;
- automatic model detection and per-model voltage/current scaling, including
  the RD6012P switchable current range;
- read-only model metadata as regular fields: nominal limits, raw scales and
  write tolerances.

## Requirements

- Python 3.14 or newer;
- `tmodbus[async-serial]` for Modbus RTU (installed automatically);
- `bleak` for Bluetooth LE (installed automatically);
- Linux with BlueZ, macOS, or Windows for BLE; any OS supported by `serialx`
  for USB serial.

## Install

```sh
uv add riden
```

or with pip:

```sh
pip install riden
```

From source:

```sh
git clone https://github.com/acc15/riden
cd riden
uv sync
```

## Quick start

```python
import asyncio

from riden import Riden


async def main() -> None:
    async with Riden.connect("bt://E1:F9:C6:24:71:C8") as rd:
        print(await rd.status())

        # Several fields — a single device transaction.
        v, i, p = (await rd.read("v", "i", "p")).values()
        print(v, i, p)

        # Adjacent registers — a single write transaction.
        await rd.write(v_set=5.0, i_set=0.1)
        await rd.write(en=True)


if __name__ == "__main__":
    asyncio.run(main())
```

The address above is the BLE address, not the Classic SPP MAC. All Riden
modules advertise under the same name (`RK6006`), so the URL takes an address;
a device name cannot tell several supplies apart.

For USB serial, pass the device path:

```python
async with Riden.connect("/dev/ttyUSB0") as rd:
    ...
```

The USB port is opened at 115200 baud, the factory setting. If the baud rate
was changed in the device menu (9600, 19200, 38400, 57600), pass it
explicitly. `timeout` is the Modbus response timeout in seconds (default
`1.0`), and `delay` is the pause between transactions (default `0.02`):

```python
async with Riden.connect("/dev/ttyUSB0", baudrate=9600, timeout=0.5) as rd:
    ...
```

BLE has no baud rate; `baudrate` applies only to serial ports. The BLE
connection timeout is the `connect_timeout` argument of `Riden.connect`.

`auto_reconnect` (default `True`) enables tmodbus's automatic reconnect.
Set it to `False` for a strict one-shot session.

Construction parses the URL and builds the tmodbus client without I/O.
`async with` connects and reads the identity; a failed open closes the client
again. `close()` is idempotent.

USB works only when the USB interface is selected in the device menu.

Field names are case-insensitive on input, so `"V"`, `"v"`, `"M1_V"` and
`"m1_v"` all refer to the same field.  Results are keyed by the canonical
lowercase name (`"v"`, `"m1_v"`), not by the spelling that was passed in.

## Several supplies in one loop

All clients share the caller's asyncio loop; no threads are involved:

```python
import asyncio

from riden import Riden


async def main() -> None:
    async with (
        Riden.connect("bt://<MAC1>") as master,
        Riden.connect("bt://<MAC2>") as follower1,
        Riden.connect("bt://<MAC3>") as follower2,
    ):
        while True:
            values = await master.read("v", "i")
            v, i = values["v"], values["i"]

            await asyncio.gather(
                follower1.write({"v_set": v, "i_set": i}),
                follower2.write({"v_set": v, "i_set": i}),
            )
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
```

`async with` opens the clients sequentially, which also avoids BlueZ's
`InProgress` error from simultaneous discoveries. To connect several supplies
in parallel, scan once and pass the discovered `BLEDevice` objects directly:

```python
import asyncio

from bleak import BleakScanner
from riden import Riden

MAC1, MAC2, MAC3 = "E1:F9:C6:24:71:C8", "26:05:E9:A3:00:37", "AA:BB:CC:DD:EE:FF"


async def main() -> None:
    found = await BleakScanner.discover(timeout=5, return_adv=True)
    devices = [
        device for address, (device, _adv) in found.items()
        if address in {MAC1, MAC2, MAC3}
    ]

    rds = [Riden.connect(device) for device in devices]
    await asyncio.gather(*(rd.open() for rd in rds))
    try:
        ...
    finally:
        await asyncio.gather(*(rd.close() for rd in rds))


asyncio.run(main())
```

`BleTransport` is still exported for custom UUIDs or timeouts; `Riden.connect`
accepts a prebuilt transport as well.

## Example: voltage sweep + status

```python
import asyncio

from riden import Riden


async def main() -> None:
    async with Riden.connect("bt://E1:F9:C6:24:71:C8") as rd:
        try:
            await rd.write(v_set=0.0, i_set=0.1, en=True)

            for voltage in range(0, 60, 5):
                await rd.write(v_set=float(voltage))
                await asyncio.sleep(2)
                print(await rd.status())
        finally:
            await rd.write(v_set=0.0, en=False)


asyncio.run(main())
```

## Bluetooth LE

The BLE transport uses `bleak` and works on Linux, macOS and Windows. The
Riden module does not require pairing: power the supply on and connect. All
modules advertise as `RK6006`, so use the BLE address, not the name. On the
tested RK6006/RK6012 the BLE address is the Classic SPP MAC minus one; a BLE
scan (`bluetoothctl`, `BleakScanner`) shows the exact address. On macOS the
BLE address is a CoreBluetooth UUID rather than a MAC.

The `bt://` scheme is accepted. Everything after `://` is passed to bleak as the BLE address; there is no URL query parsing:

```python
async with Riden.connect(
    "bt://E1:F9:C6:24:71:C8", connect_timeout=5
) as rd:
    ...
```

`timeout`, `delay` and `connect_timeout` are regular arguments of
`Riden.connect`, as with any other port.

No keepalive is needed: both tested Riden BLE modules keep an idle link for at
least a minute. If a particular adapter drops an idle link, tmodbus's
automatic reconnect opens it again on the next transaction.

## Model metadata

Models expose their nominal limits, raw scales and write tolerances as
ordinary read-only fields. They are virtual: reading them costs no I/O.
The exception is RD6012P, where `I_MAX`/`I_SCALE` and the per-preset
`m*_i_max`/`m*_i_scale` fields read the current range registers they follow;
see the RD6012P section below.

| Field | Meaning |
|-------|---------|
| `V_MAX` | nominal voltage limit, V |
| `V_SCALE` | raw units per volt (`1000` means 1 mV) |
| `V_TOLERANCE` | extra volts accepted by `V_SET` and preset V |
| `OVP_TOLERANCE` | extra volts accepted by preset OVP |
| `I_MAX` | current limit of the selected output range, A |
| `I_SCALE` | raw units per ampere of the selected output range |
| `I_TOLERANCE` | extra amperes accepted by `I_SET` and preset I |
| `OCP_TOLERANCE` | extra amperes accepted by preset OCP |
| `P_MAX` | nominal rated power, W (`v_max * max(i_max)`) |
| `P_SCALE` | raw units per watt |
| `m*_i_max`, `m*_i_scale` | current limit and scale of one preset |

`I_MAX`/`I_SCALE` follow the output range, while each preset's
`m*_i_max`/`m*_i_scale` pair follows that preset's own range. `P_MAX` is
nominal and does not change with the range: for RD6012P it is 720 W even in
the 6 A range.

Tolerance is the margin the device accepts above the nominal limit for a
write, not measurement accuracy. The actual encoding limits are
`V_MAX + V_TOLERANCE` for voltage setpoints, `V_MAX + OVP_TOLERANCE` for OVP,
`I_MAX + I_TOLERANCE` for current setpoints and `I_MAX + OCP_TOLERANCE` for
OCP.

```python
meta = await rd.read("v_max", "v_scale", "i_max", "i_scale", "p_max")

# The selected range limit and its write margin, in one read.
limits = await rd.read("i_max", "i_tolerance")
max_current = limits["i_max"] + limits["i_tolerance"]
```

Metadata fields are read-only: passing one to `write()` raises `ValueError`
before any I/O. They can still be supplied in `deps` to override how another
field is decoded or encoded; as with any `deps`, the caller is responsible for
the values.

## Preset fields

Preset fields can be named as strings (`"m1_v"`, `"m1_i_range"`) or built
from a preset number and a `PresetParam`:

```python
from riden import PresetField, PresetParam

v = PresetField(1, PresetParam.V)       # m1_v
i = PresetField(1, PresetParam.I)       # m1_i
ovp = PresetField(1, PresetParam.OVP)   # m1_ovp

# A PresetField is a str, so it indexes the name-keyed result directly.
value = (await rd.read(v))[v]

await rd.write({i: 1.0, ovp: 60.0})
```

`PresetParam` is the parameter inside a preset (`V`, `I`, `OVP`, `OCP`,
`I_RANGE`, `I_MAX`, `I_SCALE`); `PresetField` adds the preset number. Both
forms work in `read()`, `write()` and `deps=`.

## RD6012P / RD6012PW current range

These models have two current ranges, switched on the front panel: 6 A with
0.1 mA resolution and 12 A with 1 mA resolution. The selected range is
reported in register 20 (`Field.I_RANGE`: `0` is 6 A, otherwise 12 A), and
the library scales every output current by the range that is actually
selected: `10000` for 6 A, `1000` for 12 A. The selected limit and scale are
also available as `I_MAX`/`I_SCALE`, and per preset as `m*_i_max`/`m*_i_scale`.
Reading `I_MAX`/`I_SCALE` reads `I_RANGE` (register 20) in the same
transaction; a preset's `m*_i_max`/`m*_i_scale` reads that preset's
`m*_i_range` (register 84 for M0, 89 for M1, and so on). On models without a
range switch these fields are constants and need no I/O.

Reading a current also reads the range, in the same transaction:

```python
# I (11) and I_RANGE (20): one read, registers 11-20
i = (await rd.read("i"))["i"]
```

If the range is already known, pass it as `deps`: the range register is not
read, its value is used to decode the other fields, and the result keeps the
same shape. This is useful in a loop that reads currents while the range stays
fixed:

```python
# I_RANGE is unknown: read I_SET (9), I (11) and I_RANGE (20)
values = await rd.read("i_set", "i", "i_range")

# I_RANGE is known: read only I_SET (9) and I (11); I_RANGE is taken from deps
values = await rd.read(
    "i_set", "i", "i_range", deps={"i_range": values["i_range"]}
)
```

Measured current needs only the scale, so a known scale alone avoids the range
register:

```python
# The 12 A scale is known: read only I (11), not I_RANGE (20)
i = (await rd.read("i", deps={"i_scale": 1000}))["i"]
```

`deps` values are semantic (`i_range` is 0 or 1, not a raw register). The
caller is responsible for their correctness: a stale or wrong range produces
plausible-looking but wrong readings.

A write needs the range to encode the current, so the range is read first
and then the setpoint is written. If the caller supplies `i_range`, it is
used as-is, nothing is read, and the range register is written before the
current:

```python
# 1 read of I_RANGE, then 1 write of I_SET
await rd.write(i_set=0.5)

# No reads: I_RANGE is written first, then I_SET
await rd.write(i_set=0.5, i_range=0)
```

If the range is known but must not be written, pass it as `deps` instead:

```python
# No reads and no range write: I_RANGE is used only to encode I_SET
await rd.write(i_set=0.5, deps={"i_range": 0})
```

When all encoding dependencies are known, even the range register is not
needed:

```python
# No reads: scale, limit and tolerance come from deps
await rd.write(
    i_set=0.5,
    deps={"i_scale": 10000, "i_max": 6, "i_tolerance": 0.1},
)
```

Values passed as fields are authoritative: if a field is both written and
named in `deps`, the written value is used.

Every preset M0..M9 has its own range register, so a preset takes five
registers instead of four (V, I, OVP, OCP, I_RANGE):

| Preset | V   | I   | OVP | OCP | I_RANGE |
|--------|-----|-----|-----|-----|---------|
| M0     | 80  | 81  | 82  | 83  | 84      |
| M1     | 85  | 86  | 87  | 88  | 89      |
| ...    |     |     |     |     |         |
| M9     | 125 | 126 | 127 | 128 | 129     |

A preset's `m*_i` and `m*_ocp` are scaled by its own `m*_i_range`, so a
complete preset is still one transaction and needs no reads:

```python
# One write of five registers starting at 85
await rd.write(m1_v=5.0, m1_i=1.0, m1_ovp=60.0, m1_ocp=1.0, m1_i_range=0)
```

On models without a selectable range, `m0_i_range`..`m9_i_range` are virtual:
reading them returns `False`, and writing them is accepted but changes
nothing. `I_RANGE` is a real register on all models; models without a range
switch report `0`.

The 12 A range also has its own output-current calibration pair,
`Field.CAL_I12_ZERO` / `Field.CAL_I12_SCALE` (registers 63 and 64).

One thing is not verified on hardware: whether the device rescales currents
already stored in a preset when the front-panel range changes. The library
always writes a preset's currents together with its range register, so a
freshly written preset is consistent.

## Performance

Reads and writes are batched differently, because Modbus can read a register
range with gaps in it, but it cannot write a sparse list of registers.

**`read()` always uses one transaction.** It computes the overall address
range of the requested fields and reads all of it at once, including any
registers between them, then decodes the fields:

```python
# V (10), I (11), P (12-13): 1 transaction, registers 10-13
v, i, p = (await rd.read("v", "i", "p")).values()

# V_SET (8) and EN (18): still 1 transaction, but registers 8-18 (11 registers)
await rd.read("v_set", "en")
```

Fields far apart make that one transaction longer, so grouping nearby fields
is preferable. Dependencies passed through `deps` are not read, so a request
with every dependency supplied needs no transaction at all:

```python
# Only v: one transaction, register 10
await rd.read("v")

# v and a known i_range: still one transaction, register 10
await rd.read("v", deps={"i_range": 0})
```

Virtual metadata fields do not widen the span. The exception is the
range-dependent current metadata on RD6012P; see the RD6012P section below.

**`write()` uses one transaction per contiguous block.** It encodes and
validates all values first, then merges fields whose registers follow each
other without a gap into one block. Every gap starts a new block and a new
transaction. A value scaled by another field needs that field first: a missing
dependency is read in one transaction, while a dependency passed by the caller
is used as-is. A dependency passed through `deps` is neither read nor written.

```python
# V_SET (8) and I_SET (9) are adjacent: 1 transaction
await rd.write(v_set=5.0, i_set=0.1)

# V_SET (8), I_SET (9) and EN (18): 2 transactions,
# registers 8-9, then register 18
await rd.write(v_set=5.0, i_set=0.1, en=True)
```

Since every value is validated before the first transaction, an invalid value
never leaves the device partially updated. A link failure between the
transactions still can: if the second write fails, the first one has
already been applied.

## Development

```sh
uv sync
uv build          # sdist + wheel in dist/
just check        # ty + ruff + pytest
```

### Releasing

Releases are prepared with `bump-my-version` (configured in `pyproject.toml`).
It bumps the version, runs `just check`, updates `uv.lock`, builds the
artifacts, commits and creates an annotated `v<version>` tag:

```sh
just bump patch           # bump, build, commit and tag
just bump minor           # minor (or major)
just bump minor --dry-run # verify without changing anything
just publish              # upload dist/ to PyPI
just publish --dry-run    # verify the upload without sending
git push --follow-tags    # bump-my-version does not push
```

The version part is required by `bump-my-version`: `just bump` without
`patch`/`minor`/`major` fails. `just publish` uploads the existing `dist/`
artifacts; `just bump` already builds them, or run `just build` explicitly.

Publishing tokens are read from `.env` (see `.env.example`). The working tree
must be clean: `bump-my-version` refuses to bump otherwise.

`just publish-test` uploads the current `dist/` to TestPyPI without bumping or
tagging. TestPyPI never accepts the same filename twice, even after the
release is deleted, so a repeated test needs a new version.

Scripts in `scripts/` are run through `uv run`:

```sh
uv run scripts/v_sweep.py
uv run scripts/link_test.py "bt://E1:F9:C6:24:71:C8"
```

`just --list` shows the remaining tasks.

## License

MIT — see [LICENSE](https://github.com/acc15/riden/blob/master/LICENSE).
