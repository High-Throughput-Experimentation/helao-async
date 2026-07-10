"""HISPEC spectral-to-CV calibration and voltage downsampling pipeline.

Helpers that pair an Andor spectroscopy parquet (or HLO) file with the
parent CV.hlo trace, fit a sawtooth to the CV voltage waveform, label
each spectrum by cycle/scan direction, merge in the spectral data,
downsample to a fixed voltage precision and interpolate current onto
the spectral time axis. Used by
:mod:`helao.deploy.hte.processors.hispec_process_all`.
"""

from helao.helpers.hlo_data import read_hlo
from helao.core.models.run_dir import RunDir
import pandas as pd
import numpy as np
import os
import json
from pathlib import Path
import ruamel.yaml
from typing import Union
from scipy.optimize import curve_fit
from scipy.interpolate import UnivariateSpline
from scipy.signal import sawtooth
import matplotlib.pyplot as plt


def yml_load(input: Union[str, Path]):
    """Parse a YAML document from a file path, a :class:`Path`, or a string.

    Args:
        input: Either a path-like pointing at an existing YAML file or
            the raw YAML text itself.

    Returns:
        The parsed YAML document as ruamel.yaml round-trip objects.

    Raises:
        ruamel.yaml.YAMLError: If the YAML content cannot be parsed.
    """
    yaml = ruamel.yaml.YAML(typ="rt")
    yaml.version = (1, 2)
    if isinstance(input, Path):
        with input.open("r") as f:
            obj = yaml.load(f)
    elif os.path.exists(input):
        with open(input, "r") as f:
            obj = yaml.load(f)
    else:
        obj = yaml.load(input)
    return obj


def read_CV_hlo(
    hlo_path: str,
    default_U_header: str = "Ewe_V",
    default_t_header: str = "t_s",
    default_cycle_header: str = "cycle",
    default_current_header: str = "I_A",
    return_additional_headers: list[str] = None,
    return_metadata: bool = False,
) -> pd.DataFrame:
    """Load a CV ``.hlo`` file into a DataFrame keeping only the chosen headers.

    Falls back through ``RUNS_ACTIVE`` -> ``RUNS_FINISHED`` -> ``RUNS_SYNCED``
    when the supplied path is missing.

    Args:
        hlo_path: Path to the CV HLO file.
        default_U_header: Column name to keep for the voltage trace.
        default_t_header: Column name to keep for the time trace.
        default_cycle_header: Column name to keep for the cycle index.
        default_current_header: Column name to keep for the current trace.
        return_additional_headers: Extra column names to include.
        return_metadata: If ``True``, also return the column-headings
            metadata dict.

    Returns:
        ``pandas.DataFrame``, or ``(metadata, DataFrame)`` when
        ``return_metadata`` is ``True``.

    Raises:
        FileNotFoundError: If the HLO file cannot be located after the
            fallback substitutions.
    """
    # combine the default headers with the areturn_additional_headers by adding them to a list
    if return_additional_headers is not None:
        headers = [
            default_U_header,
            default_t_header,
            default_cycle_header,
            default_current_header,
            *return_additional_headers,
        ]
    else:
        headers = [
            default_U_header,
            default_t_header,
            default_cycle_header,
            default_current_header,
        ]

    if not os.path.exists(hlo_path) and RunDir.ACTIVE.value in hlo_path:
        hlo_path = hlo_path.replace(RunDir.ACTIVE.value, RunDir.FINISHED.value)
    if not os.path.exists(hlo_path) and RunDir.FINISHED.value in hlo_path:
        hlo_path = hlo_path.replace(RunDir.FINISHED.value, RunDir.SYNCED.value)
    if not os.path.exists(hlo_path):
        raise FileNotFoundError(f"File {hlo_path} not found")

    meta, data = read_hlo(hlo_path, keep_keys=headers)

    if return_metadata:
        return meta["column_headings"], pd.DataFrame(data)
    else:
        return pd.DataFrame(data)


def read_spec_times_from_hlo(spec_file_path: str) -> pd.DataFrame:
    """Read only the ``tick_time`` column from an Andor spectroscopy HLO.

    The values are zero-shifted to the first sample and renamed to ``t_s``.

    Args:
        spec_file_path: Path to the spectroscopy HLO file.

    Returns:
        DataFrame with a single ``t_s`` column.
    """
    data = pd.DataFrame(read_hlo(spec_file_path, keep_keys=["tick_time"])[1])
    data.iloc[:, 0] = data.iloc[:, 0] - data.iloc[0, 0]
    # name the collumn t_s
    data.columns = ["t_s"]
    return data


