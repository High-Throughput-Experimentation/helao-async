from helao.framework._devtools.coverage_gate import (
    summarize,
    gate_passes,
    GATED_PREFIXES,
)


SAMPLE = {
    "files": {
        "helao/framework/domain/orchestration.py": {
            "summary": {"num_statements": 80, "covered_lines": 76}
        },
        "helao/framework/models/action.py": {
            "summary": {"num_statements": 20, "covered_lines": 20}
        },
        # adapters are not gated and must be ignored by the math:
        "helao/framework/adapters/http.py": {
            "summary": {"num_statements": 50, "covered_lines": 0}
        },
    }
}


def test_summarize_counts_only_gated_prefixes():
    covered, total = summarize(SAMPLE, GATED_PREFIXES)
    assert (covered, total) == (96, 100)


def test_gate_passes_at_or_above_threshold():
    assert gate_passes(SAMPLE, threshold=90.0, prefixes=GATED_PREFIXES) is True


def test_gate_fails_below_threshold():
    data = {
        "files": {
            "helao/framework/domain/x.py": {
                "summary": {"num_statements": 100, "covered_lines": 50}
            }
        }
    }
    assert gate_passes(data, threshold=90.0, prefixes=GATED_PREFIXES) is False


def test_empty_gated_layers_pass_vacuously():
    data = {"files": {"helao/framework/adapters/x.py": {"summary": {"num_statements": 10, "covered_lines": 0}}}}
    covered, total = summarize(data, GATED_PREFIXES)
    assert total == 0
    assert gate_passes(data, threshold=90.0, prefixes=GATED_PREFIXES) is True
