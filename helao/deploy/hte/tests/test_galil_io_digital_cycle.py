"""``set_digital_cycle`` must work on a station with no Gamry aux line.

``out_name_gamry`` defaulted to ``"gamry_aux"`` and was typed as the dev_do
enum, which is built from the station's own config. On a station that does not
declare that output the default is not a member of its own enum, so *every*
call failed validation before reaching the driver -- whatever the caller
passed, including ``None``.

The workaround at eche10 was a ``gamry_aux: None`` config line. That is the
*string* ``"None"`` in YAML (null is ``null``/``~``/empty), so it made the enum
member exist while leaving a non-port value behind it: a caller passing a
scalar ``out_name`` would have taken the Gamry branch and emitted ``CB None``
into the DMC program.

So: the parameter is optional, a single output with no companion is accepted,
and the driver checks the port rather than the key.
"""

import pathlib

import pytest

from helao.core.error import ErrorCodes
from helao.deploy.hte.drivers.io.enum import TriggerType
from helao.deploy.hte.drivers.io.galil_io_driver import Galil
from helao.helpers.yml_tools import yml_load

CONFIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "configs"


def _driver(dev_do: dict) -> Galil:
    """A Galil bound to a config, with the controller calls captured."""
    drv = Galil(
        config={
            "galil_ip_str": "127.0.0.1",
            "dev_di": {"gamry_ttl0": 1},
            "dev_do": dev_do,
        }
    )
    drv.uploaded = []
    drv.commands = []

    async def _upload(prog):
        drv.uploaded.append(prog)

    drv.upload_DMC = _upload
    drv.galilcmd = lambda cmd: drv.commands.append(cmd)
    return drv


@pytest.mark.asyncio
async def test_a_single_output_needs_no_gamry_companion():
    drv = _driver({"doric_wled": 1})
    result = await drv.set_digital_cycle(
        trigger_name="gamry_ttl0",
        triggertype=TriggerType.fallingedge,
        out_name="doric_wled",
        toggle_init_delay=0.0,
        toggle_duty=0.5,
        toggle_period=2.0,
        toggle_duration=10.0,
        out_name_gamry=None,
    )
    assert result["error_code"] == ErrorCodes.none
    assert drv.digital_cycle_out == [1]
    assert drv.digital_cycle_out_gamry is None
    # One output, one toggle thread -- the Gamry branch would have made two.
    prog = drv.uploaded[0]
    assert prog.count("XQ #tgl") == 1, prog


@pytest.mark.asyncio
async def test_the_gamry_pair_still_works_where_the_line_exists():
    drv = _driver({"doric_wled": 1, "gamry_aux": 6})
    result = await drv.set_digital_cycle(
        trigger_name="gamry_ttl0",
        triggertype=TriggerType.fallingedge,
        out_name="doric_wled",
        toggle_init_delay=0.0,
        toggle_duty=0.5,
        toggle_period=2.0,
        toggle_duration=10.0,
        out_name_gamry="gamry_aux",
    )
    assert result["error_code"] == ErrorCodes.none
    assert drv.digital_cycle_out == 1
    assert drv.digital_cycle_out_gamry == 6


@pytest.mark.asyncio
async def test_a_non_port_gamry_value_is_refused_not_emitted():
    # What `gamry_aux: None` in a yml actually produces.
    drv = _driver({"doric_wled": 1, "gamry_aux": "None"})
    result = await drv.set_digital_cycle(
        trigger_name="gamry_ttl0",
        triggertype=TriggerType.fallingedge,
        out_name="doric_wled",
        toggle_init_delay=0.0,
        toggle_duty=0.5,
        toggle_period=2.0,
        toggle_duration=10.0,
        out_name_gamry="gamry_aux",
    )
    assert result["error_code"] == ErrorCodes.not_available
    assert drv.uploaded == [], "a non-port value reached the DMC program"


@pytest.mark.asyncio
async def test_a_list_of_outputs_is_unchanged():
    drv = _driver({"doric_wled": 1, "spec_trig": 5})
    result = await drv.set_digital_cycle(
        trigger_name="gamry_ttl0",
        triggertype=TriggerType.fallingedge,
        out_name=["doric_wled", "spec_trig"],
        toggle_init_delay=[0.0, 0.0],
        toggle_duty=[0.5, 0.5],
        toggle_period=[2.0, 2.0],
        toggle_duration=[10.0, 10.0],
        out_name_gamry=None,
    )
    assert result["error_code"] == ErrorCodes.none
    assert drv.digital_cycle_out == [1, 5]


def test_every_tracked_dev_do_port_is_an_integer():
    """A port that is not an int is a config bug the driver cannot see.

    ``gamry_aux: None`` passed every check that looked at the *key*. This looks
    at the value, across every tracked hte config at once.
    """
    findings = []
    for path in sorted(CONFIG_DIR.glob("*.yml")):
        cfg = yml_load(path)
        for server, server_cfg in (cfg.get("servers") or {}).items():
            dev_do = ((server_cfg or {}).get("params") or {}).get("dev_do") or {}
            for name, port in dev_do.items():
                if not isinstance(port, int):
                    findings.append(f"{path.name}:{server}:{name} = {port!r}")
    assert not findings, "non-integer dev_do ports:\n  " + "\n  ".join(findings)
