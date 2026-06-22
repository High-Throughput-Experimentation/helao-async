from pathlib import Path

from helao.framework._devtools.boundary_check import (
    find_forbidden_imports,
    DOMAIN_FORBIDDEN,
    scan_dir,
)


def test_clean_source_has_no_violations():
    src = "import math\nfrom helao.framework.models import action\nfrom helao.framework.ports.clock import Clock\n"
    assert find_forbidden_imports(src, DOMAIN_FORBIDDEN) == []


def test_plain_import_of_forbidden_module_is_flagged():
    assert find_forbidden_imports("import httpx\n", DOMAIN_FORBIDDEN) == ["httpx"]


def test_from_import_of_forbidden_module_is_flagged():
    assert find_forbidden_imports("from fastapi import FastAPI\n", DOMAIN_FORBIDDEN) == ["fastapi"]


def test_submodule_of_forbidden_prefix_is_flagged():
    found = find_forbidden_imports("from helao.framework.adapters.fakes import x\n", DOMAIN_FORBIDDEN)
    assert found == ["helao.framework.adapters.fakes"]


def test_substring_lookalike_is_not_flagged():
    # 'osmosis' must not trip an 'os' rule; matching is on dotted boundaries.
    assert find_forbidden_imports("import osmosis\n", {"os"}) == []


def test_real_domain_package_is_clean():
    domain_dir = Path("helao/framework/domain")
    violations = scan_dir(domain_dir, DOMAIN_FORBIDDEN)
    assert violations == {}, f"domain/ has forbidden imports: {violations}"
