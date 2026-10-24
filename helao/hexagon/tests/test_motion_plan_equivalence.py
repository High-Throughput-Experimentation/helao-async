"""``plan_move_target`` against the two pre-extraction planners.

The reference functions below are the frame/mode blocks of the Galil
(``galil_motion_native._motor_move_unguarded``) and Thorlabs
(``thorlabs_kinesis._motor_move_body``) drivers as they stood before the
planner moved into ``motion_transform.py``, trimmed to just that block. Both
must match the shared planner on every mode x frame x request in the grid; the
Thorlabs reference also pins the trace log lines.

One intended divergence is not modelled: the old Thorlabs platexy branch ended
with a dead ``xyvec`` loop that indexed ``d_mm[0]``/``d_mm[1]``, so a platexy
request with fewer than two distances (e.g. homing ``['y']``) raised
``IndexError`` and nothing moved. The shared planner homes like Galil always
did (accepted as a bug fix); ``test_thorlabs_platexy_homing_single_axis_now_plans``
pins it.
"""

import itertools
from copy import deepcopy

import numpy as np
import pytest

from helao.deploy.hte.drivers.motion.enum import MoveModes, TransformationModes
from helao.hexagon.domain.motion_transform import TransformXY, plan_move_target


def _old_galil_plan(tf, tmpmotorpos, axis, d_mm, mode, transformation):
    current_positionvec = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    req_positionvec = [None, None, None, None, None, None]
    reqdict = dict(zip(axis, d_mm))
    for idx, ax in enumerate(["x", "y", "z", "Rx", "Ry", "Rz"]):
        if ax in tmpmotorpos["ax"]:
            current_positionvec[idx] = tmpmotorpos["position"][
                tmpmotorpos["ax"].index(ax)
            ]
            if ax in reqdict:
                req_positionvec[idx] = reqdict[ax]

    if transformation == TransformationModes.motorxy:
        pass
    elif transformation == TransformationModes.platexy:
        motorxy: list = [0.0, 0.0, 1.0]
        motorxy[0] = current_positionvec[0]
        motorxy[1] = current_positionvec[1]
        current_platexy = tf.transform_motorxy_to_platexy(motorxy)
        if mode == MoveModes.relative:
            new_platexy: list = [0.0, 0.0, 1.0]
            if req_positionvec[0] is not None:
                new_platexy[0] = current_platexy[0] + req_positionvec[0]
            else:
                new_platexy[0] = current_platexy[0]
            if req_positionvec[1] is not None:
                new_platexy[1] = current_platexy[1] + req_positionvec[1]
            else:
                new_platexy[1] = current_platexy[1]
            new_motorxy = tf.transform_platexy_to_motorxy(new_platexy)
            axis = ["x", "y"]
            d_mm = [d for d in new_motorxy[0:2]]
            mode = MoveModes.absolute
        elif mode == MoveModes.absolute:
            new_platexy: list = [0.0, 0.0, 1.0]
            if req_positionvec[0] is not None:
                new_platexy[0] = req_positionvec[0]
            else:
                new_platexy[0] = current_platexy[0]
            if req_positionvec[1] is not None:
                new_platexy[1] = req_positionvec[1]
            else:
                new_platexy[1] = current_platexy[1]
            new_motorxy = tf.transform_platexy_to_motorxy(new_platexy)
            axis = ["x", "y"]
            d_mm = [d for d in new_motorxy[0:2]]
        elif mode == MoveModes.homing:
            pass
    elif transformation == TransformationModes.instrxy:
        current_instrxyz = tf.transform_motorxyz_to_instrxyz(current_positionvec[0:3])
        if mode == MoveModes.relative:
            new_instrxyz = current_instrxyz
            for i in range(3):
                if req_positionvec[i] is not None:
                    new_instrxyz[i] = new_instrxyz[i] + req_positionvec[i]
            new_motorxyz = tf.transform_instrxyz_to_motorxyz(new_instrxyz[0:3])
            axis = ["x", "y", "z"]
            d_mm = [d for d in new_motorxyz[0:3]]
            mode = MoveModes.absolute
        elif mode == MoveModes.absolute:
            new_instrxyz = current_instrxyz
            for i in range(3):
                if req_positionvec[i] is not None:
                    new_instrxyz[i] = req_positionvec[i]
            new_motorxyz = tf.transform_instrxyz_to_motorxyz(new_instrxyz[0:3])
            axis = ["x", "y", "z"]
            d_mm = [d for d in new_motorxyz[0:3]]
        elif mode == MoveModes.homing:
            pass
    return axis, d_mm, mode


