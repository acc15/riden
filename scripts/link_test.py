#!/usr/bin/env .venv/bin/python
"""Short read/write stability test for the RK6012 Bluetooth link.

Sequence:
  1. connect (retries, no controller power-cycle by default)
  2. read status a few times with the output OFF
  3. set a safe 5 V / 10 mA and turn the output ON
  4. read status repeatedly
  5. always set 0 V and switch the output OFF

If this fails while the 500-transaction read-only test passes, the problem is
in the RK6012 Bluetooth/Modbus bridge or its power stage, not the USB dongle.

Usage:
    link_test.py "bt://E2:F9:C6:24:71:C8?channel=1&timeout=0.5"
    link_test.py --cycles 30 --interval 0.5
"""
import argparse
import time

from riden import Riden

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("port", type=str,
               help="bt://MAC?channel=1... or a serial device")
p.add_argument("--cycles", type=int, default=20, help="status reads with output ON")
p.add_argument("--interval", type=float, default=0.5)
p.add_argument("--voltage", type=float, default=5.0)
p.add_argument("--current", type=float, default=0.01)
args = p.parse_args()
ok_off = 0
ok_on = 0


with Riden.connect(args.port, delay=0.2, keepalive=None) as rd:
    try:
        print(rd.identity())
        rd.write(i_set=args.current, v_set=args.voltage, en=False)

        print(f"--- output OFF, {args.voltage:g} V / {args.current * 1e3:g} mA set ---")
        for i in range(3):
            print(rd.status())
            ok_off += 1
            time.sleep(args.interval)

        rd.write(en=True)
        print("--- output ON ---")
        for i in range(args.cycles):
            try:
                rd.status()
            except Exception as exc:  # noqa: BLE001 - report any link failure
                print(f"[{i:03d}] FAIL: {type(exc).__name__}: {exc}")
                break
            ok_on += 1
            if i % 5 == 0:
                print(f"[{i:03d}] ok")
            time.sleep(args.interval)
    finally:
        try:
            rd.write(v_set=0, en=False)
            print("cleanup: 0 V, output OFF")
        except Exception as exc:  # noqa: BLE001 - report any cleanup failure
            print(
                f"WARNING: cleanup failed: {type(exc).__name__}: {exc}\n"
                "WARNING: TURN THE RK6012 OUTPUT OFF MANUALLY"
            )

print(f"status reads: OFF {ok_off}/3, ON {ok_on}/{args.cycles}")
