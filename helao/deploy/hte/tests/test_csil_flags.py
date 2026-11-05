"""CSIL_exp default-off flags ported from the retired CCSI library.

Flags: ``secondliquid_when_both_empty`` (cellfill) and
``secondary_prerinse_cycles`` (n2rinse). Off must equal not passing the flag.
"""

from typing import Any, Callable

from helao.deploy.hte.experiments import CSIL_exp
from helao.helpers.premodels import Experiment

MASK = ("uuid", "timestamp", "time")


def _run(fn: Callable[..., Any], **kw) -> Any:
    # @experiment functions take the Experiment as their first argument
    return fn(Experiment(experiment_name=fn.__name__, experiment_params={}), **kw)


def _plan(fn, **kw):
    out = []
    for a in _run(fn, **kw):
        d = a.model_dump(mode="json")
        out.append({k: v for k, v in d.items() if not any(m in k for m in MASK)})
    return out


def _key_actions(acts, server, name):
    return [
        a
        for a in acts
        if a.action_server.server_name == server and a.action_name == name
    ]


def test_cellfill_second_liquid_when_both_empty():
    kw = dict(Solution_volume_ul=0, Clean_volume_ul=0, n2_push=True)
    off = _run(CSIL_exp.CCSI_sub_cellfill, **kw)
    on = _run(CSIL_exp.CCSI_sub_cellfill, secondliquid_when_both_empty=True, **kw)
    assert not _key_actions(off, "CLEANSYRINGE", "infuse")
    assert not _key_actions(off, "WATERSYRINGE", "infuse")
    inj = [
        a
        for a in on
        if a.action_name == "infuse"
        and a.action_params["volume_uL"] == 50
        and a.action_params["rate_uL_sec"] == 10
    ]
    assert len(inj) == 1
    n2 = [
        a.action_params["on"]
        for a in _key_actions(on, "NI", "gasvalve")
        if a.action_params["gasvalve"] == "10-n2push"
    ]
    assert n2 == [1, 0]
    # a non-empty fill is unaffected by the flag
    kw = dict(Solution_volume_ul=500, Clean_volume_ul=0)
    assert _plan(CSIL_exp.CCSI_sub_cellfill, **kw) == _plan(
        CSIL_exp.CCSI_sub_cellfill, secondliquid_when_both_empty=True, **kw
    )
    # flag off is the same plan as not passing it
    for kw in (dict(Solution_volume_ul=0, Clean_volume_ul=0), dict(n2_push=True)):
        assert _plan(CSIL_exp.CCSI_sub_cellfill, **kw) == _plan(
            CSIL_exp.CCSI_sub_cellfill, secondliquid_when_both_empty=False, **kw
        )


def _loads(acts):
    return [
        a.action_params["source_liquid_in"]["sample_no"]
        for a in acts
        if a.action_name == "archive_custom_add_liquid"
    ]


def test_n2rinse_secondary_prerinse():
    base = _run(CSIL_exp.CCSI_sub_n2rinse, rinse_cycles=1)
    pre = _run(
        CSIL_exp.CCSI_sub_n2rinse,
        rinse_cycles=1,
        secondary_prerinse_cycles=2,
        secondliquid_sample_no=468,
        secondliquid_volume=5000,
    )
    assert len(pre) > len(base)
    # the pre-rinse cycles come first and are strictly additive
    assert [a.action_name for a in pre[len(pre) - len(base) :]] == [
        a.action_name for a in base
    ]
    inj = [
        a
        for a in pre
        if a.action_name == "infuse" and a.action_params["volume_uL"] == 5000
    ]
    assert len(inj) == 2
    assert _loads(pre).count(468) >= 2 and 468 not in _loads(base)
    drains = lambda acts: len(_key_actions(acts, "SAMPLE", "archive_custom_unloadall"))
    assert drains(pre) == drains(base) + 2


def test_n2rinse_prerinse_off_is_default():
    assert _plan(CSIL_exp.CCSI_sub_n2rinse, rinse_cycles=1) == _plan(
        CSIL_exp.CCSI_sub_n2rinse, rinse_cycles=1, secondary_prerinse_cycles=0
    )
