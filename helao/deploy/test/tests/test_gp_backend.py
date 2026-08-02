"""Tests for the gpytorch surrogate behind the OER simulator.

These assert GP behaviour the acquisition loop depends on — shapes, that the
model interpolates what it was trained on, that uncertainty is larger away from
data, and that variance is never negative — rather than exact numbers, which
are optimizer-dependent and would make the suite a change detector.
"""

import numpy as np
import pytest

from helao.deploy.test.drivers.data.gp_backend import GPRegressor

#: Small, so the suite stays fast. Enough to fit a smooth 2-D function.
FIT_ITERS = 60


def _smooth(x):
    """A smooth target over composition-like inputs."""
    return np.sin(x[:, 0] / 30.0) + 0.5 * np.cos(x[:, 1] / 40.0)


@pytest.fixture
def fitted():
    """A regressor fitted to 25 points of a smooth function on 0..100."""
    rng = np.random.default_rng(0)
    X = rng.uniform(0, 100, size=(25, 4))
    y = _smooth(X).reshape(-1, 1)
    gp = GPRegressor(train_iters=FIT_ITERS)
    gp.fit(X, y)
    return gp, X, y


def test_predict_f_returns_column_vectors(fitted):
    """gpflow returned (N, 1) and the driver's arithmetic assumes it: EI
    subtracts an incumbent from `mu` and stores the result beside (N, 1)
    targets, so a flat (N,) would broadcast into an (N, N) matrix instead of
    raising."""
    gp, X, _ = fitted
    mean, var = gp.predict_f(X)
    assert mean.shape == (X.shape[0], 1)
    assert var.shape == (X.shape[0], 1)


def test_fitted_model_interpolates_its_training_points(fitted):
    """Observation noise starts at 1e-4, so the posterior mean should sit
    essentially on the training targets."""
    gp, X, y = fitted
    mean, _ = gp.predict_f(X)
    assert np.abs(mean - y).max() < 0.05


def test_uncertainty_is_lower_at_training_points_than_far_away(fitted):
    """Expected Improvement is driven entirely by this contrast; a model whose
    variance ignores the data would make acquisition a random walk."""
    gp, X, _ = fitted
    _, var_train = gp.predict_f(X)
    far = np.full((5, 4), 1000.0)
    _, var_far = gp.predict_f(far)
    assert var_train.mean() < var_far.mean()


def test_variance_is_never_negative(fitted):
    """A tiny negative variance is numerically possible, and becomes NaN the
    moment the acquisition function takes its square root."""
    gp, X, _ = fitted
    rng = np.random.default_rng(7)
    _, var = gp.predict_f(rng.uniform(0, 100, size=(200, 4)))
    assert (var >= 0).all()


def test_the_model_generalizes_better_than_predicting_the_mean(fitted):
    """The surrogate has to carry real signal for active learning to converge."""
    gp, _, _ = fitted
    rng = np.random.default_rng(3)
    Xt = rng.uniform(0, 100, size=(150, 4))
    yt = _smooth(Xt).reshape(-1, 1)
    mean, _ = gp.predict_f(Xt)
    gp_rmse = float(np.sqrt(np.mean((mean - yt) ** 2)))
    baseline_rmse = float(np.sqrt(np.mean((yt - yt.mean()) ** 2)))
    assert gp_rmse < baseline_rmse


def test_fit_accepts_a_flat_target_column():
    """The driver passes (N, 1); accepting (N,) too keeps callers from having
    to know which."""
    rng = np.random.default_rng(1)
    X = rng.uniform(0, 100, size=(10, 3))
    gp = GPRegressor(train_iters=5)
    gp.fit(X, _smooth(X))
    assert gp.fitted


def test_fit_rejects_mismatched_lengths():
    gp = GPRegressor(train_iters=5)
    with pytest.raises(ValueError, match="rows"):
        gp.fit(np.zeros((5, 3)), np.zeros((4, 1)))


def test_fit_rejects_an_empty_training_set():
    """An exact GP has nothing to condition on, and the caller has an
    acquisition bug rather than a modelling one."""
    gp = GPRegressor(train_iters=5)
    with pytest.raises(ValueError, match="no acquired points"):
        gp.fit(np.zeros((0, 3)), np.zeros((0, 1)))


def test_fit_rejects_a_one_dimensional_feature_array():
    gp = GPRegressor(train_iters=5)
    with pytest.raises(ValueError, match="2-D"):
        gp.fit(np.zeros(5), np.zeros(5))


def test_predict_before_fit_is_an_error_not_a_silent_zero():
    gp = GPRegressor(train_iters=5)
    with pytest.raises(RuntimeError, match="before fit"):
        gp.predict_f(np.zeros((3, 3)))


def test_refitting_replaces_the_model_rather_than_warm_starting():
    """The gpflow code built a fresh GPR on every refit, so an unlucky earlier
    fit could not poison later ones. Same here."""
    rng = np.random.default_rng(5)
    X1 = rng.uniform(0, 100, size=(8, 3))
    gp = GPRegressor(train_iters=10)
    gp.fit(X1, _smooth(X1))
    first = gp.predict_f(X1)[0]

    X2 = rng.uniform(0, 100, size=(20, 3))
    gp.fit(X2, _smooth(X2) + 10.0)
    second = gp.predict_f(X2)[0]

    assert second.shape == (20, 1)
    assert first.shape == (8, 1)
    # The second fit tracks its own (offset) targets, not the first fit's.
    assert second.mean() > first.mean() + 1.0
