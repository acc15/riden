import asyncio

import config

from riden import Riden


async def main() -> None:
    async with Riden.connect(config.DEFAULT_URL, config.DEFAULT_ADDRESS) as rd:
        state = rd.state
        print("connected", state.id, state.sn, state.fw)


asyncio.run(main())