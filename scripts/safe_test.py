#!/usr/bin/env .venv/bin/python
"""Safe low-voltage test: 5 V, 50 mA, output on for ~2 s, then off."""
import argparse
import time

import config

from riden import Field, Riden

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--url", default=config.DEFAULT_URL)
args = p.parse_args()


with Riden.connect(args.url, delay=0.02, keepalive=None) as rd:
    try:
        print("=== before ===")
        print(rd.status())
        print(
            "values:",
            rd.read(Field.V_SET, Field.I_SET, Field.EN, Field.V, Field.I),
        )

        rd.write(v_set=5.0, i_set=0.05)
        time.sleep(0.5)
        print("\n=== set 5.00 V / 0.050 A, output still off ===")
        print(rd.status())
        print(
            "values:",
            rd.read(Field.V_SET, Field.I_SET, Field.EN, Field.V, Field.I),
        )

        rd.write(en=True)
        time.sleep(1.0)
        print("\n=== output ON ===")
        print(rd.status())
        print(
            "values:",
            rd.read(Field.V_SET, Field.I_SET, Field.EN, Field.V, Field.I),
        )

        time.sleep(1.0)
        print("\n=== output ON (second read) ===")
        print(rd.status())
    finally:
        try:
            rd.write(en=False, v_set=0.0)
            time.sleep(0.3)
            print("\n=== output OFF ===")
            print(rd.status())
            print(
            "values:",
            rd.read(Field.V_SET, Field.I_SET, Field.EN, Field.V, Field.I),
        )
        except Exception as exc:  # noqa: BLE001 - report any cleanup failure
            print(
                f"WARNING: cleanup failed: {type(exc).__name__}: {exc}\n"
                "WARNING: TURN THE RIDEN OUTPUT OFF MANUALLY"
            )
