import geopandas as gpd
import pandas as pd

from average import areal_average, unit_averages
from catchment import load_catchment
from evap_grid import evap_anomaly_grid
from config import GLOBAL_MODEL, HYBAS_FILE, KEEP_RAW, N_SUBCATCHMENTS, NARCLIM_DIR, REGIONAL_CONFIG, SCENARIO, VARIABLES, YEARS
from download import download
from load import load_narclim
from results_db import load_climate, save_climate
from terrain_regions import terrain_regions


def read_data():
    """Return the Murrumbidgee catchment polygon."""
    return load_catchment()


def _reduce_climate(catchment, subcatchments, basins):
    """Download the run's NARCliM subsets, average them onto the units and display grid, store the result in the
    database, then delete the raw files (set KEEP_RAW=1 to keep them)."""
    if not all((NARCLIM_DIR / f"{var}_{year}.nc").exists() for var in VARIABLES for year in YEARS):
        download()
    narclim = load_narclim()
    reduced = (areal_average(narclim, catchment), unit_averages(narclim, subcatchments),
               unit_averages(narclim, basins), evap_anomaly_grid(narclim, catchment))
    narclim.close()
    save_climate((GLOBAL_MODEL, SCENARIO, REGIONAL_CONFIG), *reduced)
    if not KEEP_RAW:
        files = list(NARCLIM_DIR.glob("*.nc"))
        for f in files:
            f.unlink()
        print(f"1_masking: stored reduced climate in the database, deleted {len(files)} raw NARCliM files")
    return reduced


def run_masking(catchment):
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

    reduced = load_climate((GLOBAL_MODEL, SCENARIO, REGIONAL_CONFIG), subcatchments, basins) or _reduce_climate(catchment, subcatchments, basins)
    forcing, subcatchment_forcing, basin_forcing, evap_grid = reduced  # evap_grid: 4 km evaporation anomaly field for display
    return forcing, subcatchments, subcatchment_forcing, basins, basin_forcing, evap_grid
