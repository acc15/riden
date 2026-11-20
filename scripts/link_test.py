#!/usr/bin/env .venv/bin/python
"""Short read/write stability test for a Riden Bluetooth LE link.

Sequence:
  1. connect (retries, no controller power-cycle by default)
  2. read values a few times with the output OFF
  3. set a safe 5 V / 10 mA and turn the output ON
  4. read values repeatedly
  5. always set 0 V and switch the output OFF

If this fails while the 500-transaction read-only test passes, the problem is
in the Bluetooth/Modbus bridge or the power stage, not the USB dongle.

Usage:
    link_test.py "bt://E1:F9:C6:24:71:C8"
    link_test.py --cycles 30 --interval 0.5
"""
import argparse
import asyncio

from riden import Riden

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("port", type=str, help="bt://ADDRESS or a serial device")
p.add_argument("--cycles", type=int, default=20, help="value reads with output ON")
p.add_argument("--interval", type=float, default=0.5)
p.add_argument("--voltage", type=float, default=5.0)
p.add_argument("--current", type=float, default=0.01)
args = p.parse_args()


async def main() -> None:
    ok_off = 0
    ok_on = 0
    async with Riden.connect(args.port, delay=0.2) as rd:
        try:
            await rd.write(i_set=args.current, v_set=args.voltage, en=False)

            print(
                f"--- output OFF, {args.voltage:g} V / {args.current * 1e3:g} mA set ---"
            )
            for _ in range(3):
                print(await rd.read("v", "i", "p"))
                ok_off += 1
                await asyncio.sleep(args.interval)

            await rd.write(en=True)
            print("--- output ON ---")
            for i in range(args.cycles):
                try:
                    await rd.read("v", "i", "p")
                except Exception as exc:  # noqa: BLE001 - report any link failure
                    print(f"[{i:03d}] FAIL: {type(exc).__name__}: {exc}")
                    break
                ok_on += 1
                if i % 5 == 0:
                    print(f"[{i:03d}] ok")
                await asyncio.sleep(args.interval)
        finally:
            try:
                await rd.write(v_set=0, en=False)
                print("cleanup: 0 V, output OFF")
            except Exception as exc:  # noqa: BLE001 - report any cleanup failure
                print(
                    f"WARNING: cleanup failed: {type(exc).__name__}: {exc}\n"
                    "WARNING: TURN THE RK6012 OUTPUT OFF MANUALLY"
                )

    print(f"value reads: OFF {ok_off}/3, ON {ok_on}/{args.cycles}")


asyncio.run(main())
