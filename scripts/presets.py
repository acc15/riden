import asyncio
import functools
import operator
from dataclasses import dataclass, fields

import config

from riden import Riden

DEFAULT_ADDRESS = "E1:F9:C6:24:71:C8"
DEFAULT_URL = f"bt://{DEFAULT_ADDRESS}"

@dataclass(frozen=True, slots=True)
class Preset:
    v: float
    i: float
    ovp: float = 62
    ocp: float = 6.2
    i_range: float = 0

    def as_dict(self, index: int):
        return { f"m{index}_{field.name}": getattr(self, field.name) for field in fields(self) }


presets = [
    Preset(3.3, 0.1),
    Preset(5, 0.1),
    Preset(9, 0.1),
    Preset(12, 0.1),
    Preset(15, 0.1),
    Preset(20, 0.1),
    Preset(24, 0.1),
    Preset(28, 0.1),
    Preset(48, 0.1),
    Preset(60, 0.1),
]

async def main() -> None:
    fields = functools.reduce(operator.or_, ( p.as_dict(i) for i, p in enumerate(presets)), {})
    async with Riden.connect(config.DEFAULT_URL) as rd:
        await rd.write(fields)
        # for i, p  in enumerate(presets):
        #     await rd.write(p.as_dict(i))
        print("Done!!! Check presets in settings!")

asyncio.run(main())