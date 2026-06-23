"""Gaussian-process surrogate simulator for OER active-learning demos.

Provides :class:`GPSim`, a driver that loads a pickled subset of CP measurements,
maintains per-plate ``gpflow`` models, and exposes acquisition/initialization/fit
routines used by the GP simulator action server, plus :class:`GPSimExec`, the
:class:`Executor` that fits the model from inside a running action.
"""

import os
import asyncio
import time

from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.support.file_utils import unzpickle
from helao.framework.app.base_api import Base
from helao.framework.domain.action_session import ActionSession as Active
from helao.framework.domain.executor import Executor
from helao.framework.domain.run_models import RunExperiment as Experiment
from helao.framework.support.dispatcher import async_private_dispatcher

import numpy as np
import gpflow
from scipy.stats import norm
from sklearn.metrics import mean_absolute_error


def calc_eta(cp_dict) -> float:
    """Compute the OER overpotential from the last four seconds of a CP trace.

    Args:
        cp_dict: Dict with parallel ``"t_s"`` and ``"erhe_v"`` lists from a CP
            measurement.

    Returns:
        Mean potential (in V vs RHE) over the final 4 s of the trace minus the
        thermodynamic OER potential (1.23 V).
    """
    thresh_ts = max(cp_dict["t_s"]) - 4
    thresh_idx = min([i for i, v in enumerate(cp_dict["t_s"]) if v > thresh_ts])
    erhes = cp_dict["erhe_v"][thresh_idx:]
    return sum(erhes) / len(erhes) - 1.23


