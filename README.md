# riden

A simple synchronous client for Riden laboratory power supplies (RD6006,
RD6006P, RD6006-Max, RD6012, RD6012P, RD6012H, RD6018, RD6018P, RD6024,
RD6030, RK6006, RK6006H, RK6012, RK6018, RK4206H, RK8009).

It speaks Modbus RTU over a regular serial port or Bluetooth Low Energy (BLE).

## Features

- synchronous API: `with Riden.connect(...) as rd: ...`; the caller never
  sees an event loop, and the BLE transport keeps bleak's loop in a private
  thread;
- Bluetooth LE via `bt://` URLs on Linux, macOS and Windows (`bleak`);
- batched I/O instead of one transaction per field: any set of fields is read
  in one Modbus transaction, and written in one transaction per contiguous
  register block;
- automatic model detection and per-model voltage/current scaling, including
  the RD6012P switchable current range;
- ready-made transport stack: transaction pacing, reconnect, logging, and
  optional keepalive pings.

## Requirements

- Python 3.14 or newer;
- Bluetooth LE via `bleak`: Linux with BlueZ, macOS, or Windows;
- any OS supported by pyserial for USB serial.

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
from riden import Riden

with Riden.connect("bt://E1:F9:C6:24:71:C8") as rd:
    print(rd.status())

    # Several fields — a single device transaction.
    v, i, p = rd.read("v", "i", "p").values()
    print(v, i, p)

    # Adjacent registers — a single write transaction.
    rd.write(v_set=5.0, i_set=0.1)
    rd.write(en=True)
```

The address above is the BLE address, not the Classic SPP MAC. A device name
also works, which is handy when the address is not known:

```python
with Riden.connect("bt://RK6006") as rd:
    ...
```

For USB serial, pass the device path:

```python
with Riden.connect("/dev/ttyUSB0") as rd:
    ...
```

For USB serial, the port is opened at 115200 baud, the factory setting. If the baud rate was
changed in the device menu (9600, 19200, 38400, 57600), pass it explicitly.
`timeout` is the read timeout in seconds (default `1.0`), `write_timeout` the
write timeout (default `None`, writes block, as in pyserial):

```python
with Riden.connect("/dev/ttyUSB0", baudrate=9600, timeout=0.5) as rd:
    ...
```

BLE has no baud rate, so for `bt://` the `baudrate` value only sets the
Modbus inter-frame timing.

For any other port setting (parity, stop bits, flow control, ...), create the
port with pyserial and pass the object:

```python
import serial

port = serial.serial_for_url(
    "/dev/ttyUSB0", baudrate=115200, parity=serial.PARITY_EVEN, timeout=1.0,
    do_not_open=True,
)
with Riden.connect(port) as rd:
    ...
```

`baudrate`, `timeout` and `write_timeout` apply only when the library creates
the port from a string. A port object keeps its own settings, so pyserial
defaults apply to anything not set: 9600 baud and `timeout=None`, which blocks
a read forever on a silent device. Set both explicitly.

The client takes over the port's lifetime: leaving `with` (or `close()`)
closes it, and a reconnect reopens it, even if it was passed in already open.
`do_not_open=True` is not required, but without it the port (for `bt://`, the
BLE connection) is opened immediately rather than by `with`.

USB works only when the USB interface is selected in the device menu.

Field names are case-insensitive, so `"V"` and `"v"` refer to the same field.

## Example: voltage sweep + status

```python
import time

from riden import Riden

with Riden.connect("bt://E1:F9:C6:24:71:C8") as rd:
    try:
        rd.write(v_set=0.0, i_set=0.1, en=True)

        for voltage in range(0, 60, 5):
            rd.write(v_set=float(voltage))
            time.sleep(2)
            print(rd.status())
    finally:
        rd.write(v_set=0.0, en=False)
```

## Bluetooth LE

The BLE transport uses `bleak` and works on Linux, macOS and Windows. The
Riden module does not require pairing: power the supply on and connect. It
advertises as `RK6006` (or the model name); on the tested RK6006/RK6012 the
BLE address is the Classic SPP MAC minus one, but a device name or a BLE scan
is more reliable.

The `bt://` scheme is kept for compatibility; it now selects the BLE
transport.

