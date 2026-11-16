#!/usr/bin/env .venv/bin/python

import asyncio

import config

from riden import Riden


async def main() -> None:
    async with Riden.connect(config.DEFAULT_URL, auto_reconnect=False) as rd:
        await rd.write(v_set=12, en=True)
        await asyncio.sleep(20)
        await rd.write(v_set=5, en=False)


asyncio.run(main())
