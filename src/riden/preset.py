from enum import Enum, auto
from typing import override


class PresetParam(Enum):
    """One parameter of a preset.

    ``PresetField`` combines a parameter with a preset number; this enum only
    names the parameter itself.
    """

    @override
    @staticmethod
    def _generate_next_value_(name: str, start: int, count: int, last_values: list[str]):
        return name.lower()

    V = auto()
    I = auto()
    OVP = auto()
    OCP = auto()
    I_RANGE = auto()
    I_MAX = auto()
    I_SCALE = auto()

    @override
    @classmethod
    def _missing_(cls, value: object) -> PresetParam | None:
        if isinstance(value, str):
            return cls.__members__.get(value.upper())
        return None


class PresetField(str):
    """A concrete field of one preset: a preset number and a parameter.

    It is a ``str`` so it can index the name-keyed result of
    :meth:`riden.riden.Riden.read` directly::

        field = PresetField(1, PresetParam.V)
        value = (await rd.read(field))[field]
    """

    __slots__ = ("num", "param")

    num: int
    param: PresetParam

    def __new__(cls, num: int, param: PresetParam | str):
        param = PresetParam(param)
        if num < 0:
            raise ValueError(f"preset number must be non-negative: {num}")
        self = super().__new__(cls, f"m{num}_{param.value}")
        object.__setattr__(self, "num", num)
        object.__setattr__(self, "param", param)
        return self

    @override
    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("PresetField is immutable")

    @property
    def value(self) -> str:
        return str(self)

    @override
    def __repr__(self) -> str:
        return f"PresetField({self.num}, {self.param!r})"
