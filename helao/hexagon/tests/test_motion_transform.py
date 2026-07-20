"""Exercise the pure motion-frame math in `helao.hexagon.domain.motion_transform`
(P3a D6 split of `TransformXY` out of `galil_motion_driver.py`)."""

import numpy as np

from helao.hexagon.domain.motion_transform import TransformXY


def _identity_transform(seq=None):
    Minstr = np.matrix(np.identity(4))
    return TransformXY(Minstr, seq)


def test_ctor_precomputes_identity_system_matrix():
    # ctor signature: TransformXY(Minstr: 4x4 matrix, seq: Optional[iterable-of-axis-tags])
    t = _identity_transform(seq=None)
    assert np.allclose(t.M, np.identity(4))
    assert np.allclose(t.Minv, np.identity(4))


def test_platexy_motorxy_roundtrip_default_seq():
    t = _identity_transform(seq=None)
    platexy = [3.0, 4.0]

    motorxy = t.transform_platexy_to_motorxy(platexy)
    back = t.transform_motorxy_to_platexy(motorxy)

    assert np.allclose(back[:2], platexy)


def test_platexy_motorxy_roundtrip_with_axis_seq():
    # seq mirrors a config's axis_id dict (e.g. {"x": "A", "y": "B"}); iterating
    # it yields the axis-tag keys consumed by update_Msystem's "xy" fast path.
    t = _identity_transform(seq={"x": "A", "y": "B"})
    platexy = [1.5, -2.5]

    motorxy = t.transform_platexy_to_motorxy(platexy)
    back = t.transform_motorxy_to_platexy(motorxy)

    assert np.allclose(back[:2], platexy)


def test_instrxyz_motorxyz_roundtrip():
    t = _identity_transform(seq=None)
    instrxyz = [1.0, 2.0, 3.0]

    motorxyz = t.transform_instrxyz_to_motorxyz(instrxyz)
    back = t.transform_motorxyz_to_instrxyz(motorxyz)

    assert np.allclose(back[:3], instrxyz)


def test_rotation_matrices_are_4x4_and_identity_at_zero():
    t = _identity_transform(seq=None)
    for rot in (t.Rx, t.Ry, t.Rz):
        m = rot()
        assert m.shape == (4, 4)
    assert np.allclose(t.Rx(), np.identity(4))
    assert np.allclose(t.Ry(), np.identity(4))
    assert np.allclose(t.Rz(), np.identity(4))


def test_rotation_matrices_nonzero_angle():
    t = _identity_transform(seq=None)
    t.alpha = 90
    assert np.allclose(
        t.Rx(), np.matrix([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]])
    )


def test_update_msystem_runs_and_get_mplatexy_returns_matrix():
    t = _identity_transform(seq=None)
    t.update_Msystem()
    mplatexy = t.get_Mplatexy()
    assert mplatexy.shape == (3, 3)
    assert np.allclose(mplatexy, np.identity(3))


def test_update_mplatexy_refreshes_system_matrix():
    t = _identity_transform(seq=None)
    Mxy = np.matrix([[1, 0, 5], [0, 1, 7], [0, 0, 1]])

    assert t.update_Mplatexy(Mxy) is True
    # offsets from Mxy's last column land in Mplate's translation column
    assert np.isclose(t.Mplate[0, 3], 5)
    assert np.isclose(t.Mplate[1, 3], 7)
    # system matrix M was refreshed to include the new plate offsets
    assert np.isclose(t.M[0, 3], 5)
    assert np.isclose(t.M[1, 3], 7)


def test_get_mplate_msystem_recovers_plate_from_global():
    t = _identity_transform(seq=None)
    Mxy = np.identity(3)

    result = t.get_Mplate_Msystem(Mxy)

    assert result.shape == (3, 3)
    assert np.allclose(result, np.identity(3))