def read_spectra_from_hlo(spec_file_path: str) -> pd.DataFrame:
    """Read all spectral channels from an Andor spectroscopy HLO file.

    Skips the ``tick_time`` column and names the remaining columns by
    the wavelength array stored under ``metadata['optional']['wl']``.

    Args:
        spec_file_path: Path to the spectroscopy HLO file.

    Returns:
        DataFrame whose columns are wavelengths and whose rows are
        spectra.
    """
    meta, data = read_hlo(spec_file_path, omit_keys=["tick_time"])
    # get the tick time from the metadata
    WL = meta["optional"]["wl"]

    data = pd.DataFrame(data)
    data.columns = WL

    return data


def read_spec_times_from_parquet(
    spec_file_path: str, default_time_header: str = "t_s"
) -> pd.DataFrame:
    """Read only the time column from a spectroscopy parquet file.

    Args:
        spec_file_path: Path to the parquet file.
        default_time_header: Name of the time column to load.

    Returns:
        Single-column DataFrame, or ``None`` if reading fails.
    """
    try:
        data = pd.DataFrame(
            pd.read_parquet(spec_file_path, columns=[default_time_header])
        )
    except Exception as e:
        print(e)
        print(
            f"Could not read parquet file - the dummy column name ({default_time_header}) which is needed partially read the parquet file  may be incorrect"
        )
        return None

    return data


def read_spectra_parquet(spec_file_path: str) -> pd.DataFrame:
    """Read a spectroscopy parquet file with the ``t_s`` column removed.

    Args:
        spec_file_path: Path to the spectroscopy parquet file.

    Returns:
        DataFrame of spectra without the time column.
    """
    data = pd.read_parquet(spec_file_path)
    data.drop(columns=["t_s"], inplace=True)
    return data


def generate_interpolation_function(
    CV: pd.DataFrame,
    starting_amp: float = 1,
    starting_phase: float = 0,
    starting_offset: float = 0,
    biologic: bool = True,
    default_CV_t_header: str = "t_s",
    default_CV_U_header: str = "Ewe_V",
    defult_CV_cycle_header: str = "cycle",
    plotbl: bool = False,
) -> tuple:
    """Fit a :func:`sawtooth2` voltage waveform to the CV ``U(t)`` data.

    Also writes the fitted parameters to ``interpolation.json`` and
    optionally renders a comparison plot.

    Args:
        CV: DataFrame containing time, voltage and cycle columns.
        starting_amp: Initial amplitude guess (flip sign if the fit
            converges poorly).
        starting_phase: Initial phase guess.
        starting_offset: Initial offset guess.
        biologic: When ``True``, treats cycle counts as zero-indexed.
        default_CV_t_header: Column header for time.
        default_CV_U_header: Column header for voltage.
        defult_CV_cycle_header: Column header for cycle index.
        plotbl: When ``True``, draws and saves a fit-vs-data plot.

    Returns:
        tuple: Fitted ``(amplitude, period, phase, offset)`` for
        :func:`sawtooth2`.
    """

    # extract the time and voltage data from the collumns 't_s' and 'Ewe_V'
    # as x_data and y_data respectively

    x_data = np.array(CV[default_CV_t_header])
    y_data = np.array(CV[default_CV_U_header])

    max_cycles = int(CV[defult_CV_cycle_header].max())
    if biologic:
        max_cycles = max_cycles + 1
    # Initial guess for the parameters [amplitude, phase], period is the max time
    initial_guess = [
        starting_amp,
        x_data.max() / max_cycles,
        starting_phase,
        starting_offset,
    ]

    # Fit the data to the custom sawtooth function
    popt, pcov = curve_fit(
        sawtooth2,
        x_data,
        y_data,
        p0=initial_guess,
        method="dogbox",
        maxfev=100000,  # Increase the number of iterations
    )
    # Extract the optimal parameters
    amplitude_fit, period_fit, phase_fit, offset_fit = popt

    # Print the fitted parameters

    # Generate fitted data
    y_fit = sawtooth2(x_data, amplitude_fit, period_fit, phase_fit, offset_fit)

    # Plot the original data and the fitted data
    if plotbl:
        fig, ax = plt.subplots()
        ax.plot(x_data, y_data, label="Original data")
        ax.plot(x_data, y_fit, color="red", linestyle="--", label="Fitted data")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Voltage (V)")
        # add a title of fitted vs measured time/ voltage
        plt.title("Interpolation function used to covert t to V")

        # add ledgend and place it on outside of plot on the right
        ax.legend(loc="center left", bbox_to_anchor=(1, 0.5))
        plt.show()

        # save the plot as interpolation.png
        fig.savefig("interpolation.png")

    interpolation = (amplitude_fit, period_fit, phase_fit, offset_fit)
    interpol_write = {
        "amplitude": amplitude_fit,
        "period": period_fit,
        "phase": phase_fit,
        "offset": offset_fit,
    }
    # write to JSON
    with open("interpolation.json", "w") as f:
        json.dump(interpol_write, f)
    return interpolation