URL format:

```text
bt://ADDRESS_OR_NAME?connect_timeout=10
```

| Parameter         | Default | Meaning                          |
|-------------------|---------|----------------------------------|
| `connect_timeout` | `10`    | scan and connect timeout, seconds |

Only the parameters present in the URL are passed on; the defaults live in
`BtSerial`. An unknown parameter or an invalid value raises `ValueError`.
When several devices share the same name, pass the address instead.

The URL holds only link settings. `timeout` (read) and `write_timeout` are
regular port settings, passed as arguments, with pyserial semantics: `None`
blocks, `0` does not block, a positive value is a deadline for the whole call.
`Riden.connect("bt://...", timeout=0.5)` defaults to `1.0` s;
`serial.serial_for_url("bt://...", timeout=0.5)` and `BtSerial(address, timeout=0.5)`
default to `None`, as pyserial does.
`BtSerial` is registered as a pyserial URL handler, so `bt://` works anywhere a
regular serial port is accepted.

Some Riden Bluetooth modules drop an idle link. Enable keepalive pings if you
keep the connection open without traffic:

```python
with Riden.connect("bt://RK6006", keepalive=5.0) as rd:
    ...
```

When constructing `BtSerial` directly:

```python
from riden.bt import BtSerial

port = BtSerial("E1:F9:C6:24:71:C8", timeout=0.5)
```

`bleak` runs its asyncio loop in a private thread; the public API is the usual
blocking pyserial one, so `minimalmodbus`, retries and keepalive work
unchanged.

## RD6012P / RD6012PW current range

These models have two current ranges, switched on the front panel: 6 A with
0.1 mA resolution and 12 A with 1 mA resolution. The selected range is
reported in register 20 (`Field.I_RANGE`: `0` is 6 A, otherwise 12 A), and
the library scales every output current by the range that is actually
selected: `10000` for 6 A, `1000` for 12 A.

Reading a current also reads the range, in the same transaction:

```python
# I (11) and I_RANGE (20): one read, registers 11-20
i = rd.read("i")["i"]
```

A write needs the range to encode the current, so the range is read first
and then the setpoint is written. If the caller supplies `i_range`, it is
used as-is, nothing is read, and the range register is written before the
current:

```python
# 1 read of I_RANGE, then 1 write of I_SET
rd.write(i_set=0.5)

# No reads: I_RANGE is written first, then I_SET
rd.write(i_set=0.5, i_range=0)
```

Every preset M0..M9 has its own range register, so a preset takes five
registers instead of four (V, I, OVP, OCP, I_RANGE):

| Preset | V   | I   | OVP | OCP | I_RANGE |
|--------|-----|-----|-----|-----|---------|
| M0     | 80  | 81  | 82  | 83  | 84      |
| M1     | 85  | 86  | 87  | 88  | 89      |
| ...    |     |     |     |     |         |
| M9     | 125 | 126 | 127 | 128 | 129     |

`M*_I` and `M*_OCP` are scaled by their own `M*_I_RANGE`, so a complete
preset is still one transaction and needs no reads:

```python
# One write of five registers starting at 85
rd.write(m1_v=5.0, m1_i=1.0, m1_ovp=60.0, m1_ocp=1.0, m1_i_range=0)
```

On models without a selectable range, `M0_I_RANGE`..`M9_I_RANGE` are virtual:
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
v, i, p = rd.read("v", "i", "p").values()

# V_SET (8) and EN (18): still 1 transaction, but registers 8-18 (11 registers)
rd.read("v_set", "en")
```

Fields far apart make that one transaction longer, so grouping nearby fields
is preferable.

**`write()` uses one transaction per contiguous block.** It encodes and
validates all values first, then merges fields whose registers follow each
other without a gap into one block. Every gap starts a new block and a new
transaction. A value scaled by another field needs that field first: a missing
dependency is read in one transaction, while a dependency passed by the caller
is used as-is.

```python
# V_SET (8) and I_SET (9) are adjacent: 1 transaction
rd.write(v_set=5.0, i_set=0.1)

# V_SET (8), I_SET (9) and EN (18): 2 transactions,
# registers 8-9, then register 18
rd.write(v_set=5.0, i_set=0.1, en=True)
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
