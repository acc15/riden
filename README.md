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
- ready-made transport stack: transaction pacing, keepalive, reconnect, and
  logging.

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

Pair and trust the device first (`bluetoothctl pair/trust`); the RFCOMM
channel is usually `1`. URL format:

```text
bt://AA:BB:CC:DD:EE:FF?channel=1&timeout=0.5
```

`timeout` and `connect_timeout` are specified in seconds as query parameters.
`BtSerial` is registered as a pyserial URL handler, so `bt://` works anywhere a
regular serial port is accepted.

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
just publish            # patch release: bump, build, upload to PyPI
just publish-minor      # minor release (publish-major for major)
just publish --dry-run  # no bump and no tag, only verify the upload
just bump               # bump patch, commit and tag without uploading
just bump-minor         # same for minor (bump-major for major)
git push --follow-tags  # bump-my-version does not push
```

Publishing tokens are read from `.env` (see `.env.example`). The working tree
must be clean: `bump-my-version` refuses to bump otherwise.

`just publish-test` uploads the current version to TestPyPI without bumping or
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
