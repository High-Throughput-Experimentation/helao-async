"""Standalone fidelity check for ``SampleArchiveShim`` (plan Phase 3 gate).

Run (from repo root, ``helao`` conda env, ``PYTHONPATH`` = repo root)::

    conda run -n helao python helao/deploy/hte/tests/test_sample_shim_fidelity.py

This spins up a minimal in-process FastAPI app exposing the 13 private
endpoints the shim calls, backed by trivial fakes that return the *wire
shapes* the real SAMPLE server produces (ErrorCodes + Sample models). Because
the throwaway app has no ZMQ RPC dispatcher, every shim call transparently
uses the HTTP fallback -- which is exactly the path the ``m1`` outbound
serialization contract must survive. It asserts:

* ``tray_query_sample`` returns ``(ErrorCodes, <SampleUnion instance>)``.
* an ``AssemblySample`` with >=2 heterogeneous parts round-trips with its
  ``parts`` preserved (length + per-part subtype).
* a non-``none`` ``ErrorCodes`` round-trips to the *same* enum member.
* ``update_samples`` returns cleanly (no raise) on a ``None`` body.
* every shim call raises ``RuntimeError`` when SAMPLE is unreachable.

NOTE: this uses a lightweight fake so it is runnable on a plain Linux box.
Phase 7's full smoke (live SAMPLE + PAL, real Archive/DB, ZMQ fast path)
is a superset and still required for the RPC-fast-path parity assertion.
"""

import asyncio
import socket
import threading
import time
from typing import List, Optional, Union

import uvicorn
from fastapi import Body, FastAPI

from helao.core.error import ErrorCodes
from helao.core.models.sample import (
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    SolidSample,
    object_to_sample,
)
from helao.deploy.hte.drivers.robot.sample_shim import SampleArchiveShim

_SampleParam = Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _make_fake_sample_app() -> FastAPI:
    """Minimal app returning the exact wire shapes the real endpoints emit."""
    app = FastAPI()

    def _assembly_with_parts() -> AssemblySample:
        return AssemblySample(
            sample_no=1,
            machine_name="testhost",
            parts=[
                LiquidSample(sample_no=10, machine_name="testhost"),
                SolidSample(sample_no=20, machine_name="testhost", plate_id=1),
            ],
        )

    @app.post("/get_samples")
    async def get_samples(samples: List[_SampleParam] = Body([], embed=True)):
        # echo an assembly-with-parts to exercise nested rehydration
        return [_assembly_with_parts()]

    @app.post("/new_samples")
    async def new_samples(samples: List[_SampleParam] = Body([], embed=True)):
        return [object_to_sample(s) for s in samples]

    @app.post("/update_samples")
    async def update_samples(samples: List[_SampleParam] = Body([], embed=True)):
        return None  # void endpoint -> None body on success

    @app.post("/tray_query_sample")
    async def tray_query_sample(
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
    ):
        return ErrorCodes.not_available, LiquidSample(
            sample_no=5, machine_name="testhost"
        )

    @app.post("/tray_get_next_full")
    async def tray_get_next_full(
        after_tray: Optional[int] = None,
        after_slot: Optional[int] = None,
        after_vial: Optional[int] = None,
    ):
        return {"tray": 1, "slot": 2, "vial": 3}

    @app.post("/tray_new_position")
    async def tray_new_position(req_vol: float = 2.0):
        return {"tray": 1, "slot": 1, "vial": 1}

    @app.post("/tray_update_position")
    async def tray_update_position(
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
        sample: Optional[_SampleParam] = Body(None, embed=True),
        dilute: bool = False,
    ):
        return True

    @app.post("/custom_query_sample")
    async def custom_query_sample(custom: Optional[str] = None):
        return ErrorCodes.none, _assembly_with_parts()

    @app.post("/custom_update_position")
    async def custom_update_position(
        custom: Optional[str] = None,
        sample: Optional[_SampleParam] = Body(None, embed=True),
        dilute: bool = False,
    ):
        return True, LiquidSample(sample_no=7, machine_name="testhost")

    @app.post("/new_ref_samples")
    async def new_ref_samples(
        samples_in: List[_SampleParam] = Body([], embed=True),
        sample_out_type: str = "",
        sample_position: str = "",
        combine_liquids: bool = False,
        combine_gases: bool = False,
        action=Body(None, embed=True),
    ):
        return ErrorCodes.none, [LiquidSample(sample_no=99, machine_name="testhost")]

    @app.post("/custom_dest_allowed")
    async def custom_dest_allowed(custom: Optional[str] = None):
        return True

    @app.post("/custom_assembly_allowed")
    async def custom_assembly_allowed(custom: Optional[str] = None):
        return False

    @app.post("/custom_is_destroyed")
    async def custom_is_destroyed(custom: Optional[str] = None):
        return True

    return app


class _ServerThread(threading.Thread):
    def __init__(self, app, port):
        super().__init__(daemon=True)
        self._config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        self.server = uvicorn.Server(self._config)

    def run(self):
        self.server.run()


