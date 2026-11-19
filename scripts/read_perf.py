#!/usr/bin/env .venv/bin/python

import asyncio
import time

import config

from riden import Field, Riden


async def measure_perf(rd: Riden, fn) -> None:
    start = time.perf_counter()
    await fn(rd)
    print(f"{fn.__name__} executed in {time.perf_counter() - start}s")


async def single_long_read(rd: Riden) -> None:
    layout = rd.require_state().layout
    print(
        await rd.read(
            f
            for f in layout.fields()
            if (located := layout.resolve(f)) is not None and located.reg.read is not None
        )
    )


async def two_short_reads(rd: Riden) -> None:
    print(await rd.read(Field.ID), await rd.read(Field.V))


async def main() -> None:
    async with Riden.connect(config.DEFAULT_URL) as rd:
        await measure_perf(rd, single_long_read)
        await measure_perf(rd, two_short_reads)


asyncio.run(main())
