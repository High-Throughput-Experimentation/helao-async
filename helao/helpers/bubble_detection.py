"""Heuristic bubble detection from open-circuit potential traces."""

from scipy.signal import find_peaks
import statistics
import pandas as pd

from helao.helpers import helao_logging as logging  # get LOGGER from BaseAPI instance

global LOGGER
LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def bubble_detection(
    data: pd.DataFrame,
    RSD_threshold: float,
    simple_threshold: float,
    signal_change_threshold: float,
    amplitude_threshold: float,
) -> bool:
    """Detect bubble formation in a potential-time trace using four heuristics.

    Runs four independent tests on the input trace and returns ``True`` if any
    of them fires. The tests are: relative standard deviation of ``Ewe_V``
    exceeding ``RSD_threshold``; the most recent ``Ewe_V`` sample falling below
    ``simple_threshold``; the largest 0.5-second-spaced sample-to-sample delta
    exceeding ``signal_change_threshold``; and the mean peak-to-trough
    amplitude exceeding ``amplitude_threshold``.

    Args:
        data: Trace containing ``t_s`` (time in seconds) and ``Ewe_V``
            (working-electrode potential) columns.
        RSD_threshold: Relative standard deviation cutoff in percent.
        simple_threshold: Lower bound on the final ``Ewe_V`` sample.
        signal_change_threshold: Maximum allowed change between successive
            0.5-second-spaced samples.
        amplitude_threshold: Maximum allowed mean peak-to-trough amplitude.

    Returns:
        ``True`` if any heuristic indicates a bubble, otherwise ``False``.
    """
    required_cols = {"t_s", "Ewe_V"}
    missing_cols = required_cols.difference(set(data.columns))
    if missing_cols:
        LOGGER.warning(
            f"bubble_detection skipped: missing columns {sorted(missing_cols)} in OCV data."
        )
        return False

    if data.empty or len(data["Ewe_V"]) < 2:
        LOGGER.warning("bubble_detection skipped: not enough OCV points for analysis.")
        return False

    try:
        # relative standard deviation test
        SD = statistics.stdev(list(data["Ewe_V"]))
        mean = statistics.mean(list(data["Ewe_V"]))
        if mean == 0:
            RSD_test_result = False
            LOGGER.warning("bubble_detection: Ewe_V mean is zero; skipping RSD test.")
        else:
            RSD = (SD / mean) * 100
            RSD_test_result = RSD > RSD_threshold

        # simple threshold test
        # checks whether last value is higher than set threshold
        last_val = data["Ewe_V"].iloc[-1]
        simple_test_result = last_val < simple_threshold

        # change in signal test
        # takes every 1s data and compared the change in signal average and whether that is above a threshold
        modulo_seconds = 0.5
        idx = []
        for index, row in data.iterrows():
            if row["t_s"] % modulo_seconds == 0:
                idx.append(index)

        modulo_E = data.loc[idx]["Ewe_V"]

        E_changes = []
        for i in range(len(modulo_E) - 1):
            E_changes.append(abs(modulo_E.iloc[i] - modulo_E.iloc[i + 1]))
        signal_change_result = any(i > signal_change_threshold for i in E_changes)

        # peak finding test
        # Find peaks (maxima)
        peaks, properties_peaks = find_peaks(data["Ewe_V"])
        peak_avg = data["Ewe_V"].iloc[peaks].mean()
        # Find troughs (minima) - by finding peaks in the inverted signal
        troughs, properties_troughs = find_peaks(-data["Ewe_V"])
        troughs_avg = data["Ewe_V"].iloc[troughs].mean()

        mean_amplitude = abs(peak_avg - troughs_avg)

        amplitude_test_result = mean_amplitude > amplitude_threshold

    # print("peaks at t:")
    # print(test_red["t_s"].iloc[peaks])

    # print("\ntroughs at t:")
    # print(test_red["t_s"].iloc[troughs])

    # mean_amplitude = peak_avg - troughs_avg
    # print("\n Mean amplitude:")
    # print(mean_amplitude)

    # print("E_change: {}".format(E_changes))
    # print("mean_amplitude: {}".format(mean_amplitude))
    # print("last value: {}".format(last_val))
    # print("RSD: {}".format(RSD))

    # return (
    #     RSD_test_result,
    #     simple_test_result,
    #     signal_change_result,
    #     amplitude_test_result,
    # )

    # print("\nBubble detected:")
    # print("RSD test: " + str(RSD_test_result))
    # print("simple test: " + str(simple_test_result))
    # print("signal change test: " + str(signal_change_result))
    # print("amplitude test: " + str(amplitude_test_result))

        has_bubble = (
            RSD_test_result
            or simple_test_result
            or signal_change_result
            or amplitude_test_result
        )
        for label, test in [
            ("RSD_test", RSD_test_result),
            ("simple_test", simple_test_result),
            ("single_change_test", signal_change_result),
            ("amplitude_test", amplitude_test_result),
        ]:
            LOGGER.debug(f"{label}: {test}")

        return bool(has_bubble)
    except Exception:
        LOGGER.error("bubble_detection failed; returning has_bubble=False", exc_info=True)
        return False
