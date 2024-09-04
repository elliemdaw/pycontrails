"""Utilities for working with ECMWF model-level data."""

import datetime
import pathlib

import numpy as np
import numpy.typing as npt
import pandas as pd
import xarray as xr

from pycontrails.physics import units

_path_to_static = pathlib.Path(__file__).parent / "static"
MODEL_LEVELS_PATH = _path_to_static / "model_level_dataframe_v20240418.csv"


def pressure_levels_at_model_levels_constant_surface_pressure(
    alt_ft_min: float | None = None,
    alt_ft_max: float | None = None,
) -> list[int]:
    """Return the pressure levels at each model level assuming a constant surface pressure.

    This function assumes 137 model levels.

    The pressure levels are rounded to the nearest hPa.

    Parameters
    ----------
    alt_ft_min : float | None
        Minimum altitude, [:math:`ft`]. If None, there is no minimum altitude
        used in filtering the ``MODEL_LEVELS_PATH`` table.
    alt_ft_max : float | None
        Maximum altitude, [:math:`ft`]. If None, there is no maximum altitude
        used in filtering the ``MODEL_LEVELS_PATH`` table.

    Returns
    -------
    list[int]
        List of pressure levels, [:math:`hPa`].
    """
    usecols = ["n", "Geometric Altitude [m]", "pf [hPa]"]
    df = pd.read_csv(MODEL_LEVELS_PATH, usecols=usecols, index_col="n")

    filt = df.index >= 1  # exclude degenerate model level 0
    if alt_ft_min is not None:
        alt_m_min = units.ft_to_m(alt_ft_min)
        filt &= df["Geometric Altitude [m]"] >= alt_m_min
    if alt_ft_max is not None:
        alt_m_max = units.ft_to_m(alt_ft_max)
        filt &= df["Geometric Altitude [m]"] <= alt_m_max

    return df.loc[filt, "pf [hPa]"].round().astype(int).tolist()


def _cache_model_level_dataframe() -> pd.DataFrame:
    """Regenerate static model level data file.

    Read the ERA5 L137 model level definitions published by ECMWF
    and cache it in a static file for use by this module.
    This should only be used by model developers, and only if ECMWF model
    level definitions change. ``MODEL_LEVEL_PATH`` must be manually
    updated to use newly-cached files.

    Requires the `lxml <https://lxml.de/>`_ package to be installed.
    """

    url = "https://confluence.ecmwf.int/display/UDOC/L137+model+level+definitions"
    df = pd.read_html(url, na_values="-", index_col="n")[0]

    today = datetime.datetime.now()
    new_file_path = _path_to_static / f"model_level_dataframe_v{today.strftime('%Y%m%d')}.csv"
    if new_file_path.is_file():
        msg = f"Static file already exists at {new_file_path}"
        raise ValueError(msg)

    df.to_csv(new_file_path)
