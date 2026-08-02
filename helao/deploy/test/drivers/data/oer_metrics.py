"""Pure OER metrics shared by the simulator drivers.

``calc_eta`` used to live in ``gpsim_driver``, which imports a GP stack at
module scope. That made every consumer transitively depend on it for four lines
of arithmetic that need none of it -- and when that stack was gpflow, whose
TensorFlow dependency has no Python 3.14 build, it took ``cpsim_driver`` down
with the GP simulator. The backend is gpytorch now, but the coupling would be
just as wrong.

Nothing here may import gpytorch, torch, or any optional heavy dependency.
"""

__all__ = ["calc_eta"]

#: Thermodynamic OER potential, V vs RHE.
OER_POTENTIAL_VRHE = 1.23

#: Trailing window of a CP trace averaged to obtain the steady-state potential.
ETA_WINDOW_S = 4


def calc_eta(cp_dict) -> float:
    """Compute the OER overpotential from the last four seconds of a CP trace.

    Args:
        cp_dict: Dict with parallel ``"t_s"`` and ``"erhe_v"`` lists from a CP
            measurement.

    Returns:
        Mean potential (in V vs RHE) over the final 4 s of the trace minus the
        thermodynamic OER potential (1.23 V).
    """
    thresh_ts = max(cp_dict["t_s"]) - ETA_WINDOW_S
    thresh_idx = min([i for i, v in enumerate(cp_dict["t_s"]) if v > thresh_ts])
    erhes = cp_dict["erhe_v"][thresh_idx:]
    return sum(erhes) / len(erhes) - OER_POTENTIAL_VRHE
