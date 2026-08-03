"""Gaussian-process regression backend for the OER simulator.

Wraps ``gpytorch`` behind the three operations ``gpsim_driver`` actually uses:
fit a surrogate to acquired points, and predict latent mean and variance over
candidate points. Keeping the GP library behind this seam means the driver
holds acquisition logic only, and the backend can be tested on synthetic data
with no HELAO machinery present.

This replaces ``gpflow``, which pulls in TensorFlow -- and TensorFlow has no
Python 3.14 release, which is what made the GP simulator unimportable and got
the whole OERSIM stack shelved.

**The model is a port, not a redesign.** It reproduces what the gpflow version
specified:

===========================  ====================================
gpflow                       gpytorch
===========================  ====================================
``mean_function=None``       :class:`~gpytorch.means.ZeroMean`
``kernels.Constant()``       :class:`~gpytorch.kernels.ConstantKernel`
``kernels.Matern32(ls=50)``  ``MaternKernel(nu=1.5)``, same init
``kernels.White(1e-4)``      likelihood noise, same init
``models.GPR``               :class:`~gpytorch.models.ExactGP`
``optimizers.Scipy``         Adam on the exact marginal likelihood
===========================  ====================================

One difference is deliberate. gpflow carried observation noise twice -- a
``White`` kernel *and* the GPR likelihood's own variance, which are degenerate
against each other. gpytorch models it once, in the likelihood, initialized to
the ``White`` kernel's value.
"""

__all__ = ["GPRegressor", "DEFAULT_LENGTHSCALE", "DEFAULT_NOISE", "TRAIN_ITERS"]

import numpy as np
import torch

import gpytorch

#: Matern lengthscale at initialization, carried over from the gpflow model.
#: Compositions are expressed in percent, so this is half the axis range.
DEFAULT_LENGTHSCALE = 50.0

#: Initial observation-noise variance, from the gpflow ``White`` kernel.
DEFAULT_NOISE = 1e-4

#: Adam steps per fit. gpflow used L-BFGS with ``maxiter=100``; Adam needs more
#: steps for comparable marginal-likelihood improvement, and unlike L-BFGS it
#: cannot fail outright on an ill-conditioned step.
TRAIN_ITERS = 200

#: Adam step size. Large enough to move hyperparameters meaningfully within
#: TRAIN_ITERS, small enough not to oscillate on a handful of points -- the
#: acquisition loop refits from as few as five acquired compositions.
LEARNING_RATE = 0.1


class _ExactGP(gpytorch.models.ExactGP):
    """Zero-mean exact GP with the ported kernel structure."""

    def __init__(self, train_x, train_y, likelihood):
        """Build the model around one training set.

        Args:
            train_x: ``(N, D)`` training inputs.
            train_y: ``(N,)`` training targets.
            likelihood: The Gaussian likelihood carrying observation noise.
        """
        super().__init__(train_x, train_y, likelihood)
        self.mean_module = gpytorch.means.ZeroMean()
        self.covar_module = (
            gpytorch.kernels.ConstantKernel()
            + gpytorch.kernels.ScaleKernel(gpytorch.kernels.MaternKernel(nu=1.5))
        )
        self.covar_module.kernels[1].base_kernel.lengthscale = DEFAULT_LENGTHSCALE

    def forward(self, x):
        """Return the prior at ``x``."""
        return gpytorch.distributions.MultivariateNormal(
            self.mean_module(x), self.covar_module(x)
        )


class GPRegressor:
    """A GP surrogate over one plate's composition space.

    Fitting builds a fresh model, matching the gpflow code it replaces: each
    refit there constructed a new ``GPR`` rather than warm-starting, so an
    unlucky earlier fit cannot poison later ones.

    Attributes:
        train_iters: Adam steps taken per :meth:`fit`.
    """

    def __init__(self, train_iters: int = TRAIN_ITERS):
        """Create an unfitted regressor.

        Args:
            train_iters: Adam steps per fit.
        """
        self.train_iters = train_iters
        self._model = None
        self._likelihood = None
        self._trained_on = 0
        #: Final negative marginal log-likelihood, for the driver's fit log.
        self.final_loss = None

    @property
    def fitted(self) -> bool:
        """Whether :meth:`fit` has run."""
        return self._model is not None

    def fit(self, X, y) -> None:
        """Fit the surrogate to acquired compositions.

        Args:
            X: ``(N, D)`` composition vectors.
            y: ``(N, 1)`` or ``(N,)`` measured targets.

        Raises:
            ValueError: If ``X`` and ``y`` disagree in length, or ``X`` is
                empty -- an exact GP has nothing to condition on, and the
                caller has an acquisition bug rather than a modelling one.
        """
        train_x = torch.as_tensor(np.asarray(X, dtype=np.float64))
        train_y = torch.as_tensor(np.asarray(y, dtype=np.float64)).reshape(-1)
        if train_x.ndim != 2:
            raise ValueError(f"X must be 2-D, got shape {tuple(train_x.shape)}")
        if train_x.shape[0] != train_y.shape[0]:
            raise ValueError(
                f"X has {train_x.shape[0]} rows but y has {train_y.shape[0]}"
            )
        if train_x.shape[0] == 0:
            raise ValueError("cannot fit a GP with no acquired points")

        likelihood = gpytorch.likelihoods.GaussianLikelihood().double()
        likelihood.noise = DEFAULT_NOISE
        model = _ExactGP(train_x, train_y, likelihood).double()

        model.train()
        likelihood.train()
        optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
        mll = gpytorch.mlls.ExactMarginalLogLikelihood(likelihood, model)
        loss = None
        for _ in range(self.train_iters):
            optimizer.zero_grad()
            loss = -mll(model(train_x), train_y)
            loss.backward()
            optimizer.step()
        # detach first: the loss still carries its graph, and converting it
        # directly warns and keeps that graph alive on the driver's fit log.
        self.final_loss = float(loss.detach()) if loss is not None else None

        model.eval()
        likelihood.eval()
        self._model = model
        self._likelihood = likelihood
        self._trained_on = int(train_x.shape[0])

    def predict_f(self, X):
        """Predict the latent function's mean and variance.

        Latent, not predictive: observation noise is excluded, matching
        gpflow's ``predict_f``. The acquisition function treats the variance as
        model uncertainty, so folding in noise would inflate Expected
        Improvement everywhere by a constant and flatten the ranking.

        Args:
            X: ``(N, D)`` compositions to score.

        Returns:
            tuple[np.ndarray, np.ndarray]: ``(mean, variance)``, each
            ``(N, 1)`` -- the shape gpflow returned and the driver's arithmetic
            assumes.

        Raises:
            RuntimeError: If called before :meth:`fit`.
        """
        if self._model is None:
            raise RuntimeError("predict_f called before fit")
        test_x = torch.as_tensor(np.asarray(X, dtype=np.float64))
        if test_x.ndim != 2:
            raise ValueError(f"X must be 2-D, got shape {tuple(test_x.shape)}")
        # debug off: the acquisition loop scores acquired points too, and
        # gpytorch warns on every eval-mode call whose input matches the
        # training set. Here that is intended, not a mistake.
        with (
            torch.no_grad(),
            gpytorch.settings.fast_pred_var(),
            gpytorch.settings.debug(False),
        ):
            posterior = self._model(test_x)
            mean = posterior.mean.numpy().reshape(-1, 1)
            variance = posterior.variance.numpy().reshape(-1, 1)
        # A tiny negative variance is numerically possible and would become NaN
        # the moment the acquisition function takes a square root.
        return mean, np.clip(variance, 0.0, None)
