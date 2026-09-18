"""``hlo_json_dumps`` must serialize what a config actually holds.

orjson serializes subclasses of ``str``, ``int``, ``dict`` and ``list``
natively but **not** subclasses of ``float``. ``ruamel`` loads every YAML float
as ``ScalarFloat``, so from the stdlib-json-to-orjson switch (``a63e264c``,
2026-07-14) until this fix, any config value enqueued as data raised
``TypeError: Type is not JSON serializable: ScalarFloat`` inside the data
logger, which caught it and wrote ``{"error": "data was not serializable"}``
into the ``.hlo`` in place of the row.

It surfaced at eche10 on ``solid_get_builtin_specref``, whose whole output is
``world_cfg["builtin_ref_motorxy"]`` -- two floats straight out of the yml.

The fixture is a real ``ruamel`` load rather than a hand-built subclass,
because the point is the type the loader actually produces.
"""

import io

import pytest
from ruamel.yaml import YAML

from helao.helpers.to_json import hlo_json_dumps


def _yaml_load(text: str):
    return YAML().load(io.StringIO(text))


def test_ruamel_scalar_float_round_trips():
    cfg = _yaml_load(
        "builtin_ref_motorxy:\n  - 44.850974338462315\n  - -107.5622526817081\n"
    )
    value = cfg["builtin_ref_motorxy"]
    # The fixture is only meaningful if the loader still yields the subclass.
    assert type(value[0]).__name__ == "ScalarFloat"
    assert (
        hlo_json_dumps({"_refxy": value})
        == '{"_refxy":[44.850974338462315,-107.5622526817081]}'
    )


def test_nested_config_mapping_round_trips():
    cfg = _yaml_load("axes:\n  x:\n    scale: 1.5\n    counts: 3\n    name: xaxis\n")
    assert (
        hlo_json_dumps(cfg) == '{"axes":{"x":{"scale":1.5,"counts":3,"name":"xaxis"}}}'
    )


def test_non_finite_still_becomes_null():
    assert hlo_json_dumps({"v": float("nan")}) == '{"v":null}'
    assert hlo_json_dumps({"v": float("inf")}) == '{"v":null}'


def test_an_unserializable_object_still_raises():
    # The coercion is deliberately narrow: a wrong object must not be
    # stringified into something that reads like a measurement.
    class Thing:
        pass

    with pytest.raises(TypeError, match="Thing"):
        hlo_json_dumps({"v": Thing()})
