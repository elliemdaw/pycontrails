"""
``pycontrails`` public API.

Copyright 2021-2023 Breakthrough Energy

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from __future__ import annotations

import logging
from importlib import metadata

import dask

# Work around for https://github.com/pydata/xarray/issues/7259
# Only occurs for xarray 2022.11 and above
try:
    import netCDF4
except ModuleNotFoundError:
    pass

from pycontrails.core.cache import DiskCacheStore, GCPCacheStore
from pycontrails.core.datalib import MetDataSource
from pycontrails.core.fleet import Fleet
from pycontrails.core.flight import Aircraft, Flight
from pycontrails.core.fuel import Fuel, HydrogenFuel, JetA, SAFBlend
from pycontrails.core.met import MetDataArray, MetDataset
from pycontrails.core.met_var import MetVariable
from pycontrails.core.models import Model, ModelParams
from pycontrails.core.vector import GeoVectorDataset, VectorDataset

try:
    __version__ = metadata.version("pycontrails")
except metadata.PackageNotFoundError:
    __version__ = "unknown"

__license__ = "Apache-2.0"
__url__ = "https://py.contrails.org"

log = logging.getLogger(__name__)

# Hardcode the dask warning silence config
dask.config.set({"array.slicing.split_large_chunks": False})


__all__ = [
    "Aircraft",
    "DiskCacheStore",
    "Fleet",
    "Flight",
    "Fuel",
    "GCPCacheStore",
    "GeoVectorDataset",
    "HydrogenFuel",
    "JetA",
    "MetDataArray",
    "MetDataset",
    "MetDataSource",
    "MetVariable",
    "Model",
    "ModelParams",
    "SAFBlend",
    "VectorDataset",
]