class GPSim:
    """Per-plate Gaussian-process surrogate over an OER composition library.

    Loads pickled CP data for every plate in ``oer13_cps.pzstd``, derives an eta
    target per composition, and maintains a ``gpflow`` regression model per
    plate alongside the bookkeeping (acquired/available indices, EI history,
    progress) that the GP action server endpoints rely on.

    Attributes:
        base: Hosting action server, used for live-buffer updates.
        config_dict: ``params`` block from the server config.
        rng: Seeded ``numpy`` generator for random initialization.
        all_data: Pickled per-plate composition-and-trace dataset.
        els: Element labels common to every plate.
        features: Mapping of ``plate_id`` to its composition feature array.
        targets: Mapping of ``plate_id`` to its eta target column.
        acquired: Per-plate indices acquired through this plate's own CP runs.
        acq_fromglobal: Per-plate indices acquired through other plates that
            share the same composition.
        available: Per-plate indices still eligible for acquisition.
        g_acq: Set of compositions acquired across all plates.
        g_avl: Set of all known compositions.
        invfeats: Mapping of composition tuple to ``(plate_id, idx)`` entries.
        models: Per-plate ``gpflow.models.GPR`` instances.
        progress: Latest acquisition record per plate.
        initialized: Per-plate flag set after prior initialization.
        global_step: Counter of acquisitions across all plates.
    """

    def __init__(self, action_serv: Base):
        """Initialize the simulator and kick off prior initialization.

        Args:
            action_serv: Action server hosting this driver.
        """
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.rng = np.random.default_rng(seed=self.config_dict["random_seed"])
        self.data_file = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
            ),
            "demos",
            "data",
            "oer13_cps.pzstd",
        )
        self.all_data = unzpickle(self.data_file)
        self.els = self.all_data["els"]
        self.all_data.pop("els")

        self.features = {
            k: np.array(sorted(d.keys())).astype(int) for k, d in self.all_data.items()
        }
        self.all_plate_feats = np.vstack([arr for arr in self.features.values()])

        sign = -1.0 if self.config_dict.get("minimize", True) else 1.0
        self.targets = {
            k: np.array(
                [sign * calc_eta(self.all_data[k][tuple(cvec)]["CP3"]) for cvec in arr]
            ).reshape(-1, 1)
            for k, arr in self.features.items()
        }
        for k, arr in self.targets.items():
            LOGGER.info(f"plate {k} has eta mean {arr.mean()}")
        # precalculated for simulation only
        self.lib_pcts = {
            k: {p: np.percentile(etas, p) for p in (1, 2, 5, 10)}
            for k, etas in self.targets.items()
        }
        # acquired indices per library
        self.acquired = {k: [] for k in self.all_data}
        self.acq_fromglobal = {k: [] for k in self.all_data}
        self.available = {
            k: list(range(arr.shape[0])) for k, arr in self.features.items()
        }

        # global acquired and available
        self.g_acq = set()
        self.g_avl = set([tuple(x) for x in self.all_plate_feats])

        # inverse map of all comps to libraries
        self.invfeats = {
            feat: [
                (plate_id, np.where((arr == feat).all(axis=1))[0][0])
                for plate_id, arr in self.features.items()
                if feat in self.all_data[plate_id]
            ]
            for feat in self.g_avl
        }

        # gpflow model
        self.kernel_func = (
            lambda: gpflow.kernels.Constant()
            + gpflow.kernels.Matern32(lengthscales=50.0)
            + gpflow.kernels.White(variance=1e-4)
        )
        self.models = {k: None for k in self.all_data}
        self.opt_logs = {k: {} for k in self.all_data}
        self.total_step = {k: {} for k in self.all_data}
        self.ei_step = {k: {} for k in self.all_data}
        self.avail_step = {k: {} for k in self.all_data}
        self.progress = {k: {} for k in self.all_data}
        self.initialized = {k: False for k in self.all_data}

        self.acq_fun, self.acq_fom, self.long_acq_fom = (
            self.calc_ei,
            "EI",
            "Expected Improvement",
        )

        self.global_step = 0
        self.event_loop = asyncio.get_event_loop()
        self.myinit()

    def myinit(self):
        """Schedule background initialization of priors for every plate."""
        asyncio.create_task(self.init_all_plates(5))

    async def init_all_plates(self, num_points: int):
        """Initialize random priors for every plate in the dataset.

        Args:
            num_points: Number of random compositions to acquire per plate.
        """
        for plate_id in self.features:
            await self.init_priors_random(plate_id, num_points)

    async def init_priors_random(self, plate_id: int, num_points: int):
        """Clear a plate and seed it with random initial acquisitions.

        Args:
            plate_id: Plate to (re)initialize.
            num_points: Number of random compositions to acquire before fitting.
        """
        arr = self.features[plate_id]
        ridxs = self.rng.choice(
            range(arr.shape[0]),
            num_points,
            replace=False,
            shuffle=False,
        )
        self.clear_plate(plate_id)
        # LOGGER.info(f"!!! initial indices for plate {plate_id} are: {ridxs}")
        for ridx in ridxs:
            await self.acquire_point(plate_id, init_point=list(arr[ridx]))
        await self.fit_model(plate_id)
        self.initialized[plate_id] = True

    def calc_ei(self, plate_id, xi=0.001, noise=True):
        """Compute Expected Improvement over unacquired compositions on a plate.

        Args:
            plate_id: Plate whose surrogate model and indices to score.
            xi: Exploration weighting added to the incumbent.
            noise: If True, use the predicted mean of acquired points as the
                incumbent; otherwise use the observed maximum.

        Returns:
            Tuple ``(ei, mu, variance)`` of arrays over the unacquired
            compositions of ``plate_id``.
        """
        acqinds = np.array(
            self.acquired[plate_id] + self.acq_fromglobal[plate_id]
        ).astype(int)
        X = self.features[plate_id][
            np.array(
                [i for i in range(self.features[plate_id].shape[0]) if i not in acqinds]
            )
        ].astype(float)
        X_sample = self.features[plate_id][acqinds].astype(float).round(2)
        Y_sample = self.targets[plate_id][acqinds]
        mu, variance = (r.numpy() for r in self.models[plate_id].predict_f(X))
        mu_sample, variance_sample = (
            r.numpy() for r in self.models[plate_id].predict_f(X_sample)
        )

        sigma = variance**0.5

        if noise:
            mu_sample_opt = np.max(mu_sample)
        else:
            mu_sample_opt = np.max(Y_sample)

        with np.errstate(divide="warn"):
            imp = mu - mu_sample_opt - xi
            Z = imp / sigma
            ei = imp * norm.cdf(Z) + sigma * norm.pdf(Z)
            ei[sigma == 0.0] = 0.0

        return ei, mu, variance

    async def acquire_point(
        self, plate_id: int, init_point: list = [], orch_str: str = ""
    ) -> dict:
        """Pick (or record) the next composition to measure on a plate.

        When ``init_point`` is empty the maximum-EI unacquired composition is
        chosen and recorded as the next measurement; otherwise the supplied
        composition is logged as already acquired (used during prior
        initialization).

        Args:
            plate_id: Plate to advance.
            init_point: Optional explicit composition vector to mark acquired.
            orch_str: Label of the requesting orchestrator for live-buffer
                status messages.

        Returns:
            Progress dict (``expected_improvement``, ``feature``,
            ``total_plate_mae``, ``plate_step``, ``global_step``) for the
            EI-driven branch, or an empty dict for the init branch.
        """
        if not init_point:
            plate_step = len(self.acquired[plate_id])
            latest_ei = self.ei_step[plate_id][plate_step]

            ei_avail_inds = list(self.avail_step[plate_id][plate_step][3])
            current_avail_inds = self.available[plate_id]

            filtered_inds = [i for i in ei_avail_inds if i in current_avail_inds]
            filtered_ei = [
                ei for i, ei in zip(ei_avail_inds, latest_ei) if i in current_avail_inds
            ]

            best_idx, best_ei = [
                (i, ei)
                for i, ei in zip(filtered_inds, filtered_ei)
                if ei == max(filtered_ei)
            ][0]

            best_avail = list(self.features[plate_id][best_idx])

            total_mae = self.total_step[plate_id][plate_step][0]
            data = {
                "expected_improvement": float(best_ei),
                "feature": [int(x) for x in best_avail],
                "total_plate_mae": float(total_mae),
                "plate_step": plate_step,
                "global_step": self.global_step,
            }
            self.progress[plate_id] = data
            self.g_acq.add(tuple(best_avail))
            for plate_key, idx in self.invfeats[tuple(best_avail)]:
                if plate_key == plate_id:
                    self.acquired[plate_key].append(idx)
                else:
                    self.acq_fromglobal[plate_key].append(idx)
                if idx in self.available[plate_key]:
                    self.available[plate_key].remove(idx)
            self.global_step += 1
            compstr = "-".join(
                [
                    f"{x}{y/100:.1f}"
                    for x, y in zip(self.els, self.features[plate_id][best_idx])
                    if y > 0
                ]
            )
            await self.base.put_lbuf(
                {"status": f"{orch_str} was advised to measure composition {compstr}"}
            )

        else:
            data = {}
            self.g_acq.add(tuple(init_point))
            for plate_key, idx in self.invfeats[tuple(init_point)]:
                if idx not in self.acq_fromglobal[plate_key]:
                    self.acq_fromglobal[plate_key].append(idx)
                if idx in self.available[plate_key]:
                    self.available[plate_key].remove(idx)
            self.global_step += 1
        LOGGER.info(
            f"plate_id {plate_id} has acquired {len(self.acquired[plate_id])} points"
        )
        return data

    async def fit_model(self, plate_id, orch_str: str = "") -> dict:
        """Refit the per-plate GP and update prediction/EI bookkeeping.

        Pushes a per-step live-buffer update (acquired fraction, last
        composition, ground-truth and predicted histograms) before refitting,
        then stores total/available MAE and the next EI vector.

        Args:
            plate_id: Plate whose model to refit.
            orch_str: Label of the requesting orchestrator for live-buffer
                status messages.

        Returns:
            Empty dict; results are written to ``self.total_step`` /
            ``self.avail_step`` / ``self.ei_step``.
        """
        plate_step = len(self.acquired[plate_id])

        if plate_step > 0:
            # update live buffer with acquired
            live_dict = {
                k: []
                for k in (
                    "plate_id",
                    "step",
                    "frac_acquired",
                    "last_acquisition",
                    "pred_avail",
                    "gt_acquired",
                    "orchestrator",
                    "status",
                )
            }
            # populate live_dict
            frac_acquired = (
                len(self.acquired[plate_id] + self.acq_fromglobal[plate_id])
                / self.features[plate_id].shape[0]
            )
            avail_pred = list(
                -1 * self.avail_step[plate_id][plate_step - 1][1].reshape(-1)
            )
            acq_gt = list(
                -1
                * self.targets[plate_id][
                    np.array(self.acquired[plate_id] + self.acq_fromglobal[plate_id])
                ].reshape(-1)
            )
            live_dict["plate_id"].append(plate_id)
            live_dict["step"].append(plate_step - 1)
            live_dict["frac_acquired"].append(frac_acquired)
            compstr = "-".join(
                [
                    f"{x}{y/100:.1f}"
                    for x, y in zip(
                        self.els,
                        self.features[plate_id][
                            self.acquired[plate_id][plate_step - 1]
                        ],
                    )
                    if y > 0
                ]
            )
            live_dict["last_acquisition"].append(compstr)
            live_dict["pred_avail"].append(avail_pred)
            live_dict["gt_acquired"].append(acq_gt)
            live_dict["orchestrator"].append(orch_str)
            live_dict["status"].append(f"{compstr} was acquired on {orch_str}")
            await self.base.put_lbuf(live_dict)

        acq_inds = np.array(
            self.acquired[plate_id] + self.acq_fromglobal[plate_id]
        ).astype(int)
        LOGGER.info("acquired indices:", acq_inds)
        X = self.features[plate_id][acq_inds].astype(float).round(2)
        y = self.targets[plate_id][acq_inds]
        LOGGER.info(f"features {X.shape}:", X)
        LOGGER.info(f"targets {y.shape}:", y)
        opt = gpflow.optimizers.Scipy()
        kernel = self.kernel_func()
        try:
            self.models[plate_id] = gpflow.models.GPR(
                data=(X, y), kernel=kernel, mean_function=None
            )
        except Exception as e:
            LOGGER.info(e)
        self.opt_logs[plate_id][plate_step] = opt.minimize(
            self.models[plate_id].training_loss,
            self.models[plate_id].trainable_variables,
            options={"maxiter": 100},
        )
        total_pred, total_var = (
            r.numpy()
            for r in self.models[plate_id].predict_f(
                self.features[plate_id].astype(float).round(2)
            )
        )
        LOGGER.info("prediction min:", total_pred.min())
        LOGGER.info("prediction mean:", total_pred.mean())
        LOGGER.info("prediction max:", total_pred.max())
        total_mae = mean_absolute_error(total_pred, self.targets[plate_id])
        self.total_step[plate_id][plate_step] = (
            total_mae,
            total_pred,
            total_var,
            acq_inds,
        )

        avail_ei, avail_pred, avail_var = self.acq_fun(plate_id, 0.01, True)
        self.ei_step[plate_id][plate_step] = avail_ei

        avail_inds = np.array(self.available[plate_id]).astype(int)
        avail_mae = mean_absolute_error(avail_pred, self.targets[plate_id][avail_inds])
        self.avail_step[plate_id][plate_step] = (
            avail_mae,
            avail_pred,
            avail_var,
            avail_inds,
        )
        data = {}
        return data

    def clear_global(self):
        """Reset all per-plate state, models, and global acquisition history."""
        self.acquired = {k: [] for k in self.all_data}
        self.acq_fromglobal = {k: [] for k in self.all_data}
        self.opt_logs = {k: {} for k in self.all_data}
        self.total_step = {k: {} for k in self.all_data}
        self.ei_step = {k: {} for k in self.all_data}
        self.avail_step = {k: {} for k in self.all_data}
        self.progress = {k: {} for k in self.all_data}
        self.g_acq = set()
        self.initialized = {k: False for k in self.all_data}
        self.available = {
            k: list(range(arr.shape[0])) for k, arr in self.features.items()
        }
        self.models = {k: None for k in self.all_data}

    def clear_plate(self, plate_id):
        """Reset state for one plate, retaining globally acquired compositions.

        Args:
            plate_id: Plate to reset.
        """
        self.acquired[plate_id] = []
        self.acq_fromglobal[plate_id] = [
            idx
            for tup in self.g_acq
            for pid, idx in self.invfeats[tup]
            if plate_id == pid
        ]
        self.opt_logs[plate_id] = {}
        self.total_step[plate_id] = {}
        self.ei_step[plate_id] = {}
        self.avail_step[plate_id] = {}
        self.progress[plate_id] = {}
        self.initialized[plate_id] = False
        self.available[plate_id] = [
            i
            for i in range(self.features[plate_id].shape[0])
            if i not in self.acq_fromglobal[plate_id]
        ]
        self.models[plate_id] = None

    async def check_condition(self, activeobj: Active) -> dict:
        """Evaluate the active-learning stop condition and requeue if needed.

        Inspects the latest plate progress against the configured
        ``stop_condition`` (``none``, ``max_iters``, ``max_stdev``,
        ``max_ei``). While the condition is unmet, this dispatches an
        ``insert_experiment`` RPC back to the requesting orchestrator to
        queue the next iteration.

        Args:
            activeobj: Active action whose ``action_params`` carry the
                stop criteria and orchestrator coordinates.

        Returns:
            Latest progress dict augmented with ``max_prediction_stdev``.
        """
        params = activeobj.action.action_params
        plate_id = params["plate_id"]
        stop_condition = params["stop_condition"]
        thresh_value = params["thresh_value"]
        repeat_experiment_name = params["repeat_experiment_name"]
        repeat_experiment_params = params["repeat_experiment_params"]
        kwargs = params["repeat_experiment_kwargs"]
        orch_key = params["orch_key"]
        orch_host = params["orch_host"]
        orch_port = params["orch_port"]

        repeat_measure_acquire = False
        progress = self.progress[plate_id]
        repeat_map = {
            # search full plate
            "none": len(self.acquired[plate_id] + self.acq_fromglobal[plate_id])
            < self.features[plate_id].shape[0],
            # below maximum iterations per plate
            "max_iters": progress["plate_step"] < thresh_value,
            # max model uncertainty
            "max_stdev": max(
                self.avail_step[plate_id][len(self.acquired[plate_id])][2] ** 2
            )
            > thresh_value,
            # maximum expected improvement
            "max_ei": progress["expected_improvement"] > thresh_value,
        }
        if repeat_map[stop_condition] and repeat_map["none"]:
            repeat_measure_acquire = True

        if repeat_measure_acquire:
            # add experiment to orchestrator
            rep_exp = Experiment(
                experiment_name=repeat_experiment_name,
                experiment_params=repeat_experiment_params,
                **kwargs,
            )
            LOGGER.info("queueing repeat experiment request on Orch")
            resp, error = await async_private_dispatcher(
                orch_key,
                orch_host,
                orch_port,
                "insert_experiment",
                params_dict={},
                json_dict={
                    "idx": 0,
                    "experiment": rep_exp.clean_dict(),
                },
            )
            LOGGER.info(f"insert_experiment got response: {resp}")
            LOGGER.info(f"insert_experiment returned error: {error}")
        else:
            LOGGER.info(
                f"Threshold condition {stop_condition} {thresh_value} has been met."
            )
        return_dict = progress
        return_dict.update(
            {
                "max_prediction_stdev": float(
                    max(self.avail_step[plate_id][len(self.acquired[plate_id])][2] ** 2)
                ),
            }
        )
        return return_dict