def sawtooth2(time, amplitude, period, phase, offset):
    """Evaluate a phase/offset-shifted symmetric sawtooth wave.

    Args:
        time: Scalar or array of times.
        amplitude: Peak amplitude.
        period: Wave period.
        phase: Phase shift along time.
        offset: Vertical offset.

    Returns:
        Voltage value(s) matching the shape of ``time``.
    """
    return amplitude * sawtooth((2 * np.pi * time) / (period) - phase, 0.5) + offset


def interpolate_spec_time_to_U(
    spec_times: pd.DataFrame, interp_tup: tuple, default_time_header: str = "t_s"
) -> pd.DataFrame:
    """Add an ``Ewe_V`` column to ``spec_times`` using a fitted sawtooth.

    Args:
        spec_times: DataFrame containing a time column.
        interp_tup: ``(amp, period, phase, offset)`` from
            :func:`generate_interpolation_function`.
        default_time_header: Name of the time column in ``spec_times``.

    Returns:
        The input DataFrame mutated with a new ``Ewe_V`` column.
    """

    spec_times["Ewe_V"] = sawtooth2(spec_times[default_time_header], *interp_tup)

    return spec_times


def round_10ms(time) -> float:
    """Round a time (or list of times) to 3 decimal places.

    Args:
        time: A ``float``, ``int`` or list of either.

    Returns:
        The rounded value or list of rounded values.

    Raises:
        ValueError: If ``time`` is not a number or list of numbers.
    """
    if isinstance(time, list):
        return [np.round(x, 3) for x in time]
    elif isinstance(time, float) or isinstance(time, int):
        return np.round(time, 3)
    else:
        raise ValueError(
            f"type time is {type(time)} Time must be a float, an int or a list of floats or ints"
        )


def generate_min_max_list_for_cycles(
    CV_data: pd.DataFrame,
    default_time_header: str = "t_s",
    default_cycle_header="cycle",
) -> dict:
    """Return per-cycle ``[start_time, end_time]`` bounds from CV data.

    For cycle 0 the bounds are ``[min, max]``; for later cycles the
    start is the previous cycle's end so the intervals tile the time
    axis.

    Args:
        CV_data: DataFrame containing time and cycle columns.
        default_time_header: Name of the time column.
        default_cycle_header: Name of the cycle column.

    Returns:
        dict: Mapping of cycle index to ``[start, end]`` rounded times.
    """
    min_max_dict = {}
    previous_max = None
    for cycle, sub_frame in CV_data.groupby(default_cycle_header):
        if cycle == 0:
            min_max_dict[cycle] = round_10ms(
                [
                    sub_frame[default_time_header].min(),
                    sub_frame[default_time_header].max(),
                ]
            )
            previous_max = round_10ms(sub_frame[default_time_header].max())
        if cycle > 0:
            min_max_dict[cycle] = round_10ms(
                [previous_max, sub_frame[default_time_header].max()]
            )
            previous_max = round_10ms(sub_frame[default_time_header].max())
    return min_max_dict


