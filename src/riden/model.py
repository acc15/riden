from enum import Enum

from .spec import Spec, riden_spec


class Model(Enum):
    """Supported devices, selected by the ID register (register 0).

    Unknown codes raise ``LookupError`` instead of being mapped onto a
    neighbouring model: the scales of adjacent IDs differ by a factor of ten,
    and a wrong scale produces plausible-looking but wrong readings and
    setpoints rather than an error.

    Every model's register map is a :class:`riden.spec.Spec`: the ID codes it
    reports and the factory of its layout.  The map is built when the client
    connects, not here.

    RD6012P switches between a 6 A range (0.1 mA resolution) and a 12 A range
    (1 mA resolution) by register 20; every preset has its own range register,
    so its current fields depend on the selected range.
    """

    _value_: Spec

    RD6006 = Spec(
        frozenset((60061, 60062)),
        riden_spec(v_max=60, v_scale=100, i_max=6, i_scale=1000, p_scale=100),
    )

    RD6006P = Spec(
        frozenset((60065,)),
        riden_spec(v_max=60, v_scale=1000, i_max=6, i_scale=10000, p_scale=1000),
    )

    RD6006_MAX = Spec(
        frozenset((60068,)),
        riden_spec(v_max=60, v_scale=100, i_max=6, i_scale=1000, p_scale=100),
    )

    RD6012 = Spec(
        frozenset((60121,)),
        riden_spec(v_max=60, v_scale=100, i_max=12, i_scale=100, p_scale=100),
    )

    RD6012P = Spec(
        frozenset((60125,)),
        riden_spec(
            v_max=60,
            v_scale=1000,
            i_max=(6, 12),
            i_scale=(10000, 1000),
            p_scale=1000,
        ),
    )

    RD6012H = Spec(
        frozenset((60126,)),
        riden_spec(v_max=60, v_scale=100, i_max=12, i_scale=1000, p_scale=100),
    )

    RD6018 = Spec(
        frozenset((60181,)),
        riden_spec(v_max=60, v_scale=100, i_max=18, i_scale=100, p_scale=100),
    )

    RD6018P = Spec(
        frozenset((60185,)),
        riden_spec(v_max=60, v_scale=1000, i_max=18, i_scale=1000, p_scale=1000),
    )

    RD6024 = Spec(
        frozenset((60241,)),
        riden_spec(v_max=60, v_scale=100, i_max=24, i_scale=100, p_scale=100),
    )

    RD6030 = Spec(
        frozenset((60301,)),
        riden_spec(v_max=60, v_scale=100, i_max=30, i_scale=100, p_scale=100),
    )

    RK6006 = Spec(
        frozenset((60066,)),
        riden_spec(v_max=60, v_scale=100, i_max=6, i_scale=1000, p_scale=100),
    )

    RK6006H = Spec(
        frozenset((60067,)),
        riden_spec(v_max=60, v_scale=100, i_max=6, i_scale=1000, p_scale=100),
    )

    RK6012 = Spec(
        frozenset((60122,)),
        riden_spec(v_max=60, v_scale=100, i_max=12, i_scale=100, p_scale=100),
    )

    RK6018 = Spec(
        frozenset((60182,)),
        riden_spec(v_max=60, v_scale=100, i_max=18, i_scale=100, p_scale=100),
    )

    RK4206H = Spec(
        frozenset((42061,)),
        riden_spec(v_max=42, v_scale=100, i_max=6, i_scale=1000, p_scale=100),
    )

    RK8009 = Spec(
        frozenset((61091,)),
        riden_spec(v_max=80, v_scale=100, i_max=9, i_scale=1000, p_scale=100),
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