def _old_thorlabs_plan(tf, tmpmotorpos, axis, d_mm, mode, transformation, log):
    current_positionvec = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    req_positionvec = [None, None, None, None, None, None]
    reqdict = dict(zip(axis, d_mm))
    log(f"requested position ({mode}): {reqdict}")
    for idx, ax in enumerate(["x", "y", "z", "Rx", "Ry", "Rz"]):
        if ax in tmpmotorpos["ax"]:
            current_positionvec[idx] = tmpmotorpos["position"][
                tmpmotorpos["ax"].index(ax)
            ]
            if ax in reqdict:
                req_positionvec[idx] = reqdict[ax]
    log(f"motor position vector: {current_positionvec[0:3]}")
    log(f"requested position vector ({mode}) {req_positionvec}")

    if transformation == TransformationModes.motorxy:
        log(f"motion: got motorxy ({mode}), no transformation necessary")
    elif transformation == TransformationModes.platexy:
        log(f"motion: got platexy ({mode}), converting to motorxy")
        motorxy: list = [0, 0, 1]
        motorxy[0] = current_positionvec[0]
        motorxy[1] = current_positionvec[1]
        current_platexy = tf.transform_motorxy_to_platexy(motorxy)
        log(f"current plate position (calc from motor): {current_platexy}")
        if mode == MoveModes.relative:
            new_platexy: list = [0, 0, 1]
            if req_positionvec[0] is not None:
                new_platexy[0] = current_platexy[0] + req_positionvec[0]
            else:
                new_platexy[0] = current_platexy[0]
            if req_positionvec[1] is not None:
                new_platexy[1] = current_platexy[1] + req_positionvec[1]
            else:
                new_platexy[1] = current_platexy[1]
            log(f"new platexy (abs): {new_platexy}")
            new_motorxy = tf.transform_platexy_to_motorxy(new_platexy)
            log(f"new motorxy (abs): {new_motorxy}")
            axis = ["x", "y"]
            d_mm = [d for d in new_motorxy[0:2]]
            mode = MoveModes.absolute
        elif mode == MoveModes.absolute:
            new_platexy: list = [0, 0, 1]
            if req_positionvec[0] is not None:
                new_platexy[0] = req_positionvec[0]
            else:
                new_platexy[0] = current_platexy[0]
            if req_positionvec[1] is not None:
                new_platexy[1] = req_positionvec[1]
            else:
                new_platexy[1] = current_platexy[1]
            log(f"new platexy (abs): {new_platexy}")
            new_motorxy = tf.transform_platexy_to_motorxy(new_platexy)
            log(f"new motorxy (abs): {new_motorxy}")
            axis = ["x", "y"]
            d_mm = [d for d in new_motorxy[0:2]]
        elif mode == MoveModes.homing:
            pass
    elif transformation == TransformationModes.instrxy:
        log(f"mode: {mode}")
        log(f"motion: got instrxyz ({mode}), converting to motorxy")
        current_instrxyz = tf.transform_motorxyz_to_instrxyz(current_positionvec[0:3])
        log(f"current instrument position (calc from motor): {current_instrxyz}")
        if mode == MoveModes.relative:
            new_instrxyz = current_instrxyz
            for i in range(3):
                if req_positionvec[i] is not None:
                    new_instrxyz[i] = new_instrxyz[i] + req_positionvec[i]
                else:
                    new_instrxyz[i] = new_instrxyz[i]
            log(f"new instrument position (abs): {new_instrxyz}")
            new_motorxyz = tf.transform_instrxyz_to_motorxyz(new_instrxyz[0:3])
            log(f"new motor position (abs): {new_motorxyz}")
            axis = ["x", "y", "z"]
            d_mm = [d for d in new_motorxyz[0:3]]
            mode = MoveModes.absolute
        elif mode == MoveModes.absolute:
            new_instrxyz = current_instrxyz
            for i in range(3):
                if req_positionvec[i] is not None:
                    new_instrxyz[i] = req_positionvec[i]
                else:
                    new_instrxyz[i] = new_instrxyz[i]
            log(f"new instrument position (abs): {new_instrxyz}")
            new_motorxyz = tf.transform_instrxyz_to_motorxyz(new_instrxyz[0:3])
            log(f"new motor position (abs): {new_motorxyz}")
            axis = ["x", "y", "z"]
            d_mm = [d for d in new_motorxyz[0:3]]
        elif mode == MoveModes.homing:
            pass
    return axis, d_mm, mode