def return_cycle_for_time(time: float, min_max_dict: dict) -> int:
    """Look up which cycle interval a given time falls into.

    Times under ~20 ms are treated as cycle 0; times beyond the final
    interval's upper bound are clamped to the last cycle.

    Args:
        time: Time value to classify.
        min_max_dict: Mapping built by
            :func:`generate_min_max_list_for_cycles`.

    Returns:
        Cycle index containing ``time``.

    Raises:
        ValueError: If ``time`` cannot be placed in any interval.
    """
    max_cycle = max([int(x) for x in min_max_dict.keys()])
    for cycle, min_max in min_max_dict.items():
        time = round_10ms(time)
        if time <= 0.02:
            return 0
        if int(cycle) == 0:
            if time <= min_max[1]:
                return cycle
        if int(cycle) > 0:
            if time >= min_max[0] and time <= min_max[1]:
                return cycle
            # if the time is greater than the max time of the last cycle
            # it is in the last cycle
        if int(cycle) == max_cycle:
            if time >= min_max[1]:
                # print(f"Time {time} is greater than the max time of cycle {cycle} which is {min_max[1]} this time was assigned to cycle {cycle} but should be removed in a later function")
                return cycle
            else:
                raise ValueError(
                    f"Time {time} is outside of all bounds. Cycle was {cycle} and max was {min_max[1]}"
                )


def get_cycles_for_spec_times(
    calibration_df: pd.DataFrame,
    CV_data: pd.DataFrame,
    default_time_header1="t_s",
    default_cycle_header1="cycle",
) -> pd.DataFrame:
    """Tag each spectroscopy time row with its parent CV cycle.

    Args:
        calibration_df: DataFrame with a time column to annotate.
        CV_data: DataFrame providing per-cycle time intervals.
        default_time_header1: Time column name (shared by both frames).
        default_cycle_header1: Cycle column name to write.

    Returns:
        ``calibration_df`` with the cycle column populated.
    """
    min_max_dict = generate_min_max_list_for_cycles(
        CV_data,
        default_time_header=default_time_header1,
        default_cycle_header=default_cycle_header1,
    )
    calibration_df[default_cycle_header1] = calibration_df[default_time_header1].apply(
        lambda x: return_cycle_for_time(x, min_max_dict)
    )
    return calibration_df


def calcualte_scan_direction_for_spec_times(
    calibration_df: pd.DataFrame, interp_tup: tuple, default_time_header: str = "t_s"
) -> pd.DataFrame:
    """Label each spectroscopy time as ``anodic`` or ``cathodic`` scan direction.

    Args:
        calibration_df: DataFrame with a time column to annotate.
        interp_tup: Fitted sawtooth parameters from
            :func:`generate_interpolation_function`.
        default_time_header: Name of the time column.

    Returns:
        ``calibration_df`` with a new ``direction`` column inserted.
    """
    # calculate the derivative of the sawtooth2 function
    time_array = np.array(calibration_df[default_time_header])
    deriv = np.diff(sawtooth2(time_array, *interp_tup)) > 0
    # insert the first value of the derivative to the start of the array because np.diff reduces the length by 1
    deriv = np.insert(deriv, 0, deriv[0])

    # plt.plot(time_array, deriv)

    # Initialize scan_direction as an array of strings instead of zeros
    scan_direction = np.full(len(time_array), "", dtype=object)

    # Set the scan direction to 'anodic' if the derivative is greater than zero
    scan_direction[deriv] = "anodic"
    # Set the scan direction to 'cathodic' if the derivative is less than zero
    scan_direction[~deriv] = "cathodic"

    # add scan_direction as a new collumn to the Andorspec_calibrated dataframe
    calibration_df.insert(1, "direction", scan_direction)
    return calibration_df


def error_correct_scan(scan_df: pd.DataFrame) -> pd.DataFrame:
    """Flip mislabeled scan directions inside one cycle/direction group.

    Detects index gaps inside ``scan_df``; the smaller side of each
    gap is assumed misclassified and has its ``direction`` value
    swapped to the opposite label.

    Args:
        scan_df: DataFrame for a single cycle and nominal direction.

    Returns:
        ``scan_df`` with the corrected ``direction`` column.
    """
    num_errors = 0
    for i in range(scan_df.shape[0]):
        if i == 0:
            continue
        if scan_df.index[i] - scan_df.index[i - 1] > 1:
            # split the dataframe
            left_df = scan_df.iloc[:i]
            right_df = scan_df.iloc[i:]
            incorrect_df = right_df if left_df.shape[0] > right_df.shape[0] else left_df
            # print(incorrect_df['direction'])
            if incorrect_df["direction"].nunique() == 1:
                # print("The direction of the incorrect dataframe is the same")
                # print(f"The direction is {incorrect_df['direction'].iloc[0]}")
                correct_direction = (
                    "anodic"
                    if incorrect_df["direction"].iloc[0] == "cathodic"
                    else "cathodic"
                )
                # print(f"The correct direction is {correct_direction}")
                num_errors += 1

            # get the index of the incorrect dataframe
            incorrect_index = incorrect_df.index

            # set all values at the index of the incorrect dataframe to the correct direction
            scan_df.loc[incorrect_index, "direction"] = correct_direction
    # print(f'{num_errors} errors corrected')

    return scan_df


