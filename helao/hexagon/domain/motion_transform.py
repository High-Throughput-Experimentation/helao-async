"""Pure motion-frame coordinate transform domain service, lifted verbatim
from ``helao/deploy/hte/drivers/motion/galil_motion_driver.py``'s
``TransformXY`` (P3a D6 split): converts points between the motor, plate, and
instrument frames using only numpy matrix algebra, with no Base/Active/
gclib/Bokeh/file-IO coupling, so it is Linux-testable and reusable by P4's
ThorlabsMotor. LOGGER is stdlib ``logging.getLogger(__name__)`` per the
domain allow-list (``helao.helpers.helao_logging`` is outside it, mirroring
``global_params.py``/``dispatch_policy.py``); log wording is otherwise
unchanged from the original driver-hosted class.
"""

import logging
import traceback

import numpy as np

LOGGER = logging.getLogger(__name__)

__all__ = ["TransformXY"]


class TransformXY:
    """Coordinate transformer between motor, plate, and instrument frames.

    Stores the per-instrument matrix `Minstrxyz`, the plate calibration
    `Mplate`, and the composed system matrix `M` (and its inverse). Update
    the rotation angles `alpha`/`beta`/`gamma` and call `update_Msystem` when
    the kinematic chain changes; calling `update_Mplatexy` after a plate
    recalibration both updates the plate block and refreshes the cached
    system matrix.
    """

    def __init__(self, Minstr, seq=None):
        """Initialize the matrices and precompute the system matrix.

        Args:
            Minstr: 4x4 motor-to-instrument calibration matrix.
            seq: Optional ordered sequence of axes/rotations (e.g. ['x','y','z',
                'Rz']) describing the kinematic chain; None uses the default
                xy-only transform.

        Migration note (K2/K8): the pre-migration constructor also took an
        `action_serv: Base` argument, stored as `self.base`, and never read
        again anywhere in this class -- dropped here (mirrors
        `thorlabs_kinesis.py`'s identical `TransformXY`).
        """
        # instrument specific matrix
        # motor to instrument
        self.Minstrxyz = np.asmatrix(Minstr)  # np.asmatrix(np.identity(4))
        self.Minstr = np.asmatrix(np.identity(4))
        self.Minstrinv = np.asmatrix(np.identity(4))
        # plate Matrix
        # instrument to plate
        self.Mplate = np.asmatrix(np.identity(4))
        self.Mplatexy = np.asmatrix(np.identity(3))
        # system Matrix
        # motor to plate
        self.M = np.asmatrix(np.identity(4))
        self.Minv = np.asmatrix(np.identity(4))
        # need to update the angles here each time the axis is rotated
        self.alpha = 0
        self.beta = 0
        self.gamma = 0
        self.seq = seq

        # pre calculates the system Matrix M
        self.update_Msystem()

    def transform_platexy_to_motorxy(self, platexy, *args, **kwargs):
        """Map a plate-frame xy point to motor-frame xy via the system matrix `M`.

        Args:
            platexy: 2- or 3-element sequence (or comma-separated string) in
                the plate frame; missing trailing entries are padded.

        Returns:
            Numpy array `[motor_x, motor_y]`.
        """
        if isinstance(platexy, str):
            platexy = [float(x.strip()) for x in platexy.split(",")]
        platexy = np.asarray(platexy)
        if len(platexy) == 2:
            platexy = np.insert(platexy, 2, 1)
        if len(platexy) == 3:
            platexy = np.insert(platexy, 2, 0)
        # for _ in range(4-len(platexy)):
        #     platexy = np.append(platexy,1)
        # LOGGER.info(" ... M:\n")
        # LOGGER.info(" ... xy:")
        motorxy = np.dot(self.M, platexy)
        motorxy = np.delete(motorxy, 2)
        motorxy = np.array(motorxy)[0]
        return motorxy

    def transform_motorxy_to_platexy(self, motorxy, *args, **kwargs):
        """Map a motor-frame xy point to plate-frame xy via the inverse `Minv`."""
        if isinstance(motorxy, str):
            motorxy = [float(x.strip()) for x in motorxy.split(",")]
        motorxy = np.asarray(motorxy)
        if len(motorxy) == 2:
            motorxy = np.insert(motorxy, 2, 1)
        if len(motorxy) == 3:
            motorxy = np.insert(motorxy, 2, 0)
        # LOGGER.info(" ... Minv:\n")
        # LOGGER.info(" ... xy:")
        platexy = np.dot(self.Minv, motorxy)
        platexy = np.delete(platexy, 2)
        platexy = np.array(platexy)[0]
        return platexy

    def transform_motorxyz_to_instrxyz(self, motorxyz, *args, **kwargs):
        """Map a motor-frame xyz point to the instrument frame via `Minstrinv`."""
        motorxyz = np.asarray(motorxyz)
        if len(motorxyz) == 3:
            # append 1 at end
            motorxyz = np.append(motorxyz, 1)
        # LOGGER.info(" ... Minstrinv:\n")
        # LOGGER.info(" ... xyz:")
        instrxyz = np.dot(self.Minstrinv, motorxyz)
        return np.array(instrxyz)[0]

    def transform_instrxyz_to_motorxyz(self, instrxyz, *args, **kwargs):
        """Map an instrument-frame xyz point back to the motor frame via `Minstr`."""
        instrxyz = np.asarray(instrxyz)
        if len(instrxyz) == 3:
            instrxyz = np.append(instrxyz, 1)
        # LOGGER.info(" ... Minstr:\n")
        # LOGGER.info(" ... xyz:")

        motorxyz = np.dot(self.Minstr, instrxyz)
        return np.array(motorxyz)[0]

    def Rx(self):
        """Return the 4x4 rotation matrix about the x-axis for `self.alpha` (degrees)."""
        alphatmp = np.mod(self.alpha, 360)  # this actually takes care of neg. values
        # precalculate some common angles for better accuracy and speed
        if alphatmp == 0:  # or alphatmp == -0.0:
            return np.asmatrix(np.identity(4))
        elif alphatmp == 90:  # or alphatmp == -270:
            return np.matrix([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]])
        elif alphatmp == 180:  # or alphatmp == -180:
            return np.matrix([[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, 0], [0, 0, 0, 1]])
        elif alphatmp == 270:  # or alphatmp == -90:
            return np.matrix([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]])
        else:
            return np.matrix(
                [
                    [1, 0, 0, 0],
                    [
                        0,
                        np.cos(np.pi / 180 * alphatmp),
                        -1.0 * np.sin(np.pi / 180 * alphatmp),
                        0,
                    ],
                    [
                        0,
                        np.sin(np.pi / 180 * alphatmp),
                        np.cos(np.pi / 180 * alphatmp),
                        0,
                    ],
                    [0, 0, 0, 1],
                ]
            )

    def Ry(self):
        """Return the 4x4 rotation matrix about the y-axis for `self.beta` (degrees)."""
        betatmp = np.mod(self.beta, 360)  # this actually takes care of neg. values
        # precalculate some common angles for better accuracy and speed
        if betatmp == 0:  # or betatmp == -0.0:
            return np.asmatrix(np.identity(4))
        elif betatmp == 90:  # or betatmp == -270:
            return np.matrix([[0, 0, 1, 0], [0, 1, 0, 0], [-1, 0, 0, 0], [0, 0, 0, 1]])
        elif betatmp == 180:  # or betatmp == -180:
            return np.matrix([[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, -1, 0], [0, 0, 0, 1]])
        elif betatmp == 270:  # or betatmp == -90:
            return np.matrix([[0, 0, -1, 0], [0, 1, 0, 0], [1, 0, 0, 0], [0, 0, 0, 1]])
        else:
            return np.matrix(
                [
                    [
                        np.cos(np.pi / 180 * self.beta),
                        0,
                        np.sin(np.pi / 180 * self.beta),
                        0,
                    ],
                    [0, 1, 0, 0],
                    [
                        -1.0 * np.sin(np.pi / 180 * self.beta),
                        0,
                        np.cos(np.pi / 180 * self.beta),
                        0,
                    ],
                    [0, 0, 0, 1],
                ]
            )

    def Rz(self):
        """Return the 4x4 rotation matrix about the z-axis for `self.gamma` (degrees)."""
        gammatmp = np.mod(self.gamma, 360)  # this actually takes care of neg. values
        # precalculate some common angles for better accuracy and speed
        if gammatmp == 0:  # or gammatmp == -0.0:
            return np.asmatrix(np.identity(4))
        elif gammatmp == 90:  # or gammatmp == -270:
            return np.matrix([[0, -1, 0, 0], [1, 0, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        elif gammatmp == 180:  # or gammatmp == -180:
            return np.matrix([[-1, 0, 0, 0], [0, -1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        elif gammatmp == 270:  # or gammatmp == -90:
            return np.matrix([[0, 1, 0, 0], [-1, 0, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        else:
            return np.matrix(
                [
                    [
                        np.cos(np.pi / 180 * gammatmp),
                        -1.0 * np.sin(np.pi / 180 * gammatmp),
                        0,
                        0,
                    ],
                    [
                        np.sin(np.pi / 180 * gammatmp),
                        np.cos(np.pi / 180 * gammatmp),
                        0,
                        0,
                    ],
                    [0, 0, 1, 0],
                    [0, 0, 0, 1],
                ]
            )

    def Mx(self):
        """Return the 4x4 matrix containing only the x-row of `Minstrxyz`."""
        Mx = np.asmatrix(np.identity(4))
        Mx[0, 0:4] = self.Minstrxyz[0, 0:4]
        # LOGGER.info(" ... Mx")
        return Mx

    def My(self):
        """Return the 4x4 matrix containing only the y-row of `Minstrxyz`."""
        My = np.asmatrix(np.identity(4))
        My[1, 0:4] = self.Minstrxyz[1, 0:4]
        # LOGGER.info(" ... My")
        return My

    def Mz(self):
        """Return the 4x4 matrix containing only the z-row of `Minstrxyz`."""
        Mz = np.asmatrix(np.identity(4))
        Mz[2, 0:4] = self.Minstrxyz[2, 0:4]
        # LOGGER.info(" ... Mz")
        return Mz

    def Mplatewarp(self, platexy):
        """Return the z-correction matrix for a single plate xy point.

        Currently a stub that returns the identity matrix.
        """
        return np.asmatrix(np.identity(4))  # TODO, just returns identity matrix for now

    def update_Msystem(self):
        """Recompute `Minstr`, `M`, and their inverses from the current `seq` and angles.

        If `seq` is None the transform reduces to `Minstrxyz . Mplate`.
        Otherwise the matrix is built by walking `seq` and accumulating the
        corresponding rotation or selector matrices. Singular inverses fall
        back to a sentinel matrix with `-1` in the bottom-right entry.
        """

        LOGGER.info("updating M")

        if self.seq is None:
            LOGGER.info("seq is empty, using default transformation")
            # default case, we simply have xy calibration
            self.M = np.dot(self.Minstrxyz, self.Mplate)
        else:
            self.Minstr = np.asmatrix(np.identity(4))
            # more complicated
            # check for some common experiments:
            Mcommon1 = (
                False  # to check against when common combinations are already found
            )
            axstr = ""
            for ax in self.seq:
                axstr += ax
            # check for xyz or xy (with no z)
            # experiment does not matter so should define it like this in the config
            # if we want to use this
            if axstr.find("xy") == 0 and axstr.find("z") <= 2:
                LOGGER.info("got xyz seq")
                self.Minstr = self.Minstrxyz
                Mcommon1 = True

            for ax in self.seq:
                if ax == "x" and not Mcommon1:
                    LOGGER.info("got x seq")
                    self.Minstr = np.dot(self.Minstr, self.Mx())
                elif ax == "y" and not Mcommon1:
                    LOGGER.info("got y seq")
                    self.Minstr = np.dot(self.Minstr, self.My())
                elif ax == "z" and not Mcommon1:
                    LOGGER.info("got z seq")
                    self.Minstr = np.dot(self.Minstr, self.Mz())
                elif ax == "Rx":
                    LOGGER.info("got Rx seq")
                    self.Minstr = np.dot(self.Minstr, self.Rx())
                elif ax == "Ry":
                    LOGGER.info("got Ry seq")
                    self.Minstr = np.dot(self.Minstr, self.Ry())
                elif ax == "Rz":
                    LOGGER.info("got Rz seq")
                    self.Minstr = np.dot(self.Minstr, self.Rz())

            self.M = np.dot(self.Minstr, self.Mplate)

            # precalculate the inverse as we also need it a lot
            try:
                self.Minv = self.M.I
            except Exception as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                LOGGER.error(f"System Matrix singular ", exc_info=True)
                # use the -1 to signal inverse later --> platexy will then be [x,y,-1]
                self.Minv = np.matrix(
                    [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, -1]]
                )

            try:
                self.Minstrinv = self.Minstr.I
            except Exception as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                LOGGER.error(f"Instrument Matrix singular ", exc_info=True)
                # use the -1 to signal inverse later --> platexy will then be [x,y,-1]
                self.Minstrinv = np.matrix(
                    [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, -1]]
                )

    def update_Mplatexy(self, Mxy, *args, **kwargs) -> bool:
        """Copy a 3x3 plate-xy matrix into `Mplate` and refresh the system matrix.

        Args:
            Mxy: 3x3 plate calibration matrix (linear block in [0:2, 0:2],
                offsets in column 2).

        Returns:
            True once the update completes.
        """
        Mxy = np.matrix(Mxy)
        # assign the xy part
        self.Mplate[0:2, 0:2] = Mxy[0:2, 0:2]
        # assign the last row (offsets), notice the difference in col (3x3 vs 4x4)
        #        self.Mplate[0:2,3] = Mxy[0:2,2] # something does not work with this one is a 1x2 the other 2x1 for some reason
        self.Mplate[0, 3] = Mxy[0, 2]
        self.Mplate[1, 3] = Mxy[1, 2]
        # self.Mplate[3,0:4] should always be 0,0,0,1 and should never change

        # update the system matrix so we save calculation time later
        self.update_Msystem()
        return True

    def get_Mplatexy(self):
        """Return the 3x3 plate xy calibration matrix derived from `self.Mplate`."""
        self.Mplatexy = np.asmatrix(np.identity(3))
        self.Mplatexy[0:2, 0:2] = self.Mplate[0:2, 0:2]
        self.Mplatexy[0, 2] = self.Mplate[0, 3]
        self.Mplatexy[1, 2] = self.Mplate[1, 3]
        return self.Mplatexy

    def get_Mplate_Msystem(self, Mxy, *args, **kwargs):
        """Given a global system matrix `Mxy`, factor out `Minstr` to recover Mplate.

        Used during alignment to convert a fitted global transform into a
        plate-only calibration. Falls back to a sentinel matrix when
        `Minstr` is singular.
        """
        Mxy = np.asarray(Mxy)
        Mglobal = np.asmatrix(np.identity(4))
        Mglobal[0:2, 0:2] = Mxy[0:2, 0:2]
        Mglobal[0, 3] = Mxy[0, 2]
        Mglobal[1, 3] = Mxy[1, 2]

        try:
            Minstrinv = self.Minstr.I
            Mtmp = np.dot(Minstrinv, Mglobal)
            self.Mplatexy = np.asmatrix(np.identity(3))
            self.Mplatexy[0:2, 0:2] = Mtmp[0:2, 0:2]
            self.Mplatexy[0, 2] = Mtmp[0, 3]
            self.Mplatexy[1, 2] = Mtmp[1, 3]

            return self.Mplatexy
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(f"Instrument Matrix singular ", exc_info=True)
            # use the -1 to signal inverse later --> platexy will then be [x,y,-1]
            self.Minv = np.matrix([[0, 0, 0], [0, 0, 0], [0, 0, -1]])
