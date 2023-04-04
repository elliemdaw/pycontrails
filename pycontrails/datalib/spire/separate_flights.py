import dataclasses
import pandas as pd
import numpy as np
import numpy.typing as npt

import pycontrails.core.ads_b as adsb
from pycontrails.core.flight import _dt_waypoints
from pycontrails.ext.bada import BADA3

bada_3 = BADA3()
FLIGHT_MINIMUM_N_WYPTS = 5


@dataclasses.dataclass
class FlightTrajectories:
    """Container to categorise unique flight trajectories.
    """
    validated: list[pd.DataFrame]
    deferred: list[pd.DataFrame]
    rejected: list[pd.DataFrame]


def identify_and_categorise_unique_flights(
        df_flight_waypoints: pd.DataFrame, t_cut_off: pd.Timestamp
) -> FlightTrajectories:
    # For each subset of waypoints with the same ICAO address, identify unique flights
    df_flight_waypoints = adsb.downsample_waypoints(df_flight_waypoints, time_resolution=10, time_var="timestamp")
    df_flight_waypoints = _fill_missing_callsign_for_satellite_waypoints(df_flight_waypoints)
    flights = adsb.separate_unique_flights_from_waypoints(
        df_flight_waypoints, columns=["tail_number", "aircraft_type_icao", "callsign"]
    )
    # TODO: Smooth altitude
    flights = _separate_by_ground_indicator(flights)
    print(" ")
    # TODO: Check segment length, dt, multiple cruise phase
    # TODO: diverted flights?
    flight_trajectories = categorise_flight_trajectories(flights, t_cut_off)
    return flight_trajectories


def _fill_missing_callsign_for_satellite_waypoints(df_flight_waypoints: pd.DataFrame) -> pd.DataFrame:
    """
    Backward and forward filling of missing callsigns.

    ADS-B waypoints that are recorded by satellite often do not include the callsign metadata.

    Parameters
    ----------
    df_flight_waypoints: pd.DataFrame
        Waypoints with the same ICAO address, must contain the "callsign" and "collection_type" columns

    Returns
    -------
    pd.DataFrame
        Waypoints with the same ICAO address, where the "callsign" is filled
    """
    if np.any(df_flight_waypoints["collection_type"] == "satellite"):
        is_missing = df_flight_waypoints["callsign"].isna() & (df_flight_waypoints["collection_type"] == "satellite")

        if np.any(is_missing):
            df_flight_waypoints["callsign"] = df_flight_waypoints["callsign"].fillna(method="ffill")
            df_flight_waypoints["callsign"] = df_flight_waypoints["callsign"].fillna(method="bfill")

    return df_flight_waypoints


# TODO: Why 6000 feet?
def _separate_by_ground_indicator(
        flights: list[pd.DataFrame], *, min_n_wypt: int = FLIGHT_MINIMUM_N_WYPTS
) -> list[pd.DataFrame]:
    """
    Identify and separate unique flights using the ground indicator.

    Parameters
    ----------
    flights: list[pd.DataFrame]
        List of DataFrames containing waypoints from unique flights.
    min_n_wypt: int
        Minimum number of waypoints required for flight to be included

    Returns
    -------
    list[pd.DataFrame]
        List of DataFrames containing waypoints from unique flights that are separated by ground indicator.

    Notes
    -----
    Waypoints in the taxi phase will be omitted.
    """
    flights_checked = list()

    for df_flight_waypoints in flights:
        df_flight_waypoints.reset_index(inplace=True, drop=True)
        is_on_ground = df_flight_waypoints["on_ground"] & (df_flight_waypoints["altitude_baro"] < 6000)

        # Continue to next flight if all recorded waypoints are not on the ground
        if np.all(~is_on_ground):
            flights_checked.append(df_flight_waypoints)
            continue

        # Separate flights: only include flights if there are waypoints that are off the ground
        i_ground = df_flight_waypoints[is_on_ground].index.values
        i_cutoff_1 = i_ground[0] + 1
        i_cutoff_2 = i_ground[-1]
        df_flight_1 = df_flight_waypoints.iloc[:i_cutoff_1].copy()
        df_flight_2 = df_flight_waypoints.iloc[i_cutoff_2:].copy()

        if ~np.all(df_flight_1["on_ground"]) & (len(df_flight_1) > min_n_wypt):
            flights_checked.append(df_flight_1)

        if ~np.all(df_flight_2["on_ground"]) & (len(df_flight_2) > min_n_wypt):
            flights_checked.append(df_flight_2)

        #: Check waypoints between i_cutoff_1 and i_cutoff_2, include if there are waypoints off the ground
        #: If there are multiple flights "df_flight_3", it will be identified in "separate_by_multiple_cruise_phase".
        df_flight_3 = df_flight_waypoints.iloc[i_cutoff_1:i_cutoff_2].copy()

        if ~np.all(df_flight_3["on_ground"]) & (len(df_flight_3) > min_n_wypt):
            is_off_the_ground = ~df_flight_3["on_ground"].astype(bool)
            flights_checked.append(df_flight_3[is_off_the_ground].copy())

    return flights_checked