def _transform():
    minstr = [
        [1.0, 0.05, 0.0, 11.5],
        [-0.04, 0.98, 0.0, -7.25],
        [0.0, 0.0, 1.0, 3.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    tf = TransformXY(minstr, ["x", "y", "z"])
    tf.update_Mplatexy([[0.99, -0.02, 4.5], [0.02, 0.99, -2.5], [0, 0, 1]])
    return tf


POSITIONS = [
    {"ax": ["x", "y", "z"], "position": [10.25, -3.5, 7.0]},
    {"ax": ["x", "y"], "position": [0.0, 0.0]},
    {"ax": ["z", "y", "x"], "position": [1.0, 2.0, 3.0]},
]
REQUESTS = [
    (["x", "y"], [1.5, -2.0]),
    (["x"], [4.0]),
    (["y"], [-6.5]),
    (["z"], [2.0]),
    (["x", "y", "z"], [1.0, 2.0, 3.0]),
    (["y", "x"], [0.5, 0.25]),
    (["q"], [9.0]),
]


@pytest.mark.parametrize(
    "transformation,mode,pos,req",
    list(
        itertools.product(
            TransformationModes, MoveModes, range(len(POSITIONS)), range(len(REQUESTS))
        )
    ),
)
def test_planner_matches_both_old_planners(transformation, mode, pos, req):
    axis, d_mm = REQUESTS[req]
    tmp = POSITIONS[pos]

    g_axis, g_d, g_mode = _old_galil_plan(
        _transform(), tmp, list(axis), list(d_mm), mode, transformation
    )
    old_logs: list = []
    t_axis, t_d, t_mode = _old_thorlabs_plan(
        _transform(), tmp, list(axis), list(d_mm), mode, transformation, old_logs.append
    )
    new_logs: list = []
    n_axis, n_d, rebased = plan_move_target(
        _transform(),
        tmp,
        list(axis),
        list(d_mm),
        mode,
        transformation,
        new_logs.append,
    )
    n_mode = MoveModes.absolute if rebased else mode

    for o_axis, o_d, o_mode in ((g_axis, g_d, g_mode), (t_axis, t_d, t_mode)):
        assert n_axis == o_axis
        assert n_mode == o_mode and type(n_mode) is type(o_mode)
        assert len(n_d) == len(o_d)
        np.testing.assert_array_equal(np.asarray(n_d, float), np.asarray(o_d, float))
    assert new_logs == old_logs


def test_planner_without_log_still_plans():
    axis, d_mm, rebased = plan_move_target(
        _transform(),
        POSITIONS[0],
        ["x", "y"],
        [1.0, 2.0],
        MoveModes.relative,
        TransformationModes.platexy,
    )
    assert axis == ["x", "y"] and rebased is True
    assert deepcopy(d_mm) == d_mm


def test_thorlabs_platexy_homing_single_axis_now_plans():
    # The pre-extraction Thorlabs planner raised IndexError here (dead xyvec
    # loop); homing now passes the request through, as Galil always did.
    axis, d_mm, rebased = plan_move_target(
        _transform(),
        POSITIONS[0],
        ["y"],
        [0.0],
        MoveModes.homing,
        TransformationModes.platexy,
    )
    assert axis == ["y"] and list(d_mm) == [0.0] and rebased is False
