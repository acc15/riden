from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from .field import Field, PresetField, PresetParam

type PresetMapping = (
    Mapping[str, Any]
    | Mapping[PresetParam, Any]
    | Mapping[str | PresetParam, Any]
)
"""A mapping of preset parameter names or enums to values."""


@dataclass(frozen=True, slots=True)
class Preset:
    """One of the device's presets.

    Iterating a preset yields all of its fields, so it can be passed directly
    to ``read()``.  ``only()`` selects a subset for reading, while
    ``params()`` builds the field mapping accepted by ``write()``.
    """

    num: int

    def __post_init__(self) -> None:
        if self.num < 0:
            raise ValueError(f"preset number must be non-negative: {self.num}")

    def __iter__(self) -> Iterator[PresetField]:
        yield from self.only()

    def only(self, *params: str | PresetParam) -> tuple[PresetField, ...]:
        """Return only the selected fields of this preset.

        Without arguments all preset fields are returned.  Parameter names or
        ``PresetParam`` members may be passed to select a subset.
        """
        selected = params or tuple(PresetParam)
        return tuple(PresetField(self.num, self._param(param)) for param in selected)

    def params(
        self,
        *values: PresetMapping,
        **fields: Any,
    ) -> dict[PresetField, Any]:
        """Map parameter names or enums to concrete fields of this preset.

        Later mappings override earlier ones, and keyword arguments override
        all mappings, matching ``Riden.write``.
        """
        merged: dict[PresetField, Any] = {}
        for mapping in (*values, fields):
            for key, value in mapping.items():
                merged[PresetField(self.num, self._param(key))] = value
        return merged

    @staticmethod
    def _param(value: object) -> PresetParam:
        if isinstance(value, PresetParam):
            return value
        if isinstance(value, PresetField):
            raise TypeError("PresetField is already concrete; pass it to write() directly")
        if isinstance(value, Field):
            raise TypeError("global Field is not a preset parameter; use PresetParam")
        if isinstance(value, str):
            return PresetParam(value)
        raise TypeError(f"not a preset parameter: {value!r}")