def error_correct_scan_direction_for_all_cycles(
    calibration_df: pd.DataFrame,
) -> pd.DataFrame:
    """Apply :func:`error_correct_scan` to every (cycle, direction) group.

    Args:
        calibration_df: DataFrame containing ``cycle`` and
            ``direction`` columns.

    Returns:
        ``calibration_df`` with all groups corrected in place.
    """
    for cycle, frame in calibration_df.groupby("cycle"):
        for scan, sub_frame in frame.groupby("direction"):
            corrected_sub_frame = error_correct_scan(sub_frame)
            calibration_df.iloc[corrected_sub_frame.index, :] = corrected_sub_frame
    return calibration_df


def read_in_spectra_calibrate(
    calibration_df: pd.DataFrame, spec_path: str, read_hlo: bool = False
) -> pd.DataFrame:
    """Horizontally concatenate calibration metadata and spectra.

    Args:
        calibration_df: DataFrame with ``t_s``, ``Ewe_V``, ``cycle``
            and ``direction`` columns.
        spec_path: Path to the spectra file.
        read_hlo: When ``True``, parse an HLO file; otherwise parquet.

    Returns:
        ``calibration_df`` concatenated with the spectral columns.
    """
    if read_hlo:
        spectra_df = read_spectra_from_hlo(spec_path)
    else:
        spectra_df = read_spectra_parquet(spec_path)
    return pd.concat([calibration_df, spectra_df], axis=1)


def drop_times_larger_than_CV_max_time(
    calibrated_spectra: pd.DataFrame,
    CV_data: pd.DataFrame,
    default_time_header: str = "t_s",
) -> pd.DataFrame:
    """Drop spectral rows whose timestamp exceeds the CV's final time.

    Args:
        calibrated_spectra: DataFrame holding the calibrated spectra.
        CV_data: DataFrame whose time column defines the cutoff.
        default_time_header: Time column name in both frames.

    Returns:
        ``calibrated_spectra`` filtered to the CV time window.
    """
    max_time = CV_data[default_time_header].max()

    times = calibrated_spectra[default_time_header]
    cut_times = times[times > max_time]
    print(
        f"Times larger than the max time of the CV data were found and cut: {cut_times}"
    )
    return calibrated_spectra[calibrated_spectra[default_time_header] <= max_time]


def downsample_to_1mV_precision(
    calibrated_spectra: pd.DataFrame, precision: float = 0.001
) -> pd.DataFrame:
    """Bin spectra to a fixed voltage precision and average within bins.

    Iterates each (cycle, direction) group, rounds ``Ewe_V`` to the
    nearest multiple of ``precision`` and averages all rows sharing a
    bin. Final columns are renamed to ``U (V)`` and ``t (s)``.

    Args:
        calibrated_spectra: Calibrated spectral DataFrame with
            ``cycle`` and ``direction`` columns.
        precision: Voltage bin width in volts.

    Returns:
        Concatenated DataFrame indexed by ``U (V)``.
    """
    totaldf = pd.DataFrame()
    for cycle, frame in calibrated_spectra.groupby("cycle"):
        for scan, sub_frame in frame.groupby("direction"):
            # drop the direction collumn
            sub_frame.drop("direction", axis=1, inplace=True)
            try:

                voltage_grouping = sub_frame["Ewe_V"]
            except Exception as e:
                raise ValueError("error in getting the voltage grouping")

            voltage_grouping = np.round(voltage_grouping / precision) * precision
            try:
                sub_frame["Ewe_V"] = voltage_grouping
            except Exception as e:
                raise ValueError("error in setting the voltage grouping")
            # sub_frame.astype(float)
            try:
                sub_frame = sub_frame.groupby(sub_frame["Ewe_V"]).mean()

                # rename the index E_we_V to U (V)
                sub_frame.index.rename("U (V)", inplace=True)

                sub_frame["t_s"] = np.round(sub_frame["t_s"], 3)
            except Exception as e:
                raise ValueError("error in grouping by voltage")
            # insert a collumn called 'direction' as the 4th collumn with the value of scan
            sub_frame.insert(1, "direction", scan)

            # print(sub_frame.head())

            totaldf = pd.concat([totaldf, sub_frame])
    # reset the index
    # totaldf.reset_index(drop=True, inplace=True)
    # rename the Ewe_V collumn U (V)
    totaldf.rename(columns={"Ewe_V": "U (V)"}, inplace=True)
    # rename t_s to t (s)
    totaldf.rename(columns={"t_s": "t (s)"}, inplace=True)

    # print(len(totaldf.loc['U (V)']))
    return totaldf


