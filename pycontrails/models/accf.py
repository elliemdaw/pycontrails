"""Algorithmic Climate Change Functions."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any, overload

import xarray as xr

import pycontrails
from pycontrails.core.flight import Flight
from pycontrails.core.met import MetDataArray, MetDataset, standardize_variables
from pycontrails.core.met_var import (
    AirTemperature,
    EastwardWind,
    Geopotential,
    NorthwardWind,
    RelativeHumidity,
    SpecificHumidity,
)
from pycontrails.core.models import Model, ModelParams
from pycontrails.core.vector import GeoVectorDataset
from pycontrails.datalib import ecmwf
from pycontrails.utils import dependencies


def wide_body_jets() -> set[str]:
    """Return a set of wide body jets."""
    return {
        "A332",
        "A333",
        "A338",
        "A339",
        "A342",
        "A343",
        "A345",
        "A356",
        "A359",
        "A388",
        "B762",
        "B763",
        "B764",
        "B772",
        "B773",
        "B778",
        "B779",
        "B788",
        "B789",
    }


def regional_jets() -> set[str]:
    """Return a set of regional jets."""
    return {
        "CRJ1",
        "CRJ2",
        "CRJ7",
        "CRJ8",
        "CRJ9",
        "CRJX",
        "E135",
        "E145",
        "E170",
        "E190",
    }


@dataclass
class ACCFParams(ModelParams):
    """Default ACCF model parameters.

    See `config-user.yml` definition at
    https://github.com/dlr-pa/climaccf
    """

    lat_bound: tuple[float, float] | None = None
    lon_bound: tuple[float, float] | None = None

    efficacy: bool = True
    efficacy_option: str = "lee_2021"

    accf_v: str = "V1.0"

    ch4_scaling: float = 1.0
    co2_scaling: float = 1.0
    cont_scaling: float = 1.0
    h2o_scaling: float = 1.0
    o3_scaling: float = 1.0

    forecast_step: float = 6.0

    sep_ri_rw: bool = False

    climate_indicator: str = "ATR"

    horizontal_resolution: float = 0.5

    emission_scenario: str = "pulse"

    time_horizon: int = 20

    pfca: str = "PCFA-ISSR"

    merged: bool = True

    #: RHI Threshold
    issr_rhi_threshold: float = 0.9
    issr_temp_threshold: float = 235

    sac_ei_h2o: float = 1.25
    sac_q: float = 43000000.0
    sac_eta: float = 0.3

    nox_ei: str = "TTV"

    PMO: bool = False


class ACCF(Model):
    """Compute Algorithmic Climate Change Functions (ACCF).

    This class is a wrapper over the DLR / UMadrid library
    `climaccf <https://github.com/dlr-pa/climaccf>`_,
    `DOI: 10.5281/zenodo.6977272 <https://doi.org/10.5281/zenodo.6977272>`_

    Parameters
    ----------
    met : MetDataset
        Dataset containing "air_temperature" and "specific_humidity" variables
    surface : MetDataset, optional
        Dataset containing "surface_solar_downward_radiation" and
        "top_net_thermal_radiation" variables

    References
    ----------
    - :cite:`dietmullerDlrpaClimaccfDataset2022`
    - :cite:`dietmullerPythonLibraryComputing2022`

    """

    name = "accr"
    long_name = "algorithmic climate change functions"
    met_variables = (
        AirTemperature,
        SpecificHumidity,
        ecmwf.PotentialVorticity,
        Geopotential,
        RelativeHumidity,
        NorthwardWind,
        EastwardWind,
        ecmwf.PotentialVorticity,
    )
    sur_variables = (ecmwf.SurfaceSolarDownwardRadiation, ecmwf.TopNetThermalRadiation)
    default_params = ACCFParams

    short_vars = {v.short_name for v in (*met_variables, *sur_variables)}

    # This variable won't get used since we are not writing the output
    # anywhere, but the library will complain if it's not defined
    path_lib = "./"

    def __init__(
        self,
        met: MetDataset,
        surface: MetDataset | None = None,
        params: dict[str, Any] | None = None,
        **params_kwargs: Any,
    ) -> None:
        # Normalize ECMWF variables
        met = standardize_variables(met, self.met_variables)

        # Ignore humidity scaling warning
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", module="pycontrails.core.models")
            super().__init__(met, params=params, **params_kwargs)

        if surface:
            surface = surface.copy()
            surface = standardize_variables(surface, self.sur_variables)
            surface.data = _rad_instantaneous_to_accumulated(surface.data)
            self.surface = surface

        self.p_settings = self._get_accf_config()

    @overload
    def eval(self, source: Flight, **params: Any) -> Flight: ...

    @overload
    def eval(self, source: GeoVectorDataset, **params: Any) -> GeoVectorDataset: ...

    @overload
    def eval(self, source: MetDataset | None = ..., **params: Any) -> MetDataArray: ...

    def eval(
        self, source: GeoVectorDataset | Flight | MetDataset | None = None, **params: Any
    ) -> GeoVectorDataset | Flight | MetDataArray:
        """Evaluate accfs along flight trajectory or on meteorology grid.

        Parameters
        ----------
        source : GeoVectorDataset | Flight | MetDataset | None, optional
            Input GeoVectorDataset or Flight.
            If None, evaluates at the :attr:`met` grid points.
        **params : Any
            Overwrite model parameters before eval

        Returns
        -------
        GeoVectorDataset | Flight | MetDataArray
            Returns `np.nan` if interpolating outside meteorology grid.

        Raises
        ------
        NotImplementedError
            Raises if input ``source`` is not supported.
        """
        try:
            from climaccf.accf import GeTaCCFs
        except ModuleNotFoundError as e:
            dependencies.raise_module_not_found_error(
                name="ACCF.eval method",
                package_name="climaccf",
                module_not_found_error=e,
                pycontrails_optional_package="accf",
            )

        self.update_params(params)
        if params:
            self.p_settings = self._get_accf_config()

        self.set_source(source)

        if isinstance(self.source, GeoVectorDataset):
            self.downselect_met()
            if hasattr(self, "surface"):
                self.surface = self.source.downselect_met(self.surface)

        if isinstance(self.source, MetDataset):
            if self.source["longitude"].size > 1:
                hres = abs(self.source["longitude"].data[1] - self.source["longitude"].data[0])
                self.params["horizontal_resolution"] = float(hres)
            elif self.source["latitude"].size > 1:
                hres = abs(self.source["latitude"].data[1] - self.source["latitude"].data[0])
                self.params["horizontal_resolution"] = float(hres)

        self.set_source_met()
        self._generate_weather_store()

        # check aircraft type and set in config if needed
        if self.params["nox_ei"] != "TTV":
            if isinstance(self.source, Flight):
                ac = self.source.attrs["aircraft_type"]
                if ac in wide_body_jets():
                    self.p_settings["ac_type"] = "wide-body"
                elif ac in regional_jets():
                    self.p_settings["ac_type"] = "regional"
                else:
                    self.p_settings["ac_type"] = "single-aisle"
            else:
                self.p_settings["ac_type"] = "wide-body"

        clim_imp = GeTaCCFs(self)
        clim_imp.get_accfs(**self.p_settings)
        aCCFs, _ = clim_imp.get_xarray()

        # assign ACCF outputs to source
        maCCFs = MetDataset(aCCFs)
        for key, arr in maCCFs.data.items():
            # skip met variables
            if key in self.short_vars:
                continue

            assert isinstance(key, str)
            if isinstance(self.source, GeoVectorDataset):
                self.source[key] = self.source.intersect_met(maCCFs[key])
            else:
                self.source[key] = (maCCFs.dim_order, arr.data)

            # Tag output with additional attrs when source is MetDataset
            if isinstance(self.source, MetDataset):
                attrs: dict[str, Any] = {
                    "description": self.long_name,
                    "pycontrails_version": pycontrails.__version__,
                }
                # FIXME
                if self.met is not None:
                    attrs["met_source"] = self.met.attrs.get("met_source", "unknown")

                self.source[key].data.attrs.update(attrs)

        return self.source  # type: ignore[return-value]

    def _generate_weather_store(self) -> None:
        from climaccf.weather_store import WeatherStore

        # The library does not call the coordinates by name, it just slices the
        # underlying data array, so we need to put them in the expected order.
        # It also needs variables to have the ECMWF short name
        if isinstance(self.met, MetDataset):
            ds_met = self.met.data.transpose("time", "level", "latitude", "longitude")
            name_dict = {v.standard_name: v.short_name for v in self.met_variables}
            ds_met = ds_met.rename(name_dict)
        else:
            ds_met = None

        if hasattr(self, "surface"):
            ds_sur = self.surface.data.squeeze().transpose("time", "latitude", "longitude")
            name_dict = {v.standard_name: v.short_name for v in self.sur_variables}
            ds_sur = ds_sur.rename(name_dict)
        else:
            ds_sur = None

        ws = WeatherStore(
            ds_met,
            ds_sur,
            ll_resolution=self.p_settings["horizontal_resolution"],
            forecast_step=self.p_settings["forecast_step"],
        )

        if self.p_settings["lat_bound"] and self.p_settings["lon_bound"]:
            ws.reduce_domain(
                {
                    "latitude": self.p_settings["lat_bound"],
                    "longitude": self.p_settings["lon_bound"],
                }
            )

        self.ds = ws.get_xarray()
        self.variable_names = ws.variable_names
        self.pre_variable_names = ws.pre_variable_names
        self.coordinate_names = ws.coordinate_names
        self.pre_coordinate_names = ws.pre_coordinate_names
        self.coordinates_bool = ws.coordinates_bool
        self.aCCF_bool = ws.aCCF_bool
        self.axes = ws.axes
        self.var_xr = ws.var_xr

    def _get_accf_config(self) -> dict[str, Any]:
        # a good portion of these will get ignored since we are not producing an
        # output file, but the library will complain if they aren't defined
        return {
            "lat_bound": self.params["lat_bound"],
            "lon_bound": self.params["lon_bound"],
            "time_bound": None,
            "horizontal_resolution": self.params["horizontal_resolution"],
            "forecast_step": self.params["forecast_step"],
            "NOx_aCCF": True,
            "NOx&inverse_EIs": self.params["nox_ei"],
            "output_format": "netCDF",
            "mean": False,
            "std": False,
            "merged": self.params["merged"],
            "aCCF-V": self.params["accf_v"],
            "efficacy": self.params["efficacy"],
            "efficacy-option": self.params["efficacy_option"],
            "emission_scenario": self.params["emission_scenario"],
            "climate_indicator": self.params["climate_indicator"],
            "TimeHorizon": self.params["time_horizon"],
            "ac_type": "wide-body",
            "sep_ri_rw": self.params["sep_ri_rw"],
            "PMO": self.params["PMO"],
            "aCCF-scalingF": {
                "CH4": self.params["ch4_scaling"],
                "CO2": self.params["co2_scaling"],
                "Cont.": self.params["cont_scaling"],
                "H2O": self.params["h2o_scaling"],
                "O3": self.params["o3_scaling"],
            },
            "PCFA": self.params["pfca"],
            "PCFA-ISSR": {
                "rhi_threshold": self.params["issr_rhi_threshold"],
                "temp_threshold": self.params["issr_temp_threshold"],
            },
            "PCFA-SAC": {
                "EI_H2O": self.params["sac_ei_h2o"],
                "Q": self.params["sac_q"],
                "eta": self.params["sac_eta"],
            },
            "Chotspots": False,
            "hotspots_binary": True,
            "color": "Reds",
            "geojson": False,
            "save_path": "./",
            "save_format": "netCDF",
        }


def _rad_instantaneous_to_accumulated(ds: xr.Dataset) -> xr.Dataset:
    """Convert instantaneous radiation to accumulated radiation."""

    for name, da in ds.items():
        try:
            unit = da.attrs["units"]
        except KeyError as e:
            msg = (
                f"Radiation data contains '{name}' variable "
                "but units are not specified. Provide units in the "
                f"rad['{name}'].attrs passed into ACCF."
            )
            raise KeyError(msg) from e

        if unit == "J m**-2":
            continue
        if unit != "W m**-2":
            msg = f"Unexpected units '{unit}' for '{name}'. Expected 'J m**-2' or 'W m**-2'."
            raise ValueError(msg)

        # Convert from W m**-2 to J m**-2
        da.attrs["units"] = "J m**-2"
        ds[name] = da * 3600.0

    return ds
