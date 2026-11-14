from dataclasses import dataclass
from enum import Enum


def clamp(maximum: float, scale: float, v: float, off: float) -> int:
    """Encode ``v`` as a raw register value, checking it against the limit.

    The device acknowledges an out-of-range write but silently keeps the old
    value, so the range ``0..maximum + off`` is enforced here instead.  The
    check uses raw units, so float rounding cannot reject the limit itself.
    """
    raw = round(v * scale)
    limit = round((maximum + off) * scale)
    if not 0 <= raw <= limit:
        raise ValueError(f"{v} is out of range 0..{limit / scale}")
    return raw


@dataclass(frozen=True, slots=True)
class Spec:
    """Scaling and output limits of a device.

    ``codes`` is the exact set of values the ID register (register 0) may
    report for the model.  It is deliberately not a range: neighbouring IDs
    are different products with different scales (60181 is an RD6018 with
    0.1 A resolution, 60185 is an RD6018P with 1 mA), so a range would
    silently mis-scale every reading of the model at its edge.

    Raw register values are divided by ``*_scale`` on read and multiplied on
    write.  ``v_max``/``i_max`` are the nominal limits in volts and amperes;
    the device accepts setpoints up to ``v_max + 1`` and ``i_max + 0.1``,
    OVP up to ``v_max + 2`` and OCP up to ``i_max + 0.2``.
    """

    codes: frozenset[int]
    v_scale: int
    i_scale: int
    p_scale: int
    v_max: int
    i_max: int

    def v_clamp(self, v: float, off: float) -> int:
        return clamp(self.v_max, self.v_scale, v, off)

    def i_clamp(self, v: float, off: float) -> int:
        return clamp(self.i_max, self.i_scale, v, off)


class Model(Enum):
    """Supported devices, selected by the ID register (register 0).

    Unknown codes raise ``LookupError`` instead of being mapped onto a
    neighbouring model: the scales of adjacent IDs differ by a factor of ten,
    and a wrong scale produces plausible-looking but wrong readings and
    setpoints rather than an error.

    RD6012P is described by its 12 A range (1 mA resolution).  Its 6 A range
    (register 20 == 0) has 0.1 mA resolution and is not supported yet.
    """

    _value_: Spec

    RD6006 = Spec(
        codes=frozenset((60061, 60062)),
        v_scale=100,
        i_scale=1000,
        p_scale=100,
        v_max=60,
        i_max=6,
    )

    RD6006P = Spec(
        codes=frozenset((60065,)),
        v_scale=1000,
        i_scale=10000,
        p_scale=1000,
        v_max=60,
        i_max=6,
    )

    RD6006_MAX = Spec(
        codes=frozenset((60068,)),
        v_scale=100,
        i_scale=1000,
        p_scale=100,
        v_max=60,
        i_max=6,
    )

    RD6012 = Spec(
        codes=frozenset((60121,)),
        v_scale=100,
        i_scale=100,
        p_scale=100,
        v_max=60,
        i_max=12,
    )

    RD6012P = Spec(
        codes=frozenset((60125,)),
        v_scale=1000,
        i_scale=1000,
        p_scale=1000,
        v_max=60,
        i_max=12,
    )

    RD6012H = Spec(
        codes=frozenset((60126,)),
        v_scale=100,
        i_scale=1000,
        p_scale=100,
        v_max=60,
        i_max=12,
    )

    RD6018 = Spec(
        codes=frozenset((60181,)),
        v_scale=100,
        i_scale=100,
        p_scale=100,
        v_max=60,
        i_max=18,
    )

    RD6018P = Spec(
        codes=frozenset((60185,)),
        v_scale=1000,
        i_scale=1000,
        p_scale=1000,
        v_max=60,
        i_max=18,
    )

    RD6024 = Spec(
        codes=frozenset((60241,)),
        v_scale=100,
        i_scale=100,
        p_scale=100,
        v_max=60,
        i_max=24,
    )

    RD6030 = Spec(
        codes=frozenset((60301,)),
        v_scale=100,
        i_scale=100,
        p_scale=100,
        v_max=60,
        i_max=30,
    )

    RK6006 = Spec(
        codes=frozenset((60066,)),
        v_scale=100,
        i_scale=1000,
        p_scale=100,
        v_max=60,
        i_max=6,
    )

    RK6006H = Spec(
        codes=frozenset((60067,)),
        v_scale=100,
        i_scale=1000,
        p_scale=100,
        v_max=60,
        i_max=6,
    )

    RK6012 = Spec(
        codes=frozenset((60122,)),
        v_scale=100,
        i_scale=100,
        p_scale=100,
        v_max=60,
        i_max=12,
    )

    RK6018 = Spec(
        codes=frozenset((60182,)),
        v_scale=100,
        i_scale=100,
        p_scale=100,
        v_max=60,
        i_max=18,
    )

    RK4206H = Spec(
        codes=frozenset((42061,)),
        v_scale=100,
        i_scale=1000,
        p_scale=100,
        v_max=42,
        i_max=6,
    )

    RK8009 = Spec(
        codes=frozenset((61091,)),
        v_scale=100,
        i_scale=1000,
        p_scale=100,
        v_max=80,
        i_max=9,
    )

    @staticmethod
    def find(code: int) -> Model:
        """Return the model for an ID register value.

        An unknown code raises ``LookupError``: guessing a model would scale
        every reading and setpoint wrongly.
        """
        for model in Model:
            if code in model.value.codes:
                return model
        raise LookupError(f"unknown Riden model code: {code}")
