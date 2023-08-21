import os
import asyncio
import time

from helaocore.error import ErrorCodes
from helaocore.models.hlostatus import HloStatus
from helao.helpers.zstd_io import unzpickle
from helao.servers.base import Base, Active
from helao.helpers.executor import Executor
from helao.helpers.premodels import Experiment
from helao.helpers.dispatcher import async_private_dispatcher

import numpy as np
import gpflow
from scipy.stats import norm
from sklearn.metrics import mean_absolute_error


def calc_eta(cp_dict):
    thresh_ts = max(cp_dict["t_s"]) - 4
    thresh_idx = min([i for i, v in enumerate(cp_dict["t_s"]) if v > thresh_ts])
    erhes = cp_dict["erhe_v"][thresh_idx:]
    return sum(erhes) / len(erhes) - 1.23


class GPSim:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.rng = np.random.default_rng(seed=self.config_dict["random_seed"])
        self.data_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
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
        self.kernel_func = lambda: gpflow.kernels.Constant() * gpflow.kernels.Matern32(
            lengthscales=0.5
        ) + gpflow.kernels.White(variance=0.015**2)
        self.kernel = None
        self.model = None
        self.opt = gpflow.optimizers.Scipy()
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

    def init_all_plates(self, num_points: int):
        for plate_id in self.features:
            self.init_priors_random(plate_id, num_points)

    def init_priors_random(self, plate_id: int, num_points: int):
        arr = self.features[plate_id]
        ridxs = self.rng.choice(
            range(arr.shape[0]),
            num_points,
            replace=False,
            shuffle=False,
        )
        self.clear_plate(plate_id)
        print(f"!!! initial indices for plate {plate_id} are: {ridxs}")
        for ridx in ridxs:
            self.acquire_point(arr[ridx], plate_id, init_points=True)
        self.initialized[plate_id] = True

    def calc_ei(self, plate_id, xi=0.001, noise=True):
        """
        Computes the EI at points X based on existing samples X_sample
        and Y_sample using a Gaussian process surrogate model.

        Returns:
            Expected improvements at points X.
        """
        acqinds = self.acquired[plate_id] + self.acq_fromglobal[plate_id]
        X = self.features[plate_id][
            np.array(
                [i for i in range(self.features[plate_id].shape[0]) if i not in acqinds]
            )
        ].astype(float)
        X_sample = self.features[plate_id][np.array(acqinds)].astype(float)
        Y_sample = self.targets[plate_id][np.array(acqinds)]
        mu, variance = (r.numpy() for r in self.model.predict_f(X))
        mu_sample, variance_sample = (r.numpy() for r in self.model.predict_f(X_sample))

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

    def acquire_point(self, feat, plate_id: int, init_points: bool = False):
        """Adds eta result to acquired list and returns next composition."""
        self.g_acq.add(tuple(feat))
        for plate_key, idx in self.invfeats[tuple(feat)]:
            if plate_key == plate_id and not init_points:
                self.acquired[plate_key].append(idx)
            else:
                self.acq_fromglobal[plate_key].append(idx)
            self.available[plate_key].remove(idx)
        self.global_step += 1
        self.base.print_message(
            f"plate_id {plate_id} has acquired {len(self.acquired[plate_id])} points"
        )

    def fit_model(self, plate_id):
        """Assemble acquired etas per plate and predict loaded space."""
        plate_step = len(self.acquired[plate_id])
        inds = np.array(self.acquired[plate_id] + self.acq_fromglobal[plate_id]).astype(
            int
        )
        X = self.features[plate_id][inds].astype(float)
        y = self.targets[plate_id][inds]
        self.kernel = self.kernel_func()
        try:
            self.model = gpflow.models.GPR(
                data=(X, y), kernel=self.kernel, mean_function=None
            )
        except Exception as e:
            print(e)
        self.opt_logs[plate_id][plate_step] = self.opt.minimize(
            self.model.training_loss,
            self.model.trainable_variables,
            options={"maxiter": 100},
        )
        total_pred, total_var = (
            r.numpy()
            for r in self.model.predict_f(self.features[plate_id].astype(float))
        )
        total_mae = mean_absolute_error(total_pred, self.targets[plate_id])
        self.total_step[plate_id][plate_step] = (
            total_mae,
            total_pred,
            total_var,
            inds,
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
        latest_ei = self.ei_step[plate_id][plate_step]

        best_ei = latest_ei.max()
        best_idx = latest_ei.argmax()
        best_avail = list(self.features[plate_id][avail_inds[best_idx]])

        total_mae = self.total_step[plate_id][plate_step][0]
        data = {
            "expected_improvement": float(best_ei),
            "feature": [int(x) for x in best_avail],
            "total_plate_mae": float(total_mae),
            "plate_step": plate_step,
            "global_step": self.global_step,
        }
        print(data)
        self.progress[plate_id] = data
        return data

    def clear_global(self):
        self.acquired = {k: [] for k in self.all_data}
        self.acq_fromglobal = {k: [] for k in self.all_data}
        self.opt_logs = {k: {} for k in self.all_data}
        self.total_step = {k: {} for k in self.all_data}
        self.ei_step = {k: {} for k in self.all_data}
        self.avail_step = {k: {} for k in self.all_data}
        self.progress = {k: {} for k in self.all_data}
        self.g_acq = set()
        self.available = {
            k: list(range(arr.shape[0])) for k, arr in self.features.items()
        }

    def clear_plate(self, plate_id):
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

    async def check_condition(self, activeobj: Active):
        params = activeobj.action.action_params
        plate_id = params["plate_id"]
        stop_condition = params["stop_condition"]
        thresh_value = params["thresh_value"]
        repeat_experiment_name = params["repeat_experiment_name"]
        repeat_experiment_params = params["repeat_experiment_params"]
        kwargs = params["repeat_experiment_kwargs"]

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
            self.base.print_message("queueing repeat experiment request on Orch")
            resp, error = await async_private_dispatcher(
                self.base.orch_key,
                self.base.orch_host,
                self.base.orch_port,
                "insert_experiment",
                params_dict={},
                json_dict={
                    "idx": 0,
                    "experiment": rep_exp.clean_dict(),
                },
            )
            self.base.print_message(f"insert_experiment got response: {resp}")
            self.base.print_message(f"insert_experiment returned error: {error}")
        else:
            self.base.print_message(
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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.active.base.print_message("GPSimExec initialized.")
        self.start_time = time.time()  # instantiation time
        self.duration = self.active.action.action_params.get("duration", -1)
        self.plate_id = self.active.action.action_params["plate_id"]

    async def _exec(self):
        self.active.base.fastapp.driver.fit_model(self.plate_id)
        return {
            "error": ErrorCodes.none,
            "status": HloStatus.active,
        }

    async def _post_exec(self):
        data = self.active.base.fastapp.driver.progress[self.plate_id]
        return {
            "data": data,
            "error": ErrorCodes.none,
            "status": HloStatus.finished,
        }
