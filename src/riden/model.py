from collections.abc import Sequence
from enum import Enum


class Model(Enum):
    RD6006 = (range(60060, 60065), 100, 1000, 60, 6)
    RD6006P = ([60065], 1000, 10000, 60, 6)
    RK6006 = ([60066], 100, 1000, 60, 6)
    RD6012 = (range(60120, 60125), 100, 100, 60, 12)
    RD6012P = (range(60125, 60130), 1000, 100, 60, 12)
    RD6018 = (range(60180, 60190), 100, 100, 60, 18)
    RD6024 = (range(60241, 60250), 100, 100, 60, 24)

    def __init__(self, codes: Sequence[int], v_scale: int, i_scale: int, v_max: int, i_max: int):
        self.codes = codes
        self.v_scale = v_scale
        self.i_scale = i_scale
        self.v_max = v_max
        self.i_max = i_max

    def v_clamp(self, value: float, offset: float = 0) -> int:
        return round(max(0, min(self.v_max + offset, value)) * self.v_scale)

    def i_clamp(self, value: float, offset: float = 0) -> int:
        return round(max(0, min(self.i_max + offset, value)) * self.i_scale)

    @staticmethod
    def find(code: int) -> Model:
        for model in Model:
            if code in model.codes:
                return model
        return next(iter(Model))