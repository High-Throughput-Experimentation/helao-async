from scipy.signal import find_peaks
import statistics
import pandas as pd

from helao.helpers import logging  # get LOGGER from BaseAPI instance

global LOGGER
if logging.LOGGER is None:
    LOGGER = logging.make_LOGGER(LOGGER_name="bubble_detection_standalone")
else:
    LOGGER = logging.LOGGER


def bubble_detection(
    data: pd.DataFrame,
    RSD_threshold: float,
    simple_threshold: float,
    signal_change_threshold: float,
    amplitude_threshold: float,
) -> bool:
    """
    data must be pd.Dataframe with t, and E column
    """
    # relative standard deviation test
    SD = statistics.stdev(list(data["Ewe_V"]))
    mean = statistics.mean(list(data["Ewe_V"]))
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
