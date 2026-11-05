"""Every experiment a published hte sequence queues is a published experiment.

Plans each SEQUENCES entry at its defaults and once per bool param flipped
(refill=True once queued a nonexistent ADSS_sub_refill_syringes, invisible at
defaults). Complements the AST-only test_sequence_param_keys, which cannot see
branches whose names are not literals.

A second check runs per station config: the sequences of its sequence_libraries
may only queue experiments in that config's experiment_libraries, and each
experiment's actions may only target servers that config launches.
"""

import importlib
import inspect
import pkgutil

from pathlib import Path

import pytest

from helao.deploy.hte import experiments, sequences
from helao.helpers.config_loader import read_config
from helao.helpers.premodels import Experiment

# Disabled together with the TEC server (5c006b38); shrink-only. Re-publish an
# entry in EXPERIMENTS and delete it here (test_tec_disabled_has_no_stale_entries).
TEC_DISABLED = {
    "ANEC_sub_HeatCA",
    "ANEC_sub_HeatCV",
    "ANEC_sub_heatoff",
    "ANEC_sub_setheat",
}


def _mods(pkg):
    return [
        importlib.import_module(f"{pkg.__name__}.{m.name}")
        for m in pkgutil.iter_modules(pkg.__path__)
    ]


PUBLISHED = {n for m in _mods(experiments) for n in getattr(m, "EXPERIMENTS", [])}
CASES = [
    (m.__name__.rsplit(".", 1)[1], n, flip)
    for m in _mods(sequences)
    for n in getattr(m, "SEQUENCES", [])
    for flip in [None]
    + [
        p.name
        for p in inspect.signature(getattr(m, n)).parameters.values()
        if isinstance(p.default, bool)
    ]
]


@pytest.mark.parametrize("mod,seq,flip", CASES, ids=lambda v: str(v))
def test_queued_experiments_are_published(mod, seq, flip):
    fn = getattr(importlib.import_module(f"{sequences.__name__}.{mod}"), seq)
    kw = (
        {}
        if flip is None
        else {flip: not inspect.signature(fn).parameters[flip].default}
    )
    names = {e.experiment_name for e in fn(**kw)}
    assert names <= PUBLISHED | TEC_DISABLED, sorted(names - PUBLISHED - TEC_DISABLED)


def test_tec_disabled_has_no_stale_entries():
    assert not TEC_DISABLED & PUBLISHED, sorted(TEC_DISABLED & PUBLISHED)


# Known config gaps: published sequences that queue a server the config does not
# launch. anec: heat experiments, not runnable until the TEC server returns.
# eche10/hispec: CALC/ANA analysis steps whose servers those configs don't define.
# Shrink-only: stale entries fail test_config_gap_allowlist_has_no_stale_entries.
KNOWN_CONFIG_GAPS = {
    "anec": {
        "ANEC_ferricyanide_protocol",
        "ANEC_ferricyanide_simpleprotocol",
        "ANEC_heatOCV",
        "ANEC_repeat_HeatCA",
        "ANEC_repeat_TentHeatCA",
        "ANEC_repeat_TentHeatCAgasonly",
    },
    "eche10": {
        "ECHEUVIS_CA_led",
        "ECHEUVIS_CP_led",
        "ECHEUVIS_CV_led",
        "ECHEUVIS_postseq",
        "UVIS_T_postseq",
    },
    "hispec": {"ECHEUVIS_postseq"},
}
CONFIGS = sorted(
    p.stem
    for p in (Path(experiments.__path__[0]).parent / "configs").glob("*.yml")
    if "sequence_libraries" in read_config(p.stem)
)


def _config_problems(prefix):
    """{sequence: {problem}} for one config; problems name a missing experiment or server."""
    cfg = read_config(prefix)
    servers = set(cfg["servers"])
    exps = {}
    for lib in cfg.get("experiment_libraries", []):
        if "\\" in lib:  # test-deployment file path, not an hte module
            continue
        m = importlib.import_module(f"{experiments.__name__}.{lib}")
        exps.update({n: getattr(m, n) for n in m.EXPERIMENTS})
    bad = {}
    for lib in cfg["sequence_libraries"]:
        if "\\" in lib:
            continue
        m = importlib.import_module(f"{sequences.__name__}.{lib}")
        for sn in m.SEQUENCES:
            fn = getattr(m, sn)
            params = inspect.signature(fn).parameters
            for flip in [None] + [
                k for k, v in params.items() if isinstance(v.default, bool)
            ]:
                kw = {} if flip is None else {flip: not params[flip].default}
                for em in fn(**kw):
                    f = exps.get(em.experiment_name)
                    if f is None:
                        bad.setdefault(sn, set()).add(
                            f"unpublished:{em.experiment_name}"
                        )
                        continue
                    args = inspect.getfullargspec(f).args
                    exp = Experiment(
                        experiment_name=em.experiment_name,
                        experiment_params=em.experiment_params,
                    )
                    for a in (
                        f(
                            exp,
                            **{
                                k: v
                                for k, v in em.experiment_params.items()
                                if k in args
                            },
                        )
                        or []
                    ):
                        if a.action_server.server_name not in servers:
                            bad.setdefault(sn, set()).add(
                                f"{em.experiment_name}->{a.action_server.server_name}"
                            )
    return bad


@pytest.mark.parametrize("prefix", CONFIGS)
def test_config_sequences_resolve_to_launched_servers(prefix):
    bad = _config_problems(prefix)
    for sn in KNOWN_CONFIG_GAPS.get(prefix, ()):
        bad.pop(sn, None)
    assert not bad, {k: sorted(v) for k, v in bad.items()}


@pytest.mark.parametrize("prefix", sorted(KNOWN_CONFIG_GAPS))
def test_config_gap_allowlist_has_no_stale_entries(prefix):
    assert KNOWN_CONFIG_GAPS[prefix] <= set(_config_problems(prefix))
