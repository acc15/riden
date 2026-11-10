#!/usr/bin/env .venv/bin/python
"""Stress-test the Bluetooth link with read-only Modbus transactions.

Usage:
    stress.py [count] [delay] [--url bt://...]

The default URL points at the known RK6012.  The port is opened through
pyserial's serial_for_url(), so any supported URL (bt://, /dev/ttyUSB0,
socket://...) can be used.
"""
import argparse
import time

from config import DEFAULT_URL

from riden import Delayed, Field, Modbus, Reconnectable, Riden

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("count", type=int, nargs="?", default=50)
p.add_argument("delay", type=float, nargs="?", default=0.3)
p.add_argument("--url", default=DEFAULT_URL)
p.add_argument("--address", type=int, default=1)
p.add_argument("--transaction-delay", type=float, default=0.02)
args = p.parse_args()


ok = 0
with Riden(Reconnectable(Delayed(Modbus(args.url, address=args.address), delay=args.transaction_delay))) as rd:
    t0 = time.monotonic()
    for i in range(args.count):
        try:
            values = rd.read(
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
        time.sleep(args.delay)
    else:
        print(f"ALL {args.count} transactions OK in {time.monotonic()-t0:.1f}s")

print(f"total ok: {ok}/{args.count}")
