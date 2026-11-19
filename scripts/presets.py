import asyncio

import config

from riden import Preset, PresetParam, Riden
from riden.field import merge_fields
from riden.preset import PresetMapping

# 3.3/5/9/12/24 — common logic, USB, battery and industrial voltages.
# 15/20 — USB PD SPR; 28/36/48 — USB PD 3.1 EPR.
VOLTAGES = (3.3, 5.0, 9.0, 12.0, 15.0, 20.0, 24.0, 28.0, 36.0, 48.0)
preset_base: PresetMapping = {
    PresetParam.I: 0.02,
    PresetParam.OVP: 62,
    PresetParam.OCP: 6.1,
    PresetParam.I_RANGE: 0
}

async def main() -> None:
    async with Riden.connect(config.DEFAULT_URL) as rd:
        count = rd.state.layout.presets.count
        await rd.write(merge_fields(*(Preset(i).params(preset_base, v = VOLTAGES[i]) for i in range(count))))
        print(f"Configured {count} presets")
        print(await rd.read(*(Preset(num) for num in range(count))))


asyncio.run(main())
