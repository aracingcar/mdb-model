import geopandas as gpd
import pandas as pd

from average import areal_average, unit_averages
from catchment import load_catchment
from evap_grid import evap_anomaly_grid
from config import HYBAS_FILE, N_SUBCATCHMENTS
from load import load_narclim
from terrain_regions import terrain_regions


def read_data():
    """Return (narclim, catchment): P and PET grids in mm/day, and the Murrumbidgee polygon."""
    return load_narclim(), load_catchment()


def run_masking(narclim, catchment):
    """Return (forcing, subcatchments, subcatchment_forcing, basins, basin_forcing, evap_grid): daily area-weighted P and PET.

    basins are the individual terrain watersheds (plus a LOWLAND unit for the western plains) that the
    rainfall-runoff and routing steps work on; subcatchments group them into 12 reaches for display. evap_grid is the
    gridded (native 4 km) evaporation anomaly that the display drapes over the terrain.
    """
    subcatchments, basins = terrain_regions(catchment, HYBAS_FILE, n=N_SUBCATCHMENTS)
    lowland = subcatchments.iloc[[-1]]
    outlet = subcatchments.iloc[-2]["outlet_basin"]
    lowland_unit = gpd.GeoDataFrame({"subcatchment": ["LOWLAND"], "hybas_id": [0], "next_id": [outlet], "region": [lowland.iloc[0]["subcatchment"]],
                                     "area_km2": [lowland.iloc[0]["area_km2"]]}, geometry=lowland.geometry.values, crs=basins.crs)
    basins = pd.concat([basins, lowland_unit], ignore_index=True)

    forcing = areal_average(narclim, catchment)
    subcatchment_forcing = unit_averages(narclim, subcatchments)
    basin_forcing = unit_averages(narclim, basins)
    evap_grid = evap_anomaly_grid(narclim, catchment)  # 4 km evaporation anomaly field for display
    return forcing, subcatchments, subcatchment_forcing, basins, basin_forcing, evap_grid
