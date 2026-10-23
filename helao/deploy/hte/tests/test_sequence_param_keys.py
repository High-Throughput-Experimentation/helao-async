"""Static guard: sequence -> experiment param keys and experiment names.

orch_dispatch silently drops sequence-level experiment params the experiment
does not declare, so a misspelled key does nothing, and a misspelled
experiment name is a KeyError mid-run. For every hte sequence module this
checks, from the AST only (no imports, no I/O), that

* every experiment name queued with ``epm.add("<name>", ...)`` is defined as
  an ``@experiment`` function in the hte experiments library;
* every literal key of the params dict is a positional-or-keyword parameter
  of that experiment (as orch_dispatch filters), and no key is repeated.
"""

import ast
from pathlib import Path

HTE = Path(__file__).resolve().parents[1]

# Known leftovers, each (sequence module, sequence function, experiment, key).
# key "<unknown experiment>" means the experiment name itself does not exist.
# These are escalated to the owner (the fix changes station behaviour or needs
# a design choice); shrink this set, never grow it.
ALLOWED = {
    # ADSS_sub_move_to_sample takes no liquid_* params; unclear whether the
    # sequences should drop them or the experiment should gain them.
    *{
        ("ADSS_seq.py", f, "ADSS_sub_move_to_sample", k)
        for f in (
            "ADSS_CA_cell_1potential",
            "ADSS_PA_CVs_CAs_cell",
            "ADSS_PA_CVs_CAs_CVs_cell_simple",
            "ADSS_PA_CVs_testing",
            "ADSS_PA_CVs_CAs_CVs_autogasswitching",
            "ADSS_PA_CV_TRI",
            "ADSS_PA_CV_TRI_new",
            "ADSS_PA_CV_single",
        )
        for k in (
            "liquid_custom_position",
            "liquid_sample_no",
            "liquid_sample_volume_ul",
        )
    },
    # ADSS_sub_refill_syringes does not exist in any hte experiment library.
    (
        "ADSS_seq.py",
        "ADSS_CA_cell_1potential",
        "ADSS_sub_refill_syringes",
        "<unknown experiment>",
    ),
    (
        "ADSS_seq.py",
        "ADSS_PA_CVs_CAs_cell",
        "ADSS_sub_refill_syringes",
        "<unknown experiment>",
    ),
    (
        "ADSS_seq.py",
        "ADSS_CA_cell_multipotential",
        "ADSS_sub_refill_syringes",
        "<unknown experiment>",
    ),
    # CCSI sequences queue experiments that were renamed/removed
    # (CCSI_sub_liquidfill_syringes -> CCSI_sub_cellfill; full_fill_syringe gone).
    (
        "CCSI_seq.py",
        "CCSI_Solution_testing",
        "CCSI_sub_full_fill_syringe",
        "<unknown experiment>",
    ),
    (
        "CCSI_seq.py",
        "CCSI_Solution_testing_fixed_cleans",
        "CCSI_sub_liquidfill_syringes",
        "<unknown experiment>",
    ),
    (
        "CCSI_seq.py",
        "CCSI_priming",
        "CCSI_sub_liquidfill_syringes",
        "<unknown experiment>",
    ),
    (
        "CCSI_seq.py",
        "CCSI_priming",
        "CCSI_sub_full_fill_syringe",
        "<unknown experiment>",
    ),
    # CCSI key typos / dead keys whose fix would change what actually runs.
    ("CCSI_seq.py", "CCSI_initialization", "CCSI_sub_clean_inject", "initialization"),
    (
        "CCSI_seq.py",
        "CCSI_initialization",
        "CCSI_sub_clean_inject",
        "use_co2_check",
    ),  # duplicate key
    (
        "CCSI_seq.py",
        "CCSI_Solution_co2maintainconcentration",
        "CCSI_sub_n2rinse",
        "WaterFillWait_s",
    ),
    (
        "CCSI_seq.py",
        "CCSI_Solution_co2maintainconcentration",
        "CCSI_sub_n2flush",
        "drain_recirculation_duration",
    ),
    ("CCSI_seq.py", "CCSI_cleancycles", "CCSI_sub_n2rinse", "WaterFillWait_s"),
    (
        "CCSI_seq.py",
        "CCSI_cleancycles",
        "CCSI_sub_n2flush",
        "drain_recirculation_duration",
    ),
    # Other undeclared keys (owner decides: add the param or drop the key).
    ("ECHE_seq.py", "ECHE_CV_CA_CV", "ECHE_sub_startup", "reservoir_electrolyte"),
    ("ECHE_seq.py", "ECHE_CVs_CAs", "ECHE_sub_startup", "reservoir_electrolyte"),
    (
        "ECHE_seq.py",
        "ECHE_cleanCVs_regCVs_CAs",
        "ECHE_sub_startup",
        "reservoir_electrolyte",
    ),
    ("ECHE_seq.py", "ECHE_CP", "ECHE_sub_CP", "reference_electrode_type"),
    ("ECHE_seq.py", "ECHE_CP_led", "ECHE_sub_CP_led", "reference_electrode_type"),
    *{
        ("ECHEUVIS_seq.py", f, e, "reference_electrode_type")
        for f, e in (
            ("ECHEUVIS_CV_led", "ECHEUVIS_sub_CV_led"),
            ("ECHEUVIS_CA_led", "ECHEUVIS_sub_CA_led"),
            ("ECHEUVIS_CP_led", "ECHEUVIS_sub_CP_led"),
            ("ECHEUVIS_diagnostic_CV", "ECHEUVIS_sub_CA_led"),
            ("ECHEUVIS_diagnostic_CV", "ECHEUVIS_sub_CV_led"),
            ("ECHEUVIS_multiCA_led", "ECHEUVIS_sub_OCV_led"),
            ("ECHEUVIS_multiCA_led", "ECHEUVIS_sub_CA_led"),
        )
    },
    *{
        ("HISPEC_seq.py", f, "HISPEC_sub_PEIS", k)
        for f in ("HISPEC_CV", "HISPEC_EIS_only")
        for k in ("solution_ph", "ref_vs_nhe")
    },
}