def separate_flights_multiple_cruise_phase():
    return


def categorise_flight_trajectories(
        flights: list[pd.DataFrame], t_cut_off: pd.Timestamp
) -> FlightTrajectories:
    """
    Categorise unique flight trajectories (validated, deferred, rejected).

    Parameters
    ----------
    flights: list[pd.DataFrame]
        List of DataFrames containing waypoints from unique flights.
    t_cut_off: pd.Timestamp
        Time of the final recorded waypoint that is provided by the full set of waypoints in the raw ADS-B file

    Returns
    -------
    FlightTrajectories
        Validated, deferred, and rejected flight trajectories.

    Notes
    -----
    Flights are categorised as
        (1) Validated: Identified flight trajectory passes all the validation test,
        (2) Deferred: The remaining trajectory could be in the next file,
        (3) Rejected: Identified flight trajectory contains anomalies and fails the validation test
    """
    validated = list()
    deferred = list()
    rejected = list()

    for df_flight_waypoints in flights:
        status = validate_flight_trajectory(df_flight_waypoints, t_cut_off)

        if status["reject"]:
            rejected.append(df_flight_waypoints.copy())
        elif status["n_waypoints"] & status["cruise_phase"] & status["no_altitude_anomaly"] & status["complete"]:
            validated.append(df_flight_waypoints.copy())
        else:
            deferred.append(df_flight_waypoints.copy())

    return FlightTrajectories(validated=validated, deferred=deferred, rejected=rejected)