def fit_current_time_to_univariate_spline(
    CV: pd.DataFrame,
    smoothing_factor: float = 0.000000001,
    default_t_header: str = "t_s",
    default_J_header: str = "I_A",
    plotbl: bool = False,
) -> UnivariateSpline:
    """Fit a smoothing :class:`UnivariateSpline` to current vs. time.

    Args:
        CV: DataFrame containing time and current columns.
        smoothing_factor: Spline smoothing factor.
        default_t_header: Time column name.
        default_J_header: Current column name.
        plotbl: When ``True``, plot the fit against the raw data.

    Returns:
        Fitted spline object callable as ``spl(t)``.
    """

    # create a univariate spline object
    t = CV[default_t_header].astype(float)
    J = CV[default_J_header].astype(float)
    # Sort the data by voltage - this fixes any artifacts
    sorted_indices = np.argsort(t)
    t_sorted = t.iloc[sorted_indices]
    J_sorted = J.iloc[sorted_indices]

    # Fit the CV to a spline function
    spl = UnivariateSpline(t_sorted, J_sorted)
    spl.set_smoothing_factor(smoothing_factor)
    if plotbl:
        # Plot the spline function
        plt.plot(t_sorted, spl(t_sorted), "r", lw=3)

        # Plot the original data
        plt.plot(t_sorted, J_sorted, "b", lw=1)
        plt.xlabel("Voltage (E)")
        plt.ylabel("Current (J)")
        plt.title("CV Spline Fit")
        # set the x range from -0.2 to 1.5

    return spl


def interpolate_spectral_time_to_current(
    spectral_df_calib: pd.DataFrame,
    CV_dataframe: pd.DataFrame,
    default_time_header_CV: str = "t_s",
    default_J_header_CV: str = "I_A",
    default_time_header_spec: str = "t (s)",
    smoothing_weight: float = 0.000000001,
) -> pd.DataFrame:
    """Add a ``J (A)`` column to ``spectral_df_calib`` from a CV spline fit.

    Args:
        spectral_df_calib: DataFrame with a spectral time column.
        CV_dataframe: DataFrame providing time/current for the spline.
        default_time_header_CV: Time column name in the CV data.
        default_J_header_CV: Current column name in the CV data.
        default_time_header_spec: Time column name in the spectra.
        smoothing_weight: Spline smoothing factor.

    Returns:
        ``spectral_df_calib`` with the interpolated ``J (A)`` column.
    """
    spl = fit_current_time_to_univariate_spline(
        CV_dataframe,
        default_t_header=default_time_header_CV,
        default_J_header=default_J_header_CV,
        smoothing_factor=smoothing_weight,
    )

    spectral_df_calib.insert(
        1, "J (A)", spl(spectral_df_calib[default_time_header_spec])
    )

    return spectral_df_calib