class GPSimExec(Executor):
    """Executor that refits the GP surrogate inside a running action.

    Reads ``plate_id`` and ``orch_str`` from the active action's parameters,
    invokes :meth:`GPSim.fit_model`, then surfaces the resulting progress
    dict in ``_post_exec``.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the executor from the active action's parameters."""
        super().__init__(*args, **kwargs)
        LOGGER.info("GPSimExec initialized.")
        self.start_time = time.time()  # instantiation time
        self.duration = self.active.action.action_params.get("duration", -1)
        self.plate_id = self.active.action.action_params["plate_id"]
        self.orch_str = self.active.action.action_params["orch_str"]

    async def _exec(self) -> dict:
        """Refit the surrogate model for the configured plate.

        Returns:
            ``{"error": ErrorCodes.none, "status": HloStatus.active}``.
        """
        await self.active.driver.fit_model(self.plate_id, self.orch_str)
        return {
            "error": ErrorCodes.none,
            "status": HloStatus.active,
        }

    async def _post_exec(self) -> dict:
        """Return the latest plate progress as the action's final data.

        Returns:
            Dict with the plate's progress payload, ``error`` and
            ``HloStatus.finished``.
        """
        data = self.active.driver.progress[self.plate_id]
        return {
            "data": data,
            "error": ErrorCodes.none,
            "status": HloStatus.finished,
        }
