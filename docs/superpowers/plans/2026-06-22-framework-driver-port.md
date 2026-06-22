# Framework Driver Contract Port (Sub-project 3)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development / executing-plans. Checkbox steps.

**Goal:** Port the `HelaoDriver` ABC and friends into `helao/framework/ports/driver.py` near-verbatim — it is already a clean abstraction (parent spec §4.6).

**Architecture:** The driver contract is the `ports/` seam action servers use to talk to hardware. Lives in `ports/`. May import `support/` + `models/`; never adapters/app/domain/web.

**Tech Stack:** Python 3.12 (helao conda env), stdlib abc/dataclasses/enum, pytest.

---

## Conventions

- **helao conda env only:** prefix commands with `conda run -n helao`. Ignore cosmetic `ERROR conda.cli.main_run` line.
- **Branch:** `feat/framework-scaffold` (all sub-projects stack here). Confirm `git branch --show-current`. Never commit to `unstable`/`main`.
- **No private-deployment names.**
- Source of truth for content: `helao/core/drivers/helao_driver.py` (231 lines). Port faithfully, only repoint imports.

---

## Task 1: Port the driver contract

**Files:**
- Create: `helao/framework/ports/driver.py` (from `helao/core/drivers/helao_driver.py`)
- Test: `helao/framework/tests/test_ports_driver.py`

- [ ] **Step 1:** Read `helao/core/drivers/helao_driver.py` and `helao/core/tests/unit_test_helao_driver.py`.

- [ ] **Step 2: Write failing tests** in `test_ports_driver.py` (port assertions from unit_test_helao_driver.py): 
  - `DriverStatus` and `DriverResponseType` enums expose their expected members and compare equal to their string values.
  - `DriverResponse` constructs with defaults; `__post_init__` sets a timestamp; `timestamp_str` formats it; the dataclass round-trips its fields.
  - A minimal concrete `HelaoDriver` subclass implementing the 5 abstract methods (`connect`/`get_status`/`stop`/`reset`/`disconnect`) instantiates; instantiating the ABC directly raises `TypeError`; `_created_at`/`_uptime` return strings.
  - `DriverPoller` constructs with a fake driver; `get_data` returns a `DriverResponse`; start/stop polling toggles its task without real hardware (use a dummy driver whose `get_status` returns a canned `DriverResponse`).
  Run: `conda run -n helao python -m pytest helao/framework/tests/test_ports_driver.py` → FAIL (module missing).

- [ ] **Step 3: Port** `helao/core/drivers/helao_driver.py` → `helao/framework/ports/driver.py`. The ONLY change from source: repoint `from helao.helpers import helao_logging as logging` → `from helao.framework.support import helao_logging as logging`. Keep all class/enum/method names, signatures, defaults, and docstrings identical.

- [ ] **Step 4:** Run tests → PASS. Run `conda run -n helao python run_framework_tests.py` → suite + gate green. Run the AST boundary test (`ports/` is not domain, but confirm nothing broke).

- [ ] **Step 5: Commit** `git commit -m "feat(framework): port HelaoDriver contract into ports/driver.py"`

---

## Task 2: Verification

- [ ] **Step 1:** `conda run -n helao python run_framework_tests.py` → all pass, gate PASS.
- [ ] **Step 2:** Purity — `grep -rE "from helao\.(core|helpers)" helao/framework/ports/` is empty.
- [ ] **Step 3:** `grep -nE "import" helao/framework/ports/driver.py` shows only stdlib + `helao.framework.support.helao_logging`.
- [ ] **Step 4:** No private-deployment names in the diff.
- [ ] **Step 5:** `git log --oneline unstable..HEAD` shows the driver commit stacked.

---

## Self-review notes

- Delivers parent spec §4.6 (HelaoDriver/DriverPoller/DriverResponse/DriverStatus near-verbatim into `ports/`).
- Single import change vs source; no behavior change. ABC + dataclass + enums, fully testable with a dummy driver (no hardware).
- All commands `conda run -n helao`. No private-deployment names.
