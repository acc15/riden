#!/usr/bin/env .venv/bin/python

import asyncio
import time

import config

from riden import Field, Riden


async def main() -> None:
    async with Riden.connect(config.DEFAULT_URL) as rd:
        try:
            await rd.write(v_set=0, i_set=0.1, en=True)
            for v in range(0, 60, 5):
                start = time.perf_counter()
                await rd.write(v_set=v)
                v_set_time = time.perf_counter()
                await asyncio.sleep(2)
                print(await rd.read(Field.V, Field.I, Field.P, Field.V_IN))
                end = time.perf_counter()
                print(
                    f"executed in {end-start}s, v_set in {v_set_time-start}s"
                )
        finally:
            await rd.write(v_set=5, i_set=0.1, en=False)


asyncio.run(main())
