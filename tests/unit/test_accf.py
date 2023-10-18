"""Test ACCF model"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pycontrails import Flight, MetDataset
from pycontrails.models.accf import ACCF


@pytest.fixture()
def fl() -> Flight:
    """Create a flight for testing."""

    n = 10000
    longitude = np.linspace(45, 75, n) + np.linspace(0, 1, n)
    latitude = np.linspace(50, 60, n) - np.linspace(0, 1, n)
    level = np.full_like(longitude, 225)

    start = np.datetime64("2022-11-11")
    time = pd.date_range(start, start + np.timedelta64(90, "m"), periods=n)
    return Flight(
        longitude=longitude,
        latitude=latitude,
        level=level,
        time=time,
        aircraft_type="B737",
        flight_id=17,
    )


def test_accf_default(met_accf_pl: MetDataset, met_accf_sl: MetDataset, fl: Flight) -> None:
    """Test Default accf algorithm."""

    pytest.importorskip("climaccf", reason="climaccf package not available")

    accf = ACCF(met=met_accf_pl, surface=met_accf_sl)
    out = accf.eval(fl)

    assert np.all(np.isfinite(out["aCCF_NOx"]))