def validate_flight_trajectory(
        df_flight_waypoints: pd.DataFrame, t_cut_off: pd.Timestamp, *, min_n_wypt: int = FLIGHT_MINIMUM_N_WYPTS
) -> dict[str, bool]:
    """
    Ensure that the subset of waypoints only contains one unique flight.

    Parameters
    ----------
    df_flight_waypoints: pd.DataFrame
        Subset of flight waypoints
    t_cut_off: pd.Timestamp
        Time of the final recorded waypoint that is provided by the full set of waypoints in the raw ADS-B file
    min_n_wypt: int
        Minimum number of waypoints required for flight to be accepted

    Returns
    -------
    dict[str, bool]
        Boolean indicating if flight trajectory satisfied the three conditions outlined in `notes`

    Notes
    -----
    The subset of waypoints must satisfy all the following conditions to validate the flight trajectory:
    (1) Must contain more than `min_n_wypt` waypoints,
    (2) There must be a cruise phase of flight
    (3) There must not be waypoints below the minimum cruising altitude throughout the cruise phase.
    (4) A flight must be "complete", defined when one of these conditions are satisfied:
        - Final waypoint is on the ground, altitude < 6000 feet and speed < 150 knots (278 km/h),
        - Final waypoint is < 10,000 feet, in descent, and > 2 h have passed since `current_time_slice`, or
        - At least 12 h have passed since `t_cut_off` (remaining trajectory might not be recorded).

    Trajectory is rejected if (1) - (4) are false and > 24 h have passed since `t_cut_off`.
    """
    cols_req = ["altitude_baro", "timestamp", "aircraft_type_icao"]
    validity = np.zeros(4, dtype=bool)

    if np.any(~pd.Series(cols_req).isin(df_flight_waypoints.columns)):
        raise KeyError("DataFrame do not contain longitude and/or latitude column.")

    # Minimum cruise altitude
    altitude_ceiling_ft = bada_3.ptf_param_dict[df_flight_waypoints["aircraft_type_icao"].iloc[0]].max_altitude_ft
    min_cruise_altitude_ft = 0.5 * altitude_ceiling_ft

    # Flight duration
    dt_sec = _dt_waypoints(df_flight_waypoints["timestamp"].values)
    flight_duration_s = np.nansum(dt_sec)
    is_short_haul = (flight_duration_s < 3600)

    # Flight phase
    flight_phase: adsb.FlightPhaseDetailed = adsb.identify_phase_of_flight_detailed(
        df_flight_waypoints["altitude_baro"].values, dt_sec,
        threshold_rocd=250, min_cruise_alt_ft=min_cruise_altitude_ft
    )

    # Validate flight trajectory
    validity[0] = len(df_flight_waypoints) > min_n_wypt
    validity[1] = np.any(flight_phase.cruise)
    validity[2] = no_altitude_anomaly_during_cruise(
        df_flight_waypoints["altitude_baro"].values, flight_phase.cruise,
        min_cruise_alt_ft=min_cruise_altitude_ft
    )

    # Relax constraint for short-haul flights
    if is_short_haul & (validity[1] is False) & (validity[2] is False):
        validity[1] = np.any(flight_phase.level_flight)
        validity[2] = True

    # Check that flight is complete
    wypt_final = df_flight_waypoints.iloc[-1]
    dt = (t_cut_off - wypt_final["timestamp"]) / np.timedelta64(1, "h")

    if np.all(validity[:3]):    # If first three conditions are valid
        is_descent = np.any(flight_phase.descent[-5:]) | np.any(flight_phase.level_flight[-5:])
        complete_1 = wypt_final["on_ground"] & (wypt_final["altitude_baro"] < 6000) & (wypt_final["speed"] < 150)
        complete_2 = (wypt_final["altitude_baro"] < 10000) & is_descent & (dt > 2)
        complete_3 = dt > 12
        validity[3] = (complete_1 | complete_2 | complete_3)

    return {
        "n_waypoints": validity[0],
        "cruise_phase": validity[1],
        "no_altitude_anomaly": validity[2],
        "complete": validity[3],
        "reject": (np.all(~validity) & (dt > 24))
     }

# TODO: Check this function


def no_altitude_anomaly_during_cruise(
        altitude_ft: npt.NDArray[np.float_],
        flight_phase_cruise: npt.NDArray[np.bool_], *,
        min_cruise_alt_ft: float
) -> bool:
    """
    Check for altitude anomaly during cruise phase of flight.

    Parameters
    ----------
    altitude_ft: npt.NDArray[np.float_]
        Altitude of each waypoint, [:math:`ft`]
    flight_phase_cruise: npt.NDArray[np.bool_]
        Booleans marking if the waypoints are at cruise
    min_cruise_alt_ft: np.ndarray
        Minimum threshold altitude for cruise, [:math:`ft`]
        This is specific for each aircraft type, and can be approximated as 50% of the altitude ceiling.

    Returns
    -------
    bool
        True if no altitude anomaly is detected.

    Notes
    -----
    The presence of unrealistically low altitudes during the cruise phase of flight is an indicator that the flight
    trajectory could contain multiple unique flights.
    """
    if np.all(~flight_phase_cruise):
        return False

    i_cruise_start = np.min(np.argwhere(flight_phase_cruise))
    i_cruise_end = min(np.max(np.argwhere(flight_phase_cruise)), len(flight_phase_cruise))
    altitude_at_cruise = altitude_ft[i_cruise_start:i_cruise_end]
    return np.all(altitude_at_cruise >= min_cruise_alt_ft)