def _experiment_signatures():
    """name -> list of accepted-arg sets, one per definition across libraries.

    orch_dispatch keeps only ``getfullargspec(exp).args`` (no kwonly, no
    **kwargs). Which library a sequence meets is decided by the station config,
    not the sequence module, so a name defined in more than one library is
    checked against every copy: a key must be valid in all of them.
    """
    sigs = {}
    for f in (HTE / "experiments").glob("*.py"):
        for n in ast.parse(f.read_text(encoding="utf-8")).body:
            if isinstance(n, ast.FunctionDef) and any(
                isinstance(d, ast.Call) and getattr(d.func, "id", "") == "experiment"
                for d in n.decorator_list
            ):
                sigs.setdefault(n.name, []).append({x.arg for x in n.args.args})
    return sigs


def _problems():
    sigs = _experiment_signatures()
    out = set()
    for f in sorted((HTE / "sequences").glob("*_seq.py")):
        for fn in ast.parse(f.read_text(encoding="utf-8")).body:
            if not isinstance(fn, ast.FunctionDef):
                continue
            for c in ast.walk(fn):
                if not (
                    isinstance(c, ast.Call)
                    and isinstance(c.func, ast.Attribute)
                    and c.func.attr == "add"
                    and c.args
                    and isinstance(c.args[0], ast.Constant)
                ):
                    continue
                name = c.args[0].value
                if name not in sigs:
                    out.add((f.name, fn.name, name, "<unknown experiment>"))
                    continue
                if len(c.args) > 1 and isinstance(c.args[1], ast.Dict):
                    keys = [
                        k.value for k in c.args[1].keys if isinstance(k, ast.Constant)
                    ]
                    for k in keys:
                        if any(k not in names for names in sigs[name]) or (
                            keys.count(k) > 1
                        ):
                            out.add((f.name, fn.name, name, k))
    return out


def test_sequence_experiment_names_and_param_keys():
    problems = _problems()
    new = sorted(problems - ALLOWED)
    assert not new, "undeclared experiment/param keys in sequences:\n" + "\n".join(
        map(str, new)
    )


def test_allowlist_has_no_stale_entries():
    stale = sorted(ALLOWED - _problems())
    assert not stale, f"fixed? remove from ALLOWED: {stale}"
