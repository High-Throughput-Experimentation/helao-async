"""Unit tests for helao.framework.support.bubble_detection."""

import pandas as pd
import pytest
from helao.framework.support.bubble_detection import bubble_detection


def test_bubble_detection_no_bubble():
    """Test that a stable, low-amplitude OCP trace returns False."""
    # Create a stable trace with small oscillations
    data = pd.DataFrame({
        "t_s": [i * 0.1 for i in range(100)],  # 0 to 9.9 seconds
        "Ewe_V": [0.5 + 0.001 * (i % 5) for i in range(100)],  # Very small oscillations around 0.5V
    })

    result = bubble_detection(
        data=data,
        RSD_threshold=10.0,  # 10% RSD threshold
        simple_threshold=0.4,  # Must stay above 0.4V
        signal_change_threshold=0.05,  # Max change per 0.5s window
        amplitude_threshold=0.02,  # Max peak-to-trough amplitude
    )

    assert result is False


def test_bubble_detection_low_final_value():
    """Test that a trace ending below simple_threshold returns True."""
    # Create a trace that drops significantly at the end
    data = pd.DataFrame({
        "t_s": [i * 0.1 for i in range(100)],
        "Ewe_V": [0.5 if i < 90 else 0.3 for i in range(100)],  # Drop below 0.4V at end
    })

    result = bubble_detection(
        data=data,
        RSD_threshold=10.0,
        simple_threshold=0.4,  # Final value (0.3V) is below this
        signal_change_threshold=0.1,
        amplitude_threshold=0.1,
    )

    assert result is True


def test_bubble_detection_high_rsd():
    """Test that high relative standard deviation returns True."""
    # Create a trace with high variability
    data = pd.DataFrame({
        "t_s": [i * 0.1 for i in range(100)],
        "Ewe_V": [0.3 if i % 2 == 0 else 0.7 for i in range(100)],  # Large oscillations
    })

    result = bubble_detection(
        data=data,
        RSD_threshold=10.0,  # RSD will be > 66%
        simple_threshold=0.0,  # Won't trigger on final value
        signal_change_threshold=1.0,  # Very high threshold
        amplitude_threshold=1.0,  # Very high threshold
    )

    assert result is True


def test_bubble_detection_signal_change():
    """Test that large signal changes return True."""
    # Create a trace with a sharp step change
    data = pd.DataFrame({
        "t_s": [i * 0.1 for i in range(100)],
        "Ewe_V": [0.5 if i < 50 else 0.0 for i in range(100)],  # Sharp drop at i=50
    })

    result = bubble_detection(
        data=data,
        RSD_threshold=50.0,  # High RSD threshold
        simple_threshold=-1.0,  # Won't trigger
        signal_change_threshold=0.1,  # Low threshold; will detect 0.5V drop
        amplitude_threshold=1.0,
    )

    assert result is True


def test_bubble_detection_amplitude():
    """Test that high peak-to-trough amplitude returns True."""
    import numpy as np

    # Create a sinusoidal trace with large amplitude
    t = np.linspace(0, 10, 200)
    data = pd.DataFrame({
        "t_s": t,
        "Ewe_V": 0.5 + 0.3 * np.sin(2 * np.pi * t),  # 0.6V amplitude oscillation
    })

    result = bubble_detection(
        data=data,
        RSD_threshold=50.0,  # High threshold
        simple_threshold=0.1,  # Won't trigger
        signal_change_threshold=1.0,  # High threshold
        amplitude_threshold=0.4,  # Low threshold; will detect 0.6V amplitude
    )

    assert result is True


def test_bubble_detection_missing_columns():
    """Test that missing required columns returns False with warning."""
    data = pd.DataFrame({
        "t_s": [0, 1, 2],
        "voltage": [0.5, 0.5, 0.5],  # Wrong column name
    })

    result = bubble_detection(
        data=data,
        RSD_threshold=10.0,
        simple_threshold=0.4,
        signal_change_threshold=0.05,
        amplitude_threshold=0.02,
    )

    assert result is False


def test_bubble_detection_empty_dataframe():
    """Test that an empty DataFrame returns False."""
    data = pd.DataFrame()

    result = bubble_detection(
        data=data,
        RSD_threshold=10.0,
        simple_threshold=0.4,
        signal_change_threshold=0.05,
        amplitude_threshold=0.02,
    )

    assert result is False


def test_bubble_detection_too_few_points():
    """Test that a DataFrame with < 2 points returns False."""
    data = pd.DataFrame({
        "t_s": [0],
        "Ewe_V": [0.5],
    })

    result = bubble_detection(
        data=data,
        RSD_threshold=10.0,
        simple_threshold=0.4,
        signal_change_threshold=0.05,
        amplitude_threshold=0.02,
    )

    assert result is False


def test_bubble_detection_zero_mean():
    """Test that a trace with zero mean skips RSD test but can still detect via other heuristics."""
    data = pd.DataFrame({
        "t_s": [i * 0.1 for i in range(100)],
        "Ewe_V": [0.05 if i % 2 == 0 else -0.05 for i in range(100)],  # Oscillates around 0
    })

    result = bubble_detection(
        data=data,
        RSD_threshold=10.0,
        simple_threshold=0.0,  # Final value is -0.05, triggering simple test
        signal_change_threshold=1.0,
        amplitude_threshold=1.0,
    )

    assert result is True
