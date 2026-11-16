#!/usr/bin/env .venv/bin/python
"""Stress-test the Bluetooth link with read-only Modbus transactions.

Usage:
    stress.py [count] [delay] [--url bt://...]

The default URL points at the known RK6006.  Any URL accepted by
Riden.connect (bt://, /dev/ttyUSB0, serialx URLs) can be used.
"""
import argparse
import asyncio
import time

from config import DEFAULT_URL

from riden import Field, Riden

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("count", type=int, nargs="?", default=50)
p.add_argument("delay", type=float, nargs="?", default=0.3)
p.add_argument("--url", default=DEFAULT_URL)
p.add_argument("--address", type=int, default=1)
args = p.parse_args()


async def main() -> None:
    ok = 0
    async with Riden.connect(args.url, args.address) as rd:
        t0 = time.monotonic()
        for i in range(args.count):
            try:
                values = await rd.read(
                    Field.V_SET,
                    Field.I_SET,
                    Field.V,
                    Field.I,
                    Field.P,
                    Field.V_IN,
                    Field.PROTECTION,
                    Field.MODE,
                    Field.EN,
                )
            except Exception as e:  # noqa: BLE001 - report any link failure
                print(f"[{i:03d}] FAIL after {ok} ok: {type(e).__name__}: {e}")
                break
            ok += 1
            if i % 5 == 0:
                print(
                    f"[{i:03d}] ok setV={values[Field.V_SET]:.2f} "
                    f"setI={values[Field.I_SET]:.3f} "
                    f"outV={values[Field.V]:.2f} outI={values[Field.I]:.3f} "
                    f"en={values[Field.EN]} t={time.monotonic()-t0:.1f}s"
                )
            await asyncio.sleep(args.delay)
        else:
            print(f"ALL {args.count} transactions OK in {time.monotonic()-t0:.1f}s")

    print(f"total ok: {ok}/{args.count}")


asyncio.run(main())