def fully_read_and_calibrate_parquet(
    cv_dataframe: pd.DataFrame | str,
    spec_path: str,
    default_time_header: str = "t_s",
    default_U_header: str = "Ewe_V",
    default_current_header: str = "I_A",
    default_cycle_header: str = "cycle",
    biologic: bool = True,
    starting_amp: float = 1,
    starting_phase: float = 0,
    starting_offset: float = 0,
    spline_strength: float = 0.000000001,
    read_hlo: bool = False,
    write_file: bool = False,
    output_path: str = None,
    precision: float = 0.001,
) -> pd.DataFrame:
    """Run the full HISPEC calibration pipeline on a spectra parquet file.

    Steps performed: load spectral times, fit a sawtooth to the CV's
    ``U(t)``, interpolate spectra time to voltage, label cycles and
    scan directions (with error correction), merge in the spectra,
    drop times beyond the CV window, downsample to a fixed voltage
    precision and interpolate current onto the spectra time axis.

    Args:
        cv_dataframe: Either a CV DataFrame or a path to a CV HLO file.
        spec_path: Path to the spectra parquet file.
        default_time_header: Time column name shared across inputs.
        default_U_header: CV voltage column name.
        default_current_header: CV current column name.
        default_cycle_header: CV cycle column name.
        biologic: Whether the CV came from a Biologic potentiostat
            (zero-indexed cycles).
        starting_amp: Initial sawtooth amplitude guess.
        starting_phase: Initial sawtooth phase guess.
        starting_offset: Initial sawtooth offset guess.
        spline_strength: Current-spline smoothing factor.
        read_hlo: Reserved flag toggling HLO-based spectra reads.
        write_file: When ``True``, also write the result to parquet.
        output_path: Optional output prefix/directory for the parquet.
        precision: Voltage bin width for downsampling.

    Returns:
        Calibrated, downsampled spectra DataFrame sorted by ``t (s)``.
    """
    calibration_df = read_spec_times_from_parquet(
        spec_file_path=spec_path, default_time_header=default_time_header
    )

    if isinstance(cv_dataframe, pd.DataFrame):
        CV = cv_dataframe
    else:
        CV = read_CV_hlo(
            cv_dataframe,
            default_t_header=default_time_header,
            default_U_header=default_U_header,
            default_cycle_header=default_cycle_header,
            default_current_header=default_current_header,
            return_metadata=False,
        )

    interp = generate_interpolation_function(
        CV,
        starting_amp=starting_amp,
        starting_phase=starting_phase,
        starting_offset=starting_offset,
        biologic=biologic,
        default_CV_t_header=default_time_header,
        default_CV_U_header=default_U_header,
        defult_CV_cycle_header=default_cycle_header,
    )

    calibration_df = interpolate_spec_time_to_U(
        spec_times=calibration_df,
        interp_tup=interp,
        default_time_header=default_time_header,
    )

    calibration_df = get_cycles_for_spec_times(
        calibration_df=calibration_df,
        CV_data=CV,
        default_time_header1=default_time_header,
        default_cycle_header1=default_cycle_header,
    )

    calibration_df = calcualte_scan_direction_for_spec_times(
        calibration_df=calibration_df,
        interp_tup=interp,
        default_time_header=default_time_header,
    )

    calibration_df = error_correct_scan_direction_for_all_cycles(
        calibration_df=calibration_df
    )

    spectra_calibrated = read_in_spectra_calibrate(
        calibration_df=calibration_df, spec_path=spec_path, read_hlo=False
    )

    drop_times_larger_than_CV_max_time(
        calibrated_spectra=spectra_calibrated,
        CV_data=CV,
        default_time_header=default_time_header,
    )

    spectra_calibrated = downsample_to_1mV_precision(
        calibrated_spectra=spectra_calibrated, precision=precision
    )

    spectra_calibrated = interpolate_spectral_time_to_current(
        spectral_df_calib=spectra_calibrated,
        CV_dataframe=CV,
        default_time_header_CV=default_time_header,
        default_J_header_CV=default_current_header,
        default_time_header_spec="t (s)",
        smoothing_weight=spline_strength,
    )

    spectra_calibrated.sort_values(by="t (s)", inplace=True)
    if write_file:
        if output_path is None:
            output_path = "spectra_calibrated.parquet"
        else:
            output_path = output_path + "spectra_calibrated.parquet"
        spectra_calibrated.to_parquet(output_path, compression="zstd")

    return spectra_calibrated


if __name__ == "__main__":

    cv_path = r"/Users/benj/Documents/SpEC_Class_2/test_data/newdata/CV-3.3.0.0__0.hlo"
    spec_path = r"/Users/benj/Documents/SpEC_Class_2/test_data/newdata/test.parquet"
    fully_read_and_calibrate_parquet(
        cv_dataframe=cv_path, spec_path=spec_path, write_file=True
    )
