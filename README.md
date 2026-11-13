# riden

A simple synchronous, single-threaded client for Riden laboratory power
supplies (RD6006, RD6006P, RD6012, RD6012P, RD6018, RD6024, RK6006).

It speaks Modbus RTU over a regular serial port or Bluetooth SPP (RFCOMM) on
Linux.

## Features

- synchronous API with no background event loop:
  `with Riden.connect(...) as rd: ...`;
- Bluetooth on Linux via `bt://` URLs (`AF_BLUETOOTH` + RFCOMM);
- batched I/O: fields are read and written in one Modbus transaction per
  contiguous register block, not one transaction per field;
- automatic model and voltage/current scale detection on connect;
- ready-made transport stack: transaction pacing, reconnect, logging, and
  optional keepalive pings;
- encrypted Bluetooth link by default, which keeps idle connections alive.

## Requirements

- Python 3.14 or newer;
- Linux with BlueZ for Bluetooth SPP;
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

with Riden.connect("bt://E2:F9:C6:24:71:C8?channel=1&timeout=0.5") as rd:
    print(rd.status())

    # Several fields — a single device transaction.
    v, i, p = rd.read("v", "i", "p").values()
    print(v, i, p)

    # Several fields — a single write transaction.
    rd.write(v_set=5.0, i_set=0.1, en=True)
```

For USB serial, pass the device path:

```python
with Riden.connect("/dev/ttyUSB0") as rd:
    ...
```

Field names are case-insensitive, so `"V"` and `"v"` refer to the same field.

## Example: voltage sweep + status

```python
import time

from riden import Riden

with Riden.connect("bt://E2:F9:C6:24:71:C8?channel=1&timeout=0.5") as rd:
    try:
        rd.write(v_set=0.0, i_set=0.1, en=True)

        for voltage in range(0, 60, 5):
            rd.write(v_set=float(voltage))
            time.sleep(2)
            print(rd.status())
    finally:
        rd.write(v_set=0.0, en=False)
```

## Bluetooth on Linux

Pair the device once before the first connection (the PIN is usually `1234`):

```sh
bluetoothctl pair AA:BB:CC:DD:EE:FF
```

`bluetoothctl trust` is not required: it only affects connections managed by
`bluetoothd` (auto-reconnect, incoming connections), not the RFCOMM socket
this library opens.

URL format:

```text
bt://AA:BB:CC:DD:EE:FF?channel=1&timeout=0.5
```

| Parameter         | Default  | Meaning                                       |
|-------------------|----------|-----------------------------------------------|
| `channel`         | `1`      | RFCOMM channel, `1`..`30`                     |
| `timeout`         | `0.5`    | read/write timeout, seconds                   |
| `connect_timeout` | `10`     | connection timeout, seconds                   |
| `security`        | `medium` | `low`, `medium`, `high`, `fips` (see below)   |

Only the parameters present in the URL are passed on; the defaults live in
`BtSerial`. An unknown parameter or an invalid value raises `ValueError`.
`BtSerial` is registered as a pyserial URL handler, so `bt://` works anywhere a
regular serial port is accepted.

### Security level

`security` sets the RFCOMM socket security level (`BT_SECURITY` in BlueZ),
which the kernel enforces before the connection is used:

| Level    | Requirement                                                     |
|----------|-----------------------------------------------------------------|
| `low`    | no authentication, no encryption                                |
| `medium` | authenticated and encrypted link; any stored link key will do   |
| `high`   | as `medium`, but the link key must be MITM-protected            |
| `fips`   | Secure Connections only                                         |

The default is `medium`. A plain Linux RFCOMM socket uses `low`, and with it
the Bluetooth module of the Riden supply (tested on RK6012) drops the link
after about 8–10 s without traffic: the next request fails with
`TimeoutError: [Errno 110] Connection timed out`. In an HCI capture
(`btmon`) this is `Disconnect Complete` with reason `Connection Timeout
(0x08)`: the PSU stops answering at the radio level, while the host never
asks to disconnect. With an encrypted link the same device stays connected
while idle (verified for 60 s). The behaviour did not depend on the USB
dongle (reproduced on Realtek and Broadcom controllers). Android apps are not
affected because Android opens secure RFCOMM sockets by default.

`medium` needs a paired device: the kernel authenticates with the stored link
key, without any prompt. `high` usually fails with Riden supplies, because a
key from legacy pairing with a 4-digit PIN is not considered MITM-protected.
Use `security=low` only for a device that cannot be paired, and enable
keepalive pings in that case:

```python
with Riden.connect("bt://AA:BB:CC:DD:EE:FF?security=low", keepalive=5.0) as rd:
    ...
```

When constructing `BtSerial` directly, pass the enum:

```python
from riden.bt import BtSerial, SecurityLevel

port = BtSerial("AA:BB:CC:DD:EE:FF", security=SecurityLevel.LOW)
```

## Performance

`read()` selects the requested fields, computes their overall address range,
and issues **one** `read_registers` call for the whole range, then decodes the
raw registers into fields. `write()` encodes and validates all values first,
merges adjacent fields into contiguous blocks, and sends one transaction per
block.

Therefore:

```python
# 1 transaction instead of 3
v, i, p = rd.read("v", "i", "p").values()

# 1 transaction instead of 3
rd.write(v_set=5.0, i_set=0.1, en=True)
```

Sparse fields are still read in one transaction spanning the whole range
between them, so grouping nearby fields is preferable.

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
uv run scripts/link_test.py "bt://E2:F9:C6:24:71:C8?channel=1&timeout=0.5"
```

`just --list` shows the remaining tasks.

## License

MIT — see [LICENSE](https://github.com/acc15/riden/blob/master/LICENSE).