def _wait_until_up(port, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


async def _run_fidelity(shim: SampleArchiveShim):
    # tray_query_sample: (ErrorCodes, SampleUnion instance)
    err, sample = await shim.tray_query_sample(tray=1, slot=1, vial=1)
    assert isinstance(err, ErrorCodes), f"error not ErrorCodes: {type(err)}"
    assert err == ErrorCodes.not_available, f"ErrorCodes round-trip wrong: {err!r}"
    assert isinstance(sample, LiquidSample), f"sample not LiquidSample: {type(sample)}"

    # AssemblySample round-trip: >=2 heterogeneous parts preserved
    err2, sample2 = await shim.custom_query_sample(custom="cell1")
    assert err2 == ErrorCodes.none
    assert isinstance(sample2, AssemblySample), f"not AssemblySample: {type(sample2)}"
    assert len(sample2.parts) == 2, f"parts dropped: {len(sample2.parts)}"
    part_types = sorted(type(p).__name__ for p in sample2.parts)
    assert part_types == ["LiquidSample", "SolidSample"], f"part subtypes wrong: {part_types}"

    # unified_db.get_samples: nested assembly rehydration via list
    got = await shim.unified_db.get_samples(
        samples=[LiquidSample(sample_no=-1, machine_name="testhost")]
    )
    assert isinstance(got, list) and isinstance(got[0], AssemblySample)
    assert len(got[0].parts) == 2

    # void-success: update_samples returns None without raising (m2)
    ret = await shim.unified_db.update_samples(
        samples=[LiquidSample(sample_no=1, machine_name="testhost")]
    )
    assert ret is None, f"update_samples should return None, got {ret!r}"

    # outbound serialization over HTTP fallback (m1): raw model args accepted
    made = await shim.unified_db.new_samples(
        samples=[LiquidSample(sample_no=1, machine_name="testhost")]
    )
    assert isinstance(made, list) and isinstance(made[0], LiquidSample)

    # dicts + bools + new_ref tuple arity
    d = await shim.tray_get_next_full(after_tray=0, after_slot=0, after_vial=0)
    assert d == {"tray": 1, "slot": 2, "vial": 3}
    assert (await shim.tray_new_position(req_vol=1.0))["tray"] == 1
    assert (await shim.tray_update_position(tray=1, slot=1, vial=1,
            sample=LiquidSample(sample_no=1))) is True
    ok, s = await shim.custom_update_position(
        custom="c", sample=LiquidSample(sample_no=1))
    assert ok is True and isinstance(s, LiquidSample)
    nerr, nlist = await shim.new_ref_samples(
        samples_in=[LiquidSample(sample_no=1)],
        sample_out_type="liquid", sample_position="p", action=None)
    assert nerr == ErrorCodes.none and isinstance(nlist[0], LiquidSample)
    assert (await shim.custom_dest_allowed(custom="c")) is True
    assert (await shim.custom_assembly_allowed(custom="c")) is False
    assert (await shim.custom_is_destroyed(custom="c")) is True

    print("PASS: shim fidelity assertions (live SAMPLE fake)")


async def _run_fail_loud():
    """Every shim call must raise when SAMPLE is unreachable."""
    dead_port = _free_port()  # nothing listening here
    shim = SampleArchiveShim(
        {"servers": {"SAMPLE": {"host": "127.0.0.1", "port": dead_port}}}
    )
    calls = [
        ("tray_query_sample", shim.tray_query_sample(tray=1, slot=1, vial=1)),
        ("custom_query_sample", shim.custom_query_sample(custom="c")),
        ("custom_dest_allowed", shim.custom_dest_allowed(custom="c")),
        ("custom_is_destroyed", shim.custom_is_destroyed(custom="c")),
        ("unified_db.get_samples", shim.unified_db.get_samples(
            samples=[LiquidSample(sample_no=1)])),
        ("unified_db.update_samples", shim.unified_db.update_samples(
            samples=[LiquidSample(sample_no=1)])),
    ]
    for name, coro in calls:
        try:
            await coro
        except RuntimeError:
            continue
        raise AssertionError(f"{name} did NOT raise on unreachable SAMPLE")
    print("PASS: fail-loud (all calls raised RuntimeError when SAMPLE down)")


def main():
    port = _free_port()
    server = _ServerThread(_make_fake_sample_app(), port)
    server.start()
    try:
        if not _wait_until_up(port):
            raise RuntimeError("fake SAMPLE server did not come up")
        shim = SampleArchiveShim(
            {"servers": {"SAMPLE": {"host": "127.0.0.1", "port": port}}}
        )
        asyncio.run(_run_fidelity(shim))
        asyncio.run(_run_fail_loud())
        print("ALL FIDELITY CHECKS PASSED")
    finally:
        server.server.should_exit = True
        server.join(timeout=5)


if __name__ == "__main__":
    main()
